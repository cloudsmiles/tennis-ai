"""POST /api/jobs：multipart 上传视频（可选球员点选 cx/cy）建分析任务。"""
import os
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from ..jobs import job_manager

router = APIRouter()

VALID_STROKES = ("forehand", "backhand", "serve")


@router.post("/api/jobs")
async def create_job(
    video: UploadFile = File(...),
    cx: Optional[float] = Form(None),
    cy: Optional[float] = Form(None),
    skip_llm: bool = Form(False),
    hit_ts: Optional[float] = Form(None),
    stroke_type: Optional[str] = Form(None),
):
    if stroke_type is not None and stroke_type not in VALID_STROKES:
        raise HTTPException(status_code=422, detail="stroke_type 取值非法")
    filename = video.filename or "upload.mp4"
    suffix = Path(filename).suffix or ".mp4"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await video.read())
        tmp_path = tmp.name
    try:
        target = (cx, cy) if cx is not None and cy is not None else None
        job_id = job_manager.create(
            tmp_path, filename, target, skip_llm=skip_llm,
            hit_ts=hit_ts, stroke_type=stroke_type,
        )
    finally:
        try:
            os.unlink(tmp_path)  # create() 内已同步拷入 job 目录
        except OSError:
            pass
    return {"job_id": job_id}
