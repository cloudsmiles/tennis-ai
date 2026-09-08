"""POST /api/jobs：上传视频或引用已下载的 source，建分析任务。"""
import os
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from .. import storage
from ..jobs import job_manager

router = APIRouter()

VALID_STROKES = ("forehand", "backhand", "serve")


@router.post("/api/jobs")
async def create_job(
    video: Optional[UploadFile] = File(None),
    source_id: Optional[str] = Form(None),
    cx: Optional[float] = Form(None),
    cy: Optional[float] = Form(None),
    skip_llm: bool = Form(False),
    start_ts: Optional[float] = Form(None),
    stroke_type: Optional[str] = Form(None),
    click_ts: Optional[float] = Form(None),
):
    if stroke_type is not None and stroke_type not in VALID_STROKES:
        raise HTTPException(status_code=422, detail="stroke_type 取值非法")

    target = (cx, cy) if cx is not None and cy is not None else None
    kwargs = dict(target_player=target, skip_llm=skip_llm,
                  start_ts=start_ts, stroke_type=stroke_type, click_ts=click_ts)

    if source_id:
        # 来自 B站链接：视频已在 /api/sources 下载好，直接引用其本地文件
        src = storage.source_video_path(source_id)
        if not src.exists():
            raise HTTPException(status_code=404, detail="来源视频不存在或已失效")
        job_id = job_manager.create(str(src), src.name, **kwargs)
        return {"job_id": job_id}

    if video is None:
        raise HTTPException(status_code=422, detail="请上传视频或提供视频来源")

    filename = video.filename or "upload.mp4"
    suffix = Path(filename).suffix or ".mp4"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await video.read())
        tmp_path = tmp.name
    try:
        job_id = job_manager.create(tmp_path, filename, **kwargs)
    finally:
        try:
            os.unlink(tmp_path)  # create() 内已同步拷入 job 目录
        except OSError:
            pass
    return {"job_id": job_id}
