"""结果查询：GET /api/jobs/{job_id}/result 与拼贴图静态文件。

裁定（路由前缀）：拼贴图路径是 `/api/jobs/{job_id}/montages/{name:path}`
（montages 复数 + :path），与 storage.montage_path 的 "montages/action_N.jpg"
及前端 `${BASE}/api/jobs/${jobId}/${montage_path}` 对齐。
"""
from dataclasses import asdict

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from .. import storage
from ..jobs import job_manager

router = APIRouter()


@router.get("/api/jobs/{job_id}/result")
def result(job_id: str):
    r = job_manager.get(job_id)
    if r is None:
        raise HTTPException(status_code=404, detail="job not found")
    return asdict(r)


@router.get("/api/jobs/{job_id}/montages/{name:path}")
def montage(job_id: str, name: str):
    base = (storage.job_dir(job_id) / "montages").resolve()
    p = (base / name).resolve()
    if base not in p.parents or not p.is_file():  # 兼防路径穿越；缺失 404
        raise HTTPException(status_code=404, detail="montage not found")
    return FileResponse(p)
