"""从视频链接下载源视频（目前支持 B站）。

用 yt-dlp 下载视频流 mp4。动作分析只需要画面、不需要声音，因此选纯视频流
（bestvideo[ext=mp4]），免去 ffmpeg 合并音视频；免登录即可取到可用的最高清晰度。
yt_dlp 仅在本模块内延迟导入（与 ultralytics 同理），未安装时不影响其余功能。
"""
from pathlib import Path
from urllib.parse import urlparse

ALLOWED_HOST_SUFFIXES = ("bilibili.com", "b23.tv", "bilibili.tv")


def is_allowed_url(url: str) -> bool:
    """仅允许 B站域名（含 b23.tv 短链），避免任意 URL 带来的 SSRF 风险。"""
    try:
        host = (urlparse(url).hostname or "").lower()
    except (ValueError, AttributeError):
        return False
    return any(host == d or host.endswith("." + d) for d in ALLOWED_HOST_SUFFIXES)


def download_video(url: str, dest_dir: Path) -> Path:
    """下载 url 到 dest_dir，返回落盘的视频文件（dest_dir/video.<ext>）。

    失败时抛异常，调用方负责转成中文用户提示。
    """
    import yt_dlp

    dest_dir.mkdir(parents=True, exist_ok=True)
    # 清掉占位/上次的下载产物，避免 glob 取到空文件
    for p in list(dest_dir.glob("video.*")) + list(dest_dir.glob("dl.*")):
        p.unlink(missing_ok=True)

    opts = {
        # 纯视频 mp4 优先；取不到则退而求其次（仍不需要音频/ffmpeg）
        "format": "bestvideo[ext=mp4]/best[ext=mp4]/best",
        "outtmpl": str(dest_dir / "dl.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])

    dl_files = sorted(dest_dir.glob("dl.*"))
    if not dl_files:
        raise RuntimeError("下载未产生视频文件")
    dl = dl_files[0]
    target = dest_dir / f"video{dl.suffix or '.mp4'}"
    dl.replace(target)
    return target
