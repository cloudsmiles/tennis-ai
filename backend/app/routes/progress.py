"""GET /api/jobs/{job_id}/events：SSE 进度流。

裁定（修正原计划 bug）：轮询队列超时（queue.Empty）时 **continue** 保持连接，
只在收到终结事件（stage 为 done / error / login_required）时断流，客户端
断开由框架触发 GeneratorExit → finally 退订。
"""
import json
import queue

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from ..jobs import job_manager

router = APIRouter()

SSE_POLL_TIMEOUT = 15.0  # 秒；测试里可调小验证 continue-on-timeout
TERMINAL_STAGES = ("done", "error", "login_required")


def event_stream(job_id: str):
    """同步生成器：产出 "data: {json}\\n\\n" 格式的 SSE 事件。"""
    q = job_manager.subscribe(job_id)
    try:
        while True:
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
