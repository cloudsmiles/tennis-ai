"""POST /api/jobs：multipart 上传视频（可选球员点选 cx/cy）建分析任务。"""
import os
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, UploadFile

from ..jobs import job_manager

router = APIRouter()


@router.post("/api/jobs")
async def create_job(
    video: UploadFile = File(...),
    cx: Optional[float] = Form(None),
    cy: Optional[float] = Form(None),
):
    suffix = Path(video.filename or "").suffix or ".mp4"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await video.read())
        tmp_path = tmp.name
    try:
        target = (cx, cy) if cx is not None and cy is not None else None
        job_id = job_manager.create(tmp_path, video.filename, target)
    finally:
        try:
            os.unlink(tmp_path)  # create() 内已同步拷入 job 目录
        except OSError:
            pass
    return {"job_id": job_id}
