"""管线级：手动模式（start_ts + end_ts + stroke_type）。

全程离线：窗口抽帧 / 检测 / 拼贴 / LLM 队列全部注入替身。用户用进度条框出单个
动作的时间范围（起=准备/引拍开始，止=随挥结束），后端在这个紧贴动作的窗口内
自动找击球帧、按姿态差异选关键帧。验证：
- 走 extract_frames_window（而非全片 extract_frames）；窗口 = 范围两端各加 margin；
- 击球帧落在用户范围内部、自动识别（不经过全片速度峰，也无需用户给击球时刻）；
- 用户标注的 stroke_type 落库并透传给 LLM 队列，且不被模型返回值覆盖；
- 正反手/发球均出六帧（拼贴事件规格）。
"""
import types

import numpy as np

from app import pipeline, storage
from app.cv.keyframes import event_frame_specs
from app.schemas import FrameDet

FPS = 15.0
W, H = 640, 480
CONTACT = 10.0          # 合成挥拍的真实击球时刻
START_TS = 9.0          # 用户框的动作起点（就绪/引拍前）
END_TS = 10.9           # 用户框的动作终点（随挥到对侧之后）
MARGIN = 0.35           # settings.manual_window_margin_s


def _fake_dets(ts):
    """在时间轴上注入一次反手挥拍：以距 CONTACT 最近的帧 c 为击球帧。
    击球定位按持拍手腕高度（前挥段最高点=触球）：蓄力拍头下沉(y250)、
    触球最高(y150)、随挥收拍(y220)；横向轨迹引拍到 x320、随挥到对侧 x30。"""
    n = len(ts)
    c = min(range(n), key=lambda i: abs(ts[i] - CONTACT))
    xw = [(0, 210.0), (c - 10, 210.0), (c - 4, 320.0), (c - 1, 240.0),
          (c, 150.0), (c + 8, 30.0), (n - 1, 30.0)]
    yw = [(0, 210.0), (c - 10, 210.0), (c - 4, 250.0), (c - 1, 200.0),
          (c, 150.0), (c + 8, 220.0), (n - 1, 220.0)]
    ks = [k for k, _ in xw]
    xs = np.interp(np.arange(n), ks, [v for _, v in xw])
    ys = np.interp(np.arange(n), ks, [v for _, v in yw])
    return [
        FrameDet(
            frame_idx=i,
            ts=ts[i],
            player_box=(10, 10, 110, 310),
            player_conf=0.9,
            wrist=(float(xs[i]), float(ys[i])),
            pose_ok=True,
        )
        for i in range(n)
    ]


def _run_manual(job_id, submit, monkeypatch, tmp_path, stroke_type="backhand",
                **kw):
    monkeypatch.setattr("app.config.settings.jobs_dir", tmp_path)
    storage.create_job(job_id, "v.mp4")

    captured = {}
    montage_events = []

    def fake_window(video, fps, center_ts, before, after):
        captured["center"] = center_ts
        captured["before"] = before
        captured["after"] = after
        n = round((before + after) * FPS) + 1
        ts = [center_ts - before + i / FPS for i in range(n)]
        return [None] * n, ts, W, H

    monkeypatch.setattr(pipeline, "extract_frames_window", fake_window)
    monkeypatch.setattr(
        pipeline,
        "extract_frames",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("不应全片抽帧")),
    )
    monkeypatch.setattr(
        pipeline,
        "Detector",
        lambda: types.SimpleNamespace(
            detect_frames=lambda frames, ts, tp, target_ts=None,
                on_progress=None: _fake_dets(ts)),
    )

    def fake_montage(frames, dets, ev, path, w, h):
        montage_events.append(ev)

    monkeypatch.setattr(pipeline, "make_montage", fake_montage)
    monkeypatch.setattr(pipeline, "make_annotated_montage", fake_montage)
    monkeypatch.setattr(pipeline, "llm_queue",
                        types.SimpleNamespace(submit=submit))
    result = pipeline.run_pipeline(
        job_id, start_ts=START_TS, end_ts=END_TS,
        stroke_type=stroke_type, **kw
    )
    return result, captured, montage_events


