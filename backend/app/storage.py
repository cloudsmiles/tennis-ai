import shutil
from pathlib import Path
from .config import settings
from .schemas import JobResult

def job_dir(job_id: str) -> Path:
    return settings.jobs_dir / job_id

def create_job(job_id: str, video_filename: str) -> Path:
    d = job_dir(job_id)
    (d / "montages").mkdir(parents=True, exist_ok=True)
    (d / "frames").mkdir(parents=True, exist_ok=True)
    ext = Path(video_filename).suffix or ".mp4"
    (d / f"video{ext}").touch()
    return d

def video_path(job_id: str) -> Path:
    d = job_dir(job_id)
    vids = list(d.glob("video.*"))
    return vids[0] if vids else d / "video.mp4"

def montage_path(job_id: str, action_id: int) -> Path:
    return job_dir(job_id) / "montages" / f"action_{action_id}.jpg"

def save_result(result: JobResult) -> None:
    result.to_json(job_dir(result.job_id) / "result.json")

def load_result(job_id: str):
    p = job_dir(job_id) / "result.json"
    return JobResult.from_json(p) if p.exists() else None
