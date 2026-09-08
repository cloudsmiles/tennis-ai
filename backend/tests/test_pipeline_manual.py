"""管线级：手动模式（start_ts + stroke_type）。

全程离线：窗口抽帧 / 检测 / 拼贴 / LLM 队列全部注入替身。用户只标动作"大致
开始"的时间点，后端应在其后的窗口内用速度峰值自动定位击球帧。验证：
- 走 extract_frames_window（而非全片 extract_frames），窗口在标注点之后，
  发球的前向窗口比正手/反手更长；
- 只产出 1 个动作，击球帧由窗口内的速度峰值决定（在标注点之后），而非标注点本身；
- 用户标注的 stroke_type 落库并透传给 LLM 队列，且不被模型返回值覆盖。
"""
import types

from app import pipeline, storage
from app.schemas import FrameDet

FPS = 15.0
W, H = 640, 480
START_TS = 10.0          # 用户标注的"动作大致开始"
BEFORE = 0.5             # manual_before_margin_s
N = 38                   # 窗口帧数（覆盖 ~2.5s）
IMPACT_FRAME = 19        # 窗口内挥拍峰值所在帧（ts ≈ START+0.77s）


def _wrist_x(i: int) -> float:
    """背景每帧 ~1px 抖动；IMPACT_FRAME/下一帧大幅快挥，产生一个明显速度峰。"""
    x = 100 + (i % 2)
    if i == IMPACT_FRAME:
        x = 400.0
    elif i == IMPACT_FRAME + 1:
        x = 100.0
    return x


def _fake_dets(n):
    return [
        FrameDet(
            frame_idx=i,
            ts=START_TS - BEFORE + i / FPS,
            player_box=(10, 10, 110, 310),
            player_conf=0.9,
            wrist=(_wrist_x(i), 200.0),
            pose_ok=True,
        )
        for i in range(n)
    ]


def _run_manual(job_id, submit, monkeypatch, tmp_path, stroke_type="backhand", **kw):
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
    # 全片抽帧若被调用即视为走错分支
    monkeypatch.setattr(
        pipeline, "extract_frames",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("不应全片抽帧")),
    )
    monkeypatch.setattr(
        pipeline, "Detector",
        lambda: types.SimpleNamespace(
            detect_frames=lambda frames, ts, tp, target_ts=None:
                _fake_dets(len(frames))),
    )
    monkeypatch.setattr(pipeline, "make_montage", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "llm_queue", types.SimpleNamespace(submit=submit))
    result = pipeline.run_pipeline(
        job_id, start_ts=START_TS, stroke_type=stroke_type, **kw
    )
    return result, captured


def test_manual_finds_impact_after_start_and_keeps_stroke(monkeypatch, tmp_path):
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

    # 窗口边界：从标注点向前覆盖 2.0s（正手/反手）、向前留 0.5s 余量
    t0 = cap["center"] - cap["before"]
    t1 = cap["center"] + cap["after"]
    assert abs((START_TS - t0) - 0.5) < 1e-6
    assert abs((t1 - START_TS) - 2.0) < 1e-6

    assert result.status == "done"
    assert len(result.actions) == 1
    rec = result.actions[0]
    assert rec.stroke_type == "backhand"           # 用户标注不被模型覆盖
    assert submitted == ["backhand"]                # 透传给 LLM
    # 击球帧由峰值自动定位：在标注点之后、接近 IMPACT_FRAME 的时间（≈START+0.77s）
    assert rec.peak_ts > START_TS
    assert abs(rec.peak_ts - (START_TS - BEFORE + IMPACT_FRAME / FPS)) < 0.25


def test_manual_serve_uses_longer_window(monkeypatch, tmp_path):
    def fake_submit(path, stroke_type=None):
        return {"stroke_type": "serve", "scores": {}, "overall": 8.0,
                "issues": [], "advice": ""}

    _result, cap = _run_manual(
        "m2", fake_submit, monkeypatch, tmp_path, stroke_type="serve"
    )
    t1 = cap["center"] + cap["after"]
    assert abs((t1 - START_TS) - 3.5) < 1e-6  # 发球动作链更长，前向窗口 3.5s


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
