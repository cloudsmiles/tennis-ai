"""管线级：LLMParseError → 单动作 parse_failed + 保留模型原文（fix 1）。

全程离线：抽帧 / 检测 / 拼贴 / LLM 队列全部注入替身——不加载 YOLO 模型、
不启动浏览器、不开任何窗口。假数据构造出两次相隔 >6s 的挥拍速度尖峰，
让真实的 geometry/keyframes/select/quality 代码选出 2 个动作，从而走到
真实的 LLM 分析循环。

裁定（LLMSerialQueue 语义）：解析失败沿用既有重试节奏（新对话可能给出
合法 JSON），重试耗尽后 LLMParseError 原样上行——本文件的 fake submit
直接模拟"耗尽后"的最终异常，等价于真实队列的对外行为。
"""
import types

from app import pipeline, storage
from app.llm.tongyi import LLMParseError, NotLoggedInError
from app.schemas import FrameDet

FPS = 15.0
N_FRAMES = 200
W, H = 640, 480


def _wrist_x(i: int) -> float:
    """背景每帧 ~1px 抖动；帧 20/21 与 150/151 两次大幅快挥，产生两个峰。"""
    x = 100 + (i % 2)
    if i in (20, 150):
        x = 400.0
    elif i in (21, 151):
        x = 100.0
    return x


def _fake_dets():
    return [
        FrameDet(
            frame_idx=i,
            ts=i / FPS,
            player_box=(10, 10, 110, 310),
            player_conf=0.9,
            wrist=(_wrist_x(i), 200.0),
            pose_ok=True,
        )
        for i in range(N_FRAMES)
    ]


def _run_pipeline(job_id, submit, monkeypatch, tmp_path):
    """注入替身后跑真实 run_pipeline；storage 落盘进 tmp_path。"""
    monkeypatch.setattr("app.config.settings.jobs_dir", tmp_path)
    storage.create_job(job_id, "v.mp4")
    monkeypatch.setattr(
        pipeline,
        "extract_frames",
        lambda video, fps: (
            [None] * N_FRAMES,
            [i / FPS for i in range(N_FRAMES)],
            W,
            H,
        ),
    )
    monkeypatch.setattr(
        pipeline,
        "Detector",
        lambda: types.SimpleNamespace(
            detect_frames=lambda frames, ts, tp: _fake_dets()
        ),
    )
    monkeypatch.setattr(pipeline, "make_montage", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "llm_queue", types.SimpleNamespace(submit=submit))
    return pipeline.run_pipeline(job_id)


def test_parse_failed_action_keeps_raw_reply_and_job_continues(monkeypatch, tmp_path):
    submitted = []

    def fake_submit(path):
        submitted.append(path)
        if len(submitted) == 1:
            raise LLMParseError("原始回复")  # 第 1 个动作解析失败
        return {  # 第 2 个动作照常拿到结构化结果
            "stroke_type": "forehand",
            "scores": {"准备": 8},
            "overall": 7.5,
            "issues": ["击球点偏晚"],
            "advice": "提前引拍",
        }

    result = _run_pipeline("pf1", fake_submit, monkeypatch, tmp_path)

    assert result.status == "done"  # 单动作解析失败不终结整个任务
    assert len(result.actions) == 2
    a0, a1 = result.actions
    assert a0.status == "parse_failed" and a0.raw_reply == "原始回复"
    assert a1.status == "ok" and a1.stroke_type == "forehand"
    assert a1.overall == 7.5 and a1.issues == ["击球点偏晚"]
    assert len(submitted) == 2  # 第二个动作仍然被提交分析

    saved = storage.load_result("pf1")  # 落盘结果同样保留原文（前端展示用）
    assert saved.actions[0].status == "parse_failed"
    assert saved.actions[0].raw_reply == "原始回复"


def test_not_logged_in_still_fails_whole_job(monkeypatch, tmp_path):
    """登录缺失仍是任务级失败（保持原行为，防止 except 顺序回归）。"""

    def fake_submit(path):
        raise NotLoggedInError("tongyi not logged in")

    result = _run_pipeline("pf2", fake_submit, monkeypatch, tmp_path)
    assert result.status == "error" and result.stage == "login_required"
    assert result.actions[0].status == "failed"


def test_llm_parse_error_carries_raw():
    err = LLMParseError("模型说的原话")
    assert isinstance(err, RuntimeError)
    assert err.raw == "模型说的原话"
