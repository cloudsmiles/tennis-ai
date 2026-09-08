"""SSE 进度流行为：事件格式、终结断流、continue-on-timeout（裁定），
以及终态兜底——晚订阅 / 断线重连也能拿到终结事件（final review fix 2）。"""
import json
import queue
import threading
import time

from app import storage
from app.routes import progress
from app.schemas import JobResult


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


# ---- 终态兜底：晚订阅 / 断线重连错过终结事件也能拿到终结事件 --------

class _StubJobManager:
    """离线替身：subscribe 给永远空的队列；get 按序返回预设结果（耗尽后重复最后一个）。"""

    def __init__(self, results):
        self._results = results
        self.get_calls = 0
        self.unsubscribed = []

    def subscribe(self, job_id):
        return queue.Queue()

    def get(self, job_id):
        r = self._results[min(self.get_calls, len(self._results) - 1)]
        self.get_calls += 1
        return r

    def unsubscribe(self, job_id, q):
        self.unsubscribed.append(job_id)


def test_late_subscriber_gets_synthesized_done_event(monkeypatch):
    """订阅前任务已终结：不等队列，订阅即补发合成 done 事件并断流。"""
    stub = _StubJobManager(
        [
            JobResult(
                job_id="j", video_path="v", status="done",
                progress=100.0, stage="done", message="完成",
            )
        ]
    )
    monkeypatch.setattr(progress, "job_manager", stub)

    chunks = list(progress.event_stream("j"))

    assert len(chunks) == 1
    ev = json.loads(chunks[0][len("data: "):])
    assert ev == {"progress": 100.0, "stage": "done", "message": "完成"}
    assert stub.get_calls == 1  # 订阅首轮核对即命中，从未阻塞在队列上
    assert stub.unsubscribed == ["j"]  # finally 退订


def test_error_result_synthesizes_error_event(monkeypatch):
    """error 终态（stage 为空时回退为 "error"）同样补发并断流。"""
    stub = _StubJobManager(
        [
            JobResult(
                job_id="j", video_path="v", status="error",
                progress=15.0, stage="", message="无法读取视频文件",
            )
        ]
    )
    monkeypatch.setattr(progress, "job_manager", stub)

    chunks = list(progress.event_stream("j"))

    assert len(chunks) == 1
    ev = json.loads(chunks[0][len("data: "):])
    assert ev["stage"] == "error" and ev["progress"] == 15.0
    assert ev["message"] == "无法读取视频文件"


def test_login_required_result_synthesizes_event(monkeypatch):
    """login_required 终态（status=error + stage=login_required）原样补发。"""
    stub = _StubJobManager(
        [
            JobResult(
                job_id="j", video_path="v", status="error",
                progress=70.0, stage="login_required", message="通义千问未登录",
            )
        ]
    )
    monkeypatch.setattr(progress, "job_manager", stub)

    chunks = list(progress.event_stream("j"))

    assert len(chunks) == 1
    ev = json.loads(chunks[0][len("data: "):])
    assert ev["stage"] == "login_required" and ev["message"] == "通义千问未登录"


def test_running_result_keeps_waiting_then_catches_up(monkeypatch):
    """无结果 / running 时保持等待（熬过队列超时），终态落盘后补发断流。"""
    monkeypatch.setattr(progress, "SSE_POLL_TIMEOUT", 0.05)
    stub = _StubJobManager(
        [
            None,  # 第一次核对：还没有任何落盘结果
            JobResult(
                job_id="j", video_path="v", status="running",
                progress=50.0, stage="analyzing", message="分析中",
            ),
            JobResult(
                job_id="j", video_path="v", status="done",
                progress=100.0, stage="done", message="完成",
            ),
        ]
    )
    monkeypatch.setattr(progress, "job_manager", stub)

    chunks = list(progress.event_stream("j"))

    # 前两次核对（None / running）都只是继续等：至少熬过两次队列超时
    assert stub.get_calls >= 3
    assert len(chunks) == 1
    assert json.loads(chunks[0][len("data: "):])["stage"] == "done"


def test_catch_up_reads_real_saved_result(tmp_path, monkeypatch):
    """真实 job_manager：终态落盘后晚订阅也能立即拿到合成终结事件。"""
    monkeypatch.setattr("app.config.settings.jobs_dir", tmp_path)
    job_id = "sse-disk-done"
    storage.create_job(job_id, "v.mp4")
    storage.save_result(
        JobResult(
            job_id=job_id, video_path="v.mp4", status="done",
            progress=100.0, stage="done", message="完成",
        )
    )

    chunks = list(progress.event_stream(job_id))

    assert len(chunks) == 1
    assert json.loads(chunks[0][len("data: "):])["stage"] == "done"
