"""SSE 进度流行为：事件格式、终结断流、以及 continue-on-timeout（裁定）。"""
import json
import threading
import time

from app.routes import progress


def _wait_subscribed(jm, job_id, timeout=2.0):
    """生成器在首个 next() 才订阅：等它真正挂上队列。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        with jm._lock:
            if jm._subs.get(job_id):
                return True
        time.sleep(0.01)
    return False


def _stream_events(job_id, publish):
    """在子线程里跑 event_stream，订阅成功后执行 publish()，返回全部 chunk。"""
    out = []
    t = threading.Thread(target=lambda: out.extend(progress.event_stream(job_id)))
    t.start()
    try:
        assert _wait_subscribed(progress.job_manager, job_id), "not subscribed"
        publish()
    finally:
        t.join(timeout=10)
    return out


def test_stream_format_and_stops_on_done():
    jm = progress.job_manager
    job_id = "sse-done-test"

    def publish():
        jm._publish(job_id, {"progress": 5, "stage": "extracting", "message": "抽帧中"})
        jm._publish(job_id, {"progress": 100, "stage": "done", "message": "完成"})
        jm._publish(job_id, {"progress": 100, "stage": "done", "message": "不应到达"})

    chunks = _stream_events(job_id, publish)
    assert len(chunks) == 2, chunks
    for c in chunks:
        assert c.startswith("data: ") and c.endswith("\n\n")
    ev = json.loads(chunks[1][len("data: "):])
    assert ev["stage"] == "done" and ev["progress"] == 100


def test_stream_stops_on_error_and_login_required():
    jm = progress.job_manager
    for stage in ("error", "login_required"):
        job_id = f"sse-{stage}-test"

        def publish(job_id=job_id, stage=stage):
            jm._publish(job_id, {"progress": 50, "stage": "extracting", "message": "x"})
            jm._publish(job_id, {"progress": 50, "stage": stage, "message": "y"})
            jm._publish(job_id, {"progress": 50, "stage": "done", "message": "z"})

        chunks = _stream_events(job_id, publish)
        assert len(chunks) == 2, (stage, chunks)
        assert json.loads(chunks[-1][len("data: "):])["stage"] == stage


def test_stream_survives_poll_timeout(monkeypatch):
    """queue.Empty 不能断流：终结事件晚到若干个超时周期也必须能收到。"""
    monkeypatch.setattr(progress, "SSE_POLL_TIMEOUT", 0.05)
    jm = progress.job_manager
    job_id = "sse-timeout-test"

    def publish():
        time.sleep(0.25)  # 期间队列空转 ~5 次 0.05s 超时
        jm._publish(job_id, {"progress": 100, "stage": "done", "message": "完成"})

    chunks = _stream_events(job_id, publish)
    assert chunks, "stream died before the late event arrived"
    assert json.loads(chunks[-1][len("data: "):])["stage"] == "done"
