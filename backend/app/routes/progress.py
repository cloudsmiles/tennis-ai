"""GET /api/jobs/{job_id}/events：SSE 进度流。

裁定（修正原计划 bug）：轮询队列超时（queue.Empty）时 **continue** 保持连接，
只在收到终结事件（stage 为 done / error / login_required）时断流，客户端
断开由框架触发 GeneratorExit → finally 退订。

终态兜底（final review）：任务可能在客户端订阅前就已终结（如抽帧秒败），
或 EventSource 断线重连时终结事件已被错过——只靠队列转发会让 UI 永远干等。
订阅时与每次轮询超时后都核对一次落盘结果（job_manager.get），已终结则补发
一条合成终结事件并断流；未终结则照旧继续等待。
"""
import json
import queue

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from ..jobs import job_manager

router = APIRouter()

SSE_POLL_TIMEOUT = 15.0  # 秒；测试里可调小验证 continue-on-timeout
TERMINAL_STAGES = ("done", "error", "login_required")
TERMINAL_STATUSES = ("done", "error")


def _catch_up_event(job_id: str):
    """已落盘的终态结果 → 合成终结事件；未终结/无结果 → None。"""
    r = job_manager.get(job_id)
    if r is None:
        return None
    if r.status not in TERMINAL_STATUSES and r.stage not in TERMINAL_STAGES:
        return None
    stage = r.stage or ("done" if r.status == "done" else "error")
    progress = r.progress or (100.0 if stage == "done" else 0.0)
    return {"progress": progress, "stage": stage, "message": r.message}


def event_stream(job_id: str):
    """同步生成器：产出 "data: {json}\\n\\n" 格式的 SSE 事件。"""
    q = job_manager.subscribe(job_id)
    try:
        while True:
            # 订阅时 / 每次超时后核对落盘结果：晚订阅或重连错过终结事件
            # 的客户端在这里被补发一条合成终结事件后正常断流
            catch_up = _catch_up_event(job_id)
            if catch_up is not None:
                yield f"data: {json.dumps(catch_up, ensure_ascii=False)}\n\n"
                return
            try:
                ev = q.get(timeout=SSE_POLL_TIMEOUT)
            except queue.Empty:
                continue  # 超时不算结束：保持流打开继续等
            yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
            if ev.get("stage") in TERMINAL_STAGES:
                break
    finally:
        job_manager.unsubscribe(job_id, q)


@router.get("/api/jobs/{job_id}/events")
def events(job_id: str):
    return StreamingResponse(event_stream(job_id), media_type="text/event-stream")
