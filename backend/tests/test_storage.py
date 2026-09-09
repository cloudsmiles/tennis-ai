from pathlib import Path
from app.storage import create_job, montage_path, save_result, load_result
from app.schemas import JobResult, ActionRecord

def test_job_dirs_created(tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.settings.jobs_dir", tmp_path)
    d = create_job("abc", "x.mp4")
    assert d.exists() and (d / "montages").exists()

def test_save_and_load_result(tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.settings.jobs_dir", tmp_path)
    create_job("j1", "v.mp4")
    r = JobResult(job_id="j1", video_path="v.mp4", status="done",
                  actions=[ActionRecord(action_id=0, peak_ts=1.5, montage_path="montages/a0.jpg")])
    save_result(r)
    loaded = load_result("j1")
    assert loaded.status == "done" and loaded.actions[0].peak_ts == 1.5
