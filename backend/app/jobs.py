"""JobManager：后台线程跑 pipeline、落盘进度、向 SSE 订阅者发布事件。"""
import queue
import shutil
import threading
import uuid

from . import storage
from .pipeline import run_pipeline
from .schemas import JobResult

# 终态：SSE 事件流的断流条件（progress 路由同款集合）
_TERMINAL_STAGES = ("done", "error", "login_required")


class JobManager:
    def __init__(self):
        self._subs = {}  # job_id -> list[queue.Queue]
        self._lock = threading.Lock()

    def create(self, video_src_path, filename, target_player=None, skip_llm=False,
               start_ts=None, stroke_type=None) -> str:
        """复制上传的临时文件到 job 目录并启动后台管线线程，返回 job_id。"""
        job_id = uuid.uuid4().hex[:12]
        storage.create_job(job_id, filename)
        shutil.copy(video_src_path, storage.video_path(job_id))
        threading.Thread(
            target=self._run,
            args=(job_id, target_player, skip_llm, start_ts, stroke_type),
            daemon=True, name=f"job-{job_id}",
        ).start()
        return job_id

    def _run(self, job_id, target_player, skip_llm=False, start_ts=None,
             stroke_type=None):
        def on_progress(pct, stage, msg):
            r = storage.load_result(job_id)
            if r is None:
                r = JobResult(job_id=job_id, video_path="")
            r.progress, r.stage, r.message = pct, stage, msg
            # 管线完成前的最后一次回调（100,"done"）发生在终态落盘之后：
            # 已是终态时不回退成 running
            if r.status not in ("done", "error"):
                r.status = "running"
            storage.save_result(r)
            self._publish(
                job_id, {"progress": pct, "stage": stage, "message": msg}
            )

        try:
            result = run_pipeline(
                job_id, target_player, on_progress, skip_llm=skip_llm,
                start_ts=start_ts, stroke_type=stroke_type,
            )
        except Exception as e:
            r = storage.load_result(job_id)
            if r is None:
                r = JobResult(job_id=job_id, video_path="")
            r.status = "error"
            r.message = str(e)
            storage.save_result(r)
            self._publish(job_id, {"stage": "error", "message": str(e)})
            return

        # 管线的错误/未登录路径以返回值（而非异常/回调）结束：
        # 这里补发一个终结事件，让 SSE 订阅者断流
        if result is not None and result.status == "error":
            self._publish(
                job_id,
                {
                    "progress": result.progress,
                    "stage": result.stage or "error",
                    "message": result.message,
                },
            )

    def get(self, job_id):
        return storage.load_result(job_id)

    def subscribe(self, job_id) -> queue.Queue:
        q = queue.Queue()
        with self._lock:
            self._subs.setdefault(job_id, []).append(q)
        return q

    def unsubscribe(self, job_id, q):
        with self._lock:
            if job_id in self._subs and q in self._subs[job_id]:
                self._subs[job_id].remove(q)

    def _publish(self, job_id, event: dict):
        with self._lock:
            for q in self._subs.get(job_id, []):
                q.put(event)


job_manager = JobManager()  # 模块单例