def test_manual_range_window_and_auto_impact(monkeypatch, tmp_path):
    submitted = []

    def fake_submit(path, stroke_type=None):
        submitted.append(stroke_type)
        return {  # 模型即便返回 forehand，手动模式也应保留用户标注的 backhand
            "stroke_type": "forehand",
            "level": "3.5", "level_note": "转体充分",
            "strengths": ["平衡好"], "weaknesses": [], "advice": "建议",
        }

    result, cap, events = _run_manual(
        "m1", fake_submit, monkeypatch, tmp_path)

    # 抽帧窗口 = 用户范围两端各加 margin（供跟踪与边缘裁剪），与动作类型无关
    t0 = cap["center"] - cap["before"]
    t1 = cap["center"] + cap["after"]
    assert abs(t0 - (START_TS - MARGIN)) < 1e-6
    assert abs(t1 - (END_TS + MARGIN)) < 1e-6

    assert result.status == "done"
    assert len(result.actions) == 1
    rec = result.actions[0]
    assert rec.stroke_type == "backhand" and submitted == ["backhand"]
    # 击球帧由后端在用户范围内部自动识别，落在合成挥拍的真实击球时刻附近
    assert START_TS < rec.peak_ts < END_TS
    assert abs(rec.peak_ts - CONTACT) < 1.0 / FPS
    # 正反手六帧：准备/引拍后摆/蓄力/击球/随挥前送/随挥结束
    assert len(event_frame_specs(events[0])) == 6


def test_manual_serve_produces_six_frame_montage(monkeypatch, tmp_path):
    def fake_submit(path, stroke_type=None):
        return {"stroke_type": "serve", "level": "4.0", "level_note": "",
                "strengths": [], "weaknesses": [], "advice": ""}

    _result, _cap, events = _run_manual(
        "m2", fake_submit, monkeypatch, tmp_path, stroke_type="serve")
    # 发球六帧：准备/抛球/trophy/拍头下坠/击球/随挥
    assert len(event_frame_specs(events[0])) == 6


def test_manual_click_ts_outside_range_widens_window(monkeypatch, tmp_path):
    # 点选球员的时刻落在动作范围之外：窗口须一并纳入该帧（±0.3s）以锁定跟踪
    click = END_TS + 1.0

    def fake_submit(path, stroke_type=None):
        return {"stroke_type": "backhand", "level": "3.0", "level_note": "",
                "strengths": [], "weaknesses": [], "advice": ""}

    _result, cap, _ev = _run_manual(
        "m4", fake_submit, monkeypatch, tmp_path, click_ts=click)
    t1 = cap["center"] + cap["after"]
    assert t1 >= click + 0.3 - 1e-9


def test_uploaded_video_deleted_after_analysis(monkeypatch, tmp_path):
    """delete_video=True（本地上传）：拼贴图生成后删除 job 目录里的视频拷贝。"""
    def fake_submit(path, stroke_type=None):
        return {"stroke_type": "backhand", "level": "3.0", "level_note": "",
                "strengths": [], "weaknesses": [], "advice": ""}

    result, _cap, _ev = _run_manual(
        "m5", fake_submit, monkeypatch, tmp_path, delete_video=True)
    assert result.status == "done"
    assert not (tmp_path / "m5" / "video.mp4").exists()


def test_source_video_kept_without_delete_flag(monkeypatch, tmp_path):
    """B站来源（delete_video 缺省 False）：视频文件保留。"""
    def fake_submit(path, stroke_type=None):
        return {"stroke_type": "backhand", "level": "3.0", "level_note": "",
                "strengths": [], "weaknesses": [], "advice": ""}

    result, _cap, _ev = _run_manual(
        "m6", fake_submit, monkeypatch, tmp_path)
    assert result.status == "done"
    assert (tmp_path / "m6" / "video.mp4").exists()


def test_manual_preview_skips_llm(monkeypatch, tmp_path):
    def fake_submit(*a, **k):
        raise AssertionError("预览模式不应调用 LLM")

    result, _cap, _ev = _run_manual(
        "m3", fake_submit, monkeypatch, tmp_path, skip_llm=True)
    assert result.status == "done"
    assert len(result.actions) == 1
    rec = result.actions[0]
    assert rec.status == "pending"
    assert rec.stroke_type == "backhand"


def test_manual_rejects_inverted_range(monkeypatch, tmp_path):
    monkeypatch.setattr("app.config.settings.jobs_dir", tmp_path)
    storage.create_job("m5", "v.mp4")
    result = pipeline.run_pipeline(
        "m5", start_ts=10.0, end_ts=9.0, stroke_type="forehand")
    assert result.status == "error"
    assert "结束时间需晚于开始时间" in result.message
