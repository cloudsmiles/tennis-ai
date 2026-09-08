"""管线级：手动模式（hit_ts + stroke_type）。

全程离线：窗口抽帧 / 检测 / 拼贴 / LLM 队列全部注入替身。验证：
- 走 extract_frames_window（而非全片 extract_frames）；
- 只产出 1 个动作，击球帧取距 hit_ts 最近的帧；
- 用户标注的 stroke_type 落库并透传给 LLM 队列，且不被模型返回值覆盖。
"""
import types

from app import pipeline, storage
from app.schemas import FrameDet

FPS = 15.0
W, H = 640, 480
HIT_TS = 10.0


def _fake_dets(n):
    return [
        FrameDet(
            frame_idx=i,
            ts=HIT_TS - 0.9 + i / FPS,
            player_box=(10, 10, 110, 310),
            player_conf=0.9,
            pose_ok=True,
        )
        for i in range(n)
    ]


def _run_manual(job_id, submit, monkeypatch, tmp_path, **kw):
    monkeypatch.setattr("app.config.settings.jobs_dir", tmp_path)
    storage.create_job(job_id, "v.mp4")

    def fake_window(video, fps, center_ts, before, after):
        assert abs(center_ts - HIT_TS) < 1e-6  # 手动模式围绕用户时间戳取窗
        n = 24
        return (
            [None] * n,
            [HIT_TS - 0.9 + i / FPS for i in range(n)],
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
        lambda: types.SimpleNamespace(detect_frames=lambda frames, ts, tp: _fake_dets(len(frames))),
    )
    monkeypatch.setattr(pipeline, "make_montage", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "llm_queue", types.SimpleNamespace(submit=submit))
    return pipeline.run_pipeline(job_id, hit_ts=HIT_TS, stroke_type="backhand", **kw)


def test_manual_single_action_uses_window_and_keeps_stroke(monkeypatch, tmp_path):
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

    result = _run_manual("m1", fake_submit, monkeypatch, tmp_path)

    assert result.status == "done"
    assert len(result.actions) == 1
    rec = result.actions[0]
    assert rec.stroke_type == "backhand"          # 用户标注不被覆盖
    assert abs(rec.peak_ts - HIT_TS) < 1.0 / FPS   # 击球帧≈用户时间戳
    assert submitted == ["backhand"]               # 透传给 LLM


def test_manual_preview_skips_llm(monkeypatch, tmp_path):
    def fake_submit(*a, **k):
        raise AssertionError("预览模式不应调用 LLM")

    result = _run_manual("m2", fake_submit, monkeypatch, tmp_path, skip_llm=True)

    assert result.status == "done"
    assert len(result.actions) == 1
    rec = result.actions[0]
    assert rec.status == "pending"        # 未分析
    assert rec.stroke_type == "backhand"  # 预览也带用户标注，结果页可显示标签
