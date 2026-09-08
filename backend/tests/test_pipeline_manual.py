"""管线级：手动模式（start_ts + stroke_type）。

全程离线：窗口抽帧 / 检测 / 拼贴 / LLM 队列全部注入替身。用户只标动作"大致
开始"的时间点，后端在标注点之后的窗口内定位击球帧，再以击球帧为锚按固定时长
切四帧。验证：
- 走 extract_frames_window（而非全片 extract_frames）；发球的前向窗口更长；
- 只产出 1 个动作，击球帧取标注点之后"最晚出现的强峰"（更早的引拍峰不算）；
- 用户标注的 stroke_type 落库并透传给 LLM 队列，且不被模型返回值覆盖。
"""
import types

from app import pipeline, storage
from app.schemas import FrameDet

FPS = 15.0
W, H = 640, 480
START_TS = 10.0          # 用户标注的"动作大致开始"
BEFORE = 0.7             # manual_before_margin_s
N = 45                   # 窗口帧数（覆盖到 START+2.3s）
CONTACT_FRAME = 26       # 向前挥拍/击球峰（ts ≈ START+1.03s）


def _make_wrist_x(spike_frames):
    """背景每帧 ~1px 抖动；spike_frames 中的帧及其下一帧大幅快挥，产生速度峰。"""
    def wx(i: int) -> float:
        x = 100 + (i % 2)
        if i in spike_frames:
            x = 400.0
        elif i - 1 in spike_frames:
            x = 100.0
        return x
    return wx


def _fake_dets(n, spike_frames=(CONTACT_FRAME,)):
    wx = _make_wrist_x(set(spike_frames))
    return [
        FrameDet(
            frame_idx=i,
            ts=START_TS - BEFORE + i / FPS,
            player_box=(10, 10, 110, 310),
            player_conf=0.9,
            wrist=(wx(i), 200.0),
            pose_ok=True,
        )
        for i in range(n)
    ]


def _run_manual(job_id, submit, monkeypatch, tmp_path, stroke_type="backhand",
                spike_frames=(CONTACT_FRAME,), **kw):
    monkeypatch.setattr("app.config.settings.jobs_dir", tmp_path)
    storage.create_job(job_id, "v.mp4")

    captured = {}

    def fake_window(video, fps, center_ts, before, after):
        captured["center"] = center_ts
        captured["before"] = before
        captured["after"] = after
        return (
            [None] * N,
            [START_TS - BEFORE + i / FPS for i in range(N)],
            W,
            H,
        )

    monkeypatch.setattr(pipeline, "extract_frames_window", fake_window)
    monkeypatch.setattr(
        pipeline, "extract_frames",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("不应全片抽帧")),
    )
    monkeypatch.setattr(
        pipeline, "Detector",
        lambda: types.SimpleNamespace(
            detect_frames=lambda frames, ts, tp, target_ts=None:
                _fake_dets(len(frames), spike_frames)),
    )
    monkeypatch.setattr(pipeline, "make_montage", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "llm_queue", types.SimpleNamespace(submit=submit))
    result = pipeline.run_pipeline(
        job_id, start_ts=START_TS, stroke_type=stroke_type, **kw
    )
    return result, captured


def test_manual_anchors_contact_and_keeps_stroke(monkeypatch, tmp_path):
    submitted = []

    def fake_submit(path, stroke_type=None):
        submitted.append(stroke_type)
        # 模型即便返回 forehand，手动模式也应保留用户标注的 backhand
        return {
            "stroke_type": "forehand",
            "scores": {"准备": 7},
            "overall": 7.0,
            "issues": [],
            "advice": "建议",
        }

    result, cap = _run_manual("m1", fake_submit, monkeypatch, tmp_path)

    # 窗口边界：标注点前留 0.7s 余量，正反手向前覆盖 1.7s
    t0 = cap["center"] - cap["before"]
    t1 = cap["center"] + cap["after"]
    assert abs((START_TS - t0) - 0.7) < 1e-6
    assert abs((t1 - START_TS) - 1.7) < 1e-6

    assert result.status == "done"
    assert len(result.actions) == 1
    rec = result.actions[0]
    assert rec.stroke_type == "backhand"           # 用户标注不被模型覆盖
    assert submitted == ["backhand"]                # 透传给 LLM
    # 击球帧锚定在标注点之后的接触峰（CONTACT_FRAME）
    assert rec.peak_ts > START_TS
    assert abs(rec.peak_ts - (START_TS - BEFORE + CONTACT_FRAME / FPS)) < 0.2


def test_manual_prefers_later_contact_over_early_backswing(monkeypatch, tmp_path):
    """更早的引拍峰（frame 10）不应被当成击球；应取更晚的接触峰（frame 28）。"""
    def fake_submit(path, stroke_type=None):
        return {"stroke_type": "forehand", "scores": {}, "overall": 7.0,
                "issues": [], "advice": ""}

    result, _cap = _run_manual(
        "m4", fake_submit, monkeypatch, tmp_path,
        stroke_type="forehand", spike_frames=(10, CONTACT_FRAME),
    )
    rec = result.actions[0]
    contact_ts = START_TS - BEFORE + CONTACT_FRAME / FPS
    backswing_ts = START_TS - BEFORE + 10 / FPS
    assert abs(rec.peak_ts - contact_ts) < 0.2
    assert rec.peak_ts > backswing_ts + 0.3


def test_manual_serve_uses_longer_window(monkeypatch, tmp_path):
    def fake_submit(path, stroke_type=None):
        return {"stroke_type": "serve", "scores": {}, "overall": 8.0,
                "issues": [], "advice": ""}

    _result, cap = _run_manual(
        "m2", fake_submit, monkeypatch, tmp_path, stroke_type="serve"
    )
    t1 = cap["center"] + cap["after"]
    assert abs((t1 - START_TS) - 3.8) < 1e-6  # 发球动作链更长，前向窗口 3.8s


def test_manual_preview_skips_llm(monkeypatch, tmp_path):
    def fake_submit(*a, **k):
        raise AssertionError("预览模式不应调用 LLM")

    result, _cap = _run_manual(
        "m3", fake_submit, monkeypatch, tmp_path, skip_llm=True
    )
    assert result.status == "done"
    assert len(result.actions) == 1
    rec = result.actions[0]
    assert rec.status == "pending"         # 未分析
    assert rec.stroke_type == "backhand"   # 预览也带用户标注，结果页可显示标签
