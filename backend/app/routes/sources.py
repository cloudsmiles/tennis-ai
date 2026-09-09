"""视频链接来源：POST /api/sources 下载 B站视频，GET .../video 供前端播放。"""
import uuid

from fastapi import APIRouter, Form, HTTPException
from fastapi.responses import FileResponse

from .. import storage
from ..fetch import download_video, is_allowed_url

router = APIRouter()


@router.post("/api/sources")
def create_source(url: str = Form(...)):
    """下载链接视频到 sources/<id>/，返回 source_id 与可播放的 video_url。

    用同步 def（而非 async）：yt-dlp 下载是阻塞网络调用，交给 FastAPI 线程池，
    避免阻塞事件循环。
    """
    url = (url or "").strip()
    if not is_allowed_url(url):
        raise HTTPException(status_code=422, detail="仅支持 bilibili.com / b23.tv 链接")
    source_id = uuid.uuid4().hex[:12]
    dest = storage.source_dir(source_id)
    try:
        download_video(url, dest)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"视频下载失败：{e}")
    return {
        "source_id": source_id,
        "video_url": f"/api/sources/{source_id}/video",
    }


@router.get("/api/sources/{source_id}/video")
def source_video(source_id: str):
    path = storage.source_video_path(source_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="视频不存在或已失效")
    # FileResponse 支持 Range 请求，前端 <video> 可拖动进度
    return FileResponse(str(path), media_type="video/mp4")
