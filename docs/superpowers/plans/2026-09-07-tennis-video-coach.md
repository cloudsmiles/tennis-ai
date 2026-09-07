# 网球视频动作分析工具 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 本地上传网球视频，自动挑出 2~3 个最清晰的击球动作，生成"准备/击球/随挥"三帧拼贴图，通过 Playwright 模拟人工上传到通义千问网页，取回动作类型+评分+点评，在 React 前端展示。

**Architecture:** FastAPI 后端跑一条异步管线：OpenCV 抽帧 → YOLO11 检测跟踪球员/球拍+姿态 → 球拍/手腕速度峰值定位击球 → 质量打分择优 2~3 个动作 → 生成拼贴图 → 串行队列驱动 Playwright 持久浏览器会话上传通义千问 → 宽松解析 JSON → 落盘 result.json。React 前端经 SSE 看进度并展示动作卡片。无数据库，文件落盘。

**Tech Stack:** Python 3.10+ / FastAPI / Uvicorn / Ultralytics(YOLO11, YOLO11-pose) / OpenCV / NumPy / Playwright；React + Vite + TypeScript；macOS（CoreML/MPS）。

**Spec:** `docs/superpowers/specs/2026-09-07-tennis-video-coach-design.md`

## Global Constraints

- Python 3.10+；后端代码在 `backend/`，前端在 `frontend/`。
- 不训练任何模型；动作类型（正手/反手/发球）由通义千问判定，本地只给"疑似发球"提示。
- 不做球场透视/homography；只依赖 person + tennis racket + 17 点姿态。
- 不调用收费大模型 API；只用 Playwright 操作通义千问网页。
- 目标择优动作数默认 3（可配置，范围 2~3）。
- 抽帧默认 15 fps（可配置）。
- 回合间隔阈值默认 6.0 秒（可配置）。
- 文件落盘在 `jobs/<job_id>/`，无数据库；结果写 `result.json`，重启可恢复。
- LLM 请求严格串行，请求间加随机延时；单张失败重试 1~2 次，失败标记不影响其他动作。
- YOLO/Playwright 依赖真实模型与登录态，不进自动化 CI；纯逻辑函数必须有单元测试。
- 每个任务结束提交一次 git commit。

---

## File Structure

```
backend/
  requirements.txt
  app/
    __init__.py
    main.py                  # FastAPI 应用、挂载路由与静态目录、启动 LLM 队列
    config.py                # 全部可调参数（fps、阈值、路径、选择器）集中此处
    schemas.py               # dataclass：FrameDet / SwingEvent / ActionRecord / JobResult
    storage.py               # job 目录创建、result.json 读写、montage 路径
    jobs.py                  # JobManager：异步任务、进度状态、SSE 队列
    pipeline.py              # 编排 CV → 拼贴图 → LLM 的完整管线
    routes/
      __init__.py
      upload.py              # POST /api/jobs 上传视频建任务；GET /api/jobs
      progress.py            # GET /api/jobs/{id}/events (SSE)
      results.py             # GET /api/jobs/{id}/result；montage 静态文件
      session.py             # GET /api/llm/login-status；POST /api/llm/login
    cv/
      __init__.py
      frames.py              # 抽帧：video → List[np.ndarray] + 时间戳
      detect.py              # YOLO 包装：检测+跟踪 person/racket + pose（集成层，手动验证）
      geometry.py            # 纯函数：框中心、距画面边缘距离、框面积、点距离、速度序列、平滑、峰值
      keyframes.py           # 纯函数：由峰值选 prep/peak/follow 三帧索引 + 裁剪框
      montage.py             # 三帧裁剪 → 横向拼贴图（带中文标注）
      quality.py             # 纯函数：单个挥拍事件质量打分
      select.py              # 纯函数：峰值去重、按回合聚类、择优 2~3 个
    llm/
      __init__.py
      prompts.py             # 固定提示词文本
      selectors.py           # 通义千问页面选择器（集中配置）
      parse.py               # 纯函数：从回复文本抽取结构化 JSON
      browser.py             # Playwright 持久上下文、登录态、串行队列
      tongyi.py              # 新开对话→上传图→发提示词→抓回复（集成层，手动验证）
  tests/
    __init__.py
    conftest.py              # 合成检测数据 fixture
    test_geometry.py
    test_keyframes.py
    test_quality.py
    test_select.py
    test_parse.py
    test_storage.py
frontend/
  (Vite React TS 脚手架，任务 16 创建)
  src/
    api.ts                   # 后端调用 + SSE 封装
    App.tsx
    components/
      Uploader.tsx
      PlayerPicker.tsx
      Progress.tsx
      Results.tsx
    types.ts
```

**职责边界**：`cv/geometry.py`、`keyframes.py`、`quality.py`、`select.py`、`llm/parse.py`、`storage.py` 为纯逻辑，不碰 YOLO/浏览器/网络，全部 TDD；`cv/detect.py`、`llm/tongyi.py`、`llm/browser.py` 为集成层，手动验证。

---

## Task 1: 后端脚手架 + 配置 + 数据模型

**Files:**
- Create: `backend/requirements.txt`
- Create: `backend/app/__init__.py`
- Create: `backend/app/config.py`
- Create: `backend/app/schemas.py`
- Create: `backend/app/main.py`

**Interfaces:**
- Produces: `config.Settings`（单例 `settings`）；`schemas` 下 `FrameDet`、`SwingEvent`、`ActionRecord`、`JobResult`、`JobStatus`，后续所有任务使用这些类型。

- [ ] **Step 1: 写 requirements.txt**

```
fastapi==0.115.*
uvicorn[standard]==0.30.*
python-multipart==0.0.*
numpy==1.26.*
opencv-python-headless==4.10.*
ultralytics==8.3.*
playwright==1.47.*
pydantic==2.9.*
pytest==8.3.*
```

- [ ] **Step 2: 创建 venv 并安装**

Run: `cd backend && python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt && playwright install chromium`
Expected: 安装成功（ultralytics 首次会拉取 torch，较慢）。

- [ ] **Step 3: 写 config.py**

```python
from pathlib import Path
from pydantic import BaseModel

BASE_DIR = Path(__file__).resolve().parent.parent
JOBS_DIR = BASE_DIR / "jobs"

class Settings(BaseModel):
    jobs_dir: Path = JOBS_DIR
    extract_fps: float = 15.0
    target_actions: int = 3          # 择优动作数（2~3）
    rally_gap_seconds: float = 6.0   # 回合间隔阈值
    speed_smooth_window: int = 5     # 速度滑动平均窗口（帧）
    peak_prominence_ratio: float = 1.8  # 峰值需 >= 基线 * 该倍数
    follow_offset_frames: int = 6    # 随挥帧在峰值后多少帧
    prep_min_gap_frames: int = 3     # 引拍帧至少在峰值前多少帧
    crop_margin_ratio: float = 0.15  # 裁剪边距（相对人物框尺寸）
    llm_min_delay_s: float = 2.0
    llm_max_delay_s: float = 5.0
    llm_max_retries: int = 2
    data_dir: Path = BASE_DIR / ".pw-data"  # Playwright 持久用户目录

settings = Settings()
JOBS_DIR.mkdir(parents=True, exist_ok=True)
```

- [ ] **Step 4: 写 schemas.py**

```python
from dataclasses import dataclass, field, asdict
from typing import Optional
import json

Box = tuple  # (x1, y1, x2, y2) 像素坐标

@dataclass
class FrameDet:
    frame_idx: int
    ts: float
    player_box: Optional[Box] = None
    player_conf: float = 0.0
    racket_box: Optional[Box] = None
    racket_conf: float = 0.0
    wrist: Optional[tuple] = None      # (x, y) 持拍侧手腕
    pose_ok: bool = False              # 17 关键点是否足够完整

@dataclass
class SwingEvent:
    peak_idx: int
    peak_ts: float
    prep_idx: int
    follow_idx: int
    max_speed: float
    quality: float = 0.0
    suspected_serve: bool = False

@dataclass
class ActionRecord:
    action_id: int
    peak_ts: float
    montage_path: str                 # 相对 job 目录的拼贴图路径
    suspected_serve: bool = False
    status: str = "pending"           # pending|ok|parse_failed|failed
    stroke_type: Optional[str] = None
    scores: dict = field(default_factory=dict)
    overall: Optional[float] = None
    issues: list = field(default_factory=list)
    advice: str = ""
    raw_reply: str = ""

@dataclass
class JobResult:
    job_id: str
    video_path: str
    status: str = "queued"            # queued|running|done|error
    progress: float = 0.0
    stage: str = ""
    message: str = ""
    actions: list = field(default_factory=list)  # List[ActionRecord]

    def to_json(self, path) -> None:
        d = asdict(self)
        path.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def from_json(path) -> "JobResult":
        d = json.loads(path.read_text(encoding="utf-8"))
        acts = [ActionRecord(**a) for a in d.pop("actions", [])]
        r = JobResult(**d)
        r.actions = acts
        return r
```

- [ ] **Step 5: 写最小 main.py**

```python
from fastapi import FastAPI

def create_app() -> FastAPI:
    app = FastAPI(title="tennis-ai")
    @app.get("/api/health")
    def health():
        return {"ok": True}
    return app

app = create_app()
```

- [ ] **Step 6: 冒烟运行**

Run: `cd backend && source .venv/bin/activate && uvicorn app.main:app --port 8000 &` 然后 `curl -s localhost:8000/api/health`
Expected: `{"ok":true}`

- [ ] **Step 7: Commit**

```bash
git add backend/requirements.txt backend/app
git commit -m "feat: backend scaffold with config and schemas"
```

---

## Task 2: 存储层 storage.py

**Files:**
- Create: `backend/app/storage.py`
- Test: `backend/tests/test_storage.py`

**Interfaces:**
- Consumes: `config.settings.jobs_dir`；`schemas.JobResult`。
- Produces: `create_job(job_id, video_filename) -> Path`（返回 job 目录）、`job_dir(job_id) -> Path`、`montage_path(job_id, action_id) -> Path`、`save_result(result: JobResult)`、`load_result(job_id) -> JobResult | None`。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_storage.py
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && source .venv/bin/activate && pytest tests/test_storage.py -v`
Expected: FAIL（ModuleNotFoundError: app.storage）

- [ ] **Step 3: 实现 storage.py**

```python
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
```
注：上传任务里真正保存视频用 `shutil.copy`/写入，`create_job` 的 `touch()` 仅占位；Task 14 上传路由会把文件写到 `video_path(job_id)`。

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_storage.py -v`
Expected: PASS（2 passed）

- [ ] **Step 5: Commit**

```bash
git add backend/app/storage.py backend/tests/test_storage.py
git commit -m "feat: job storage layer"
```

---

## Task 3: CV 几何纯函数 geometry.py

**Files:**
- Create: `backend/app/cv/__init__.py`（空）
- Create: `backend/app/cv/geometry.py`
- Test: `backend/tests/test_geometry.py`

**Interfaces:**
- Produces:
  - `box_center(box) -> (x,y)`
  - `box_area(box) -> float`
  - `dist_to_edge(box, w, h) -> float`（框到最近画面边缘的归一化距离，0=贴边）
  - `point_speed(points: list[(x,y)|None]) -> list[float]`（逐帧位移，缺失帧速度为 0，长度与输入相同，首帧 0）
  - `smooth(values: list[float], window: int) -> list[float]`（居中滑动平均，边界截断）
  - `find_peaks(speed: list[float], prominence_ratio: float, min_gap: int) -> list[int]`（返回局部峰值帧索引；峰值需 > 邻域基线 * prominence_ratio，且两峰间距 >= min_gap）

- [ ] **Step 1: 写失败测试**

```python
# tests/test_geometry.py
import math
from app.cv.geometry import box_center, box_area, dist_to_edge, point_speed, smooth, find_peaks

def test_box_helpers():
    assert box_center((0, 0, 10, 20)) == (5.0, 10.0)
    assert box_area((0, 0, 10, 20)) == 200.0

def test_dist_to_edge_center_is_high():
    assert dist_to_edge((40, 40, 60, 60), 100, 100) > dist_to_edge((0, 0, 20, 20), 100, 100)

def test_point_speed_basic():
    pts = [(0, 0), (3, 4), None, (3, 8)]
    sp = point_speed(pts)
    assert sp[0] == 0.0 and sp[1] == 5.0 and sp[2] == 0.0 and sp[3] == 0.0

def test_smooth_reduces_spike():
    v = [0, 0, 10, 0, 0]
    s = smooth(v, 3)
    assert max(s) < 10

def test_find_peaks_detects_two():
    # 基线 1，两个明显尖峰在 idx 10 和 30
    v = [1.0] * 45
    v[10], v[30] = 10.0, 10.0
    peaks = find_peaks(v, prominence_ratio=3.0, min_gap=5)
    assert 10 in peaks and 30 in peaks

def test_find_peaks_ignores_flat():
    v = [1.0] * 40
    assert find_peaks(v, prominence_ratio=3.0, min_gap=5) == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_geometry.py -v`
Expected: FAIL（ModuleNotFoundError）

- [ ] **Step 3: 实现 geometry.py**

```python
from typing import Optional

def box_center(box):
    x1, y1, x2, y2 = box
    return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)

def box_area(box):
    x1, y1, x2, y2 = box
    return max(0.0, x2 - x1) * max(0.0, y2 - y1)

def dist_to_edge(box, w, h):
    x1, y1, x2, y2 = box
    return float(min(x1, y1, w - x2, h - y2)) / max(1.0, min(w, h))

def point_speed(points):
    out = [0.0] * len(points)
    prev = None
    for i, p in enumerate(points):
        if p is not None and prev is not None:
            out[i] = math.dist(p, prev)
        prev = p if p is not None else prev
    return out

def smooth(values, window):
    import numpy as np
    if window <= 1:
        return list(values)
    k = np.ones(window) / window
    pad = window // 2
    padded = np.pad(values, (pad, pad), mode="edge")
    conv = np.convolve(padded, k, mode="valid")
    return list(conv[: len(values)])

def find_peaks(speed, prominence_ratio, min_gap):
    import numpy as np
    n = len(speed)
    if n < 3:
        return []
    s = np.asarray(speed, dtype=float)
    baseline = np.median(s[s > 0]) if np.any(s > 0) else 0.0
    thr = baseline * prominence_ratio
    cand = [i for i in range(1, n - 1) if s[i] >= s[i - 1] and s[i] >= s[i + 1] and s[i] > thr]
    cand.sort(key=lambda i: -s[i])  # 强峰优先
    picked = []
    for i in cand:
        if all(abs(i - j) >= min_gap for j in picked):
            picked.append(i)
    return sorted(picked)
```
（文件头补 `import math`。）

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_geometry.py -v`
Expected: PASS（6 passed）

- [ ] **Step 5: Commit**

```bash
git add backend/app/cv backend/tests/test_geometry.py
git commit -m "feat: cv geometry pure functions (speed, smoothing, peaks)"
```

---

## Task 4: 挥拍事件构建 keyframes.py（三帧索引 + 裁剪框）

**Files:**
- Create: `backend/app/cv/keyframes.py`
- Test: `backend/tests/test_keyframes.py`

**Interfaces:**
- Consumes: `schemas.FrameDet`、`SwingEvent`；`config.settings`（prep_min_gap_frames、follow_offset_frames、crop_margin_ratio）。
- Produces:
  - `build_swing_events(dets: list[FrameDet], peaks: list[int], speed: list[float]) -> list[SwingEvent]`（填 peak/prep/follow 索引、max_speed、suspected_serve）
  - `crop_box_for(det: FrameDet, frame_w, frame_h, margin_ratio) -> (x1,y1,x2,y2)`（以人物框为中心加边距、夹在画面内）
  - `is_overhead(dets, peak_idx) -> bool`（持拍手腕/球拍高于肩膀且在画面上方，判"疑似发球"）

- [ ] **Step 1: 写失败测试**

```python
# tests/test_keyframes.py
from app.schemas import FrameDet
from app.cv.keyframes import build_swing_events, crop_box_for, is_overhead

def _det(i, ts, pbox, wrist=None, pose_ok=True):
    return FrameDet(frame_idx=i, ts=ts, player_box=pbox, player_conf=0.9,
                    wrist=wrist, pose_ok=pose_ok)

def test_build_swing_events_indices():
    dets = [_det(i, i / 15.0, (10, 10, 100, 300)) for i in range(40)]
    speed = [1.0] * 40; speed[20] = 20.0
    evs = build_swing_events(dets, [20], speed)
    assert len(evs) == 1
    e = evs[0]
    assert e.peak_idx == 20 and e.prep_idx < 20 and e.follow_idx > 20 and e.max_speed == 20.0

def test_crop_box_clamped_and_margined():
    det = _det(0, 0, (40, 40, 60, 400))
    x1, y1, x2, y2 = crop_box_for(det, 200, 500, 0.2)
    assert x1 >= 0 and y1 >= 0 and x2 <= 200 and y2 <= 500
    assert (x2 - x1) > 20  # 加了边距比原框宽

def test_overhead_serve_detected():
    # 手腕在画面很高处（y 很小）
    dets = [_det(i, i/15.0, (10, 10, 100, 300), wrist=(50, 30)) for i in range(10)]
    assert is_overhead(dets, 5) is True

def test_overhead_not_when_wrist_low():
    dets = [_det(i, i/15.0, (10, 10, 100, 300), wrist=(50, 250)) for i in range(10)]
    assert is_overhead(dets, 5) is False
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_keyframes.py -v`
Expected: FAIL（ModuleNotFoundError）

- [ ] **Step 3: 实现 keyframes.py**

```python
from ..schemas import FrameDet, SwingEvent
from ..config import settings
from .geometry import box_center

def build_swing_events(dets, peaks, speed):
    events = []
    n = len(dets)
    for p in peaks:
        prep = max(0, p - max(settings.prep_min_gap_frames, settings.follow_offset_frames))
        # 引拍：往回找一个局部低速点
        j = p - 1
        while j > 0 and speed[j] > speed[j - 1] and j > p - 15:
            j -= 1
        prep = max(0, j)
        follow = min(n - 1, p + settings.follow_offset_frames)
        serve = is_overhead(dets, p)
        events.append(SwingEvent(
            peak_idx=p, peak_ts=dets[p].ts, prep_idx=prep, follow_idx=follow,
            max_speed=float(speed[p]), suspected_serve=serve))
    return events

def crop_box_for(det, frame_w, frame_h, margin_ratio):
    x1, y1, x2, y2 = det.player_box
    w, h = x2 - x1, y2 - y1
    mx, my = w * margin_ratio, h * margin_ratio
    X1 = max(0, int(x1 - mx)); Y1 = max(0, int(y1 - my))
    X2 = min(frame_w, int(x2 + mx)); Y2 = min(frame_h, int(y2 + my))
    return (X1, Y1, X2, Y2)

def is_overhead(dets, peak_idx, look=3):
    hi = 0
    tot = 0
    for i in range(max(0, peak_idx - look), min(len(dets), peak_idx + 1)):
        d = dets[i]
        if d.wrist is not None and d.player_box:
            _, y1, _, y2 = d.player_box
            shoulder_y = y1 + (y2 - y1) * 0.3
            if d.wrist[1] < shoulder_y:  # 手腕高于肩部
                hi += 1
            tot += 1
    return tot > 0 and hi / tot >= 0.6
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_keyframes.py -v`
Expected: PASS（4 passed）

- [ ] **Step 5: Commit**

```bash
git add backend/app/cv/keyframes.py backend/tests/test_keyframes.py
git commit -m "feat: swing event construction and crop boxes"
```

---

## Task 5: 质量打分 quality.py

**Files:**
- Create: `backend/app/cv/quality.py`
- Test: `backend/tests/test_quality.py`

**Interfaces:**
- Consumes: `FrameDet`、`SwingEvent`、`geometry`；帧宽高。
- Produces: `score_event(det: FrameDet, ev: SwingEvent, frame_w, frame_h, baseline_speed: float) -> float`（0~1，越大越好）；并回填 `ev.quality`。

打分项（加权和，裁剪到 0~1）：人物置信度 0.25、人物框相对大小 0.25、距边缘 0.2、球拍可见 0.15、峰值尖锐度 0.1、姿态完整 0.05。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_quality.py
from app.schemas import FrameDet, SwingEvent
from app.cv.quality import score_event

def _ev():
    return SwingEvent(peak_idx=5, peak_ts=0.3, prep_idx=2, follow_idx=8, max_speed=20.0)

def test_good_clear_player_scores_higher_than_small_edge():
    good = FrameDet(5, 0.3, player_box=(60, 60, 200, 420), player_conf=0.95,
                    racket_box=(90, 200, 130, 260), racket_conf=0.9, wrist=(100, 220), pose_ok=True)
    bad = FrameDet(5, 0.3, player_box=(0, 0, 30, 60), player_conf=0.4,
                   racket_box=None, racket_conf=0.0, wrist=None, pose_ok=False)
    sg = score_event(good, _ev(), 640, 480, baseline_speed=2.0)
    sb = score_event(bad, _ev(), 640, 480, baseline_speed=2.0)
    assert sg > sb and sg > 0.6 and sb < 0.4
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_quality.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 quality.py**

```python
from .geometry import box_area, dist_to_edge

def _clamp(x): return max(0.0, min(1.0, x))

def score_event(det, ev, frame_w, frame_h, baseline_speed):
    s = 0.0
    s += 0.25 * _clamp(det.player_conf)
    area_ratio = box_area(det.player_box) / float(frame_w * frame_h) if det.player_box else 0.0
    s += 0.25 * _clamp(area_ratio / 0.15)          # 人物占画面 ~15% 视为满分
    if det.player_box:
        s += 0.20 * _clamp(dist_to_edge(det.player_box, frame_w, frame_h) / 0.05)
    s += 0.15 * _clamp(det.racket_conf)
    sharp = (ev.max_speed / baseline_speed) if baseline_speed > 1e-6 else 1.0
    s += 0.10 * _clamp(sharp / 5.0)
    s += 0.05 * (1.0 if det.pose_ok else 0.0)
    ev.quality = _clamp(s)
    return ev.quality
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_quality.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/cv/quality.py backend/tests/test_quality.py
git commit -m "feat: swing quality scoring"
```

---

## Task 6: 去重 + 回合聚类 + 择优 select.py

**Files:**
- Create: `backend/app/cv/select.py`
- Test: `backend/tests/test_select.py`

**Interfaces:**
- Consumes: `SwingEvent`（已含 quality、peak_ts、suspected_serve）；`config.settings.target_actions`、`rally_gap_seconds`。
- Produces: `select_best(events: list[SwingEvent], target: int, gap_seconds: float) -> list[SwingEvent]`：按时间间隔把事件分到不同回合；每回合取质量最高的一个；再从各回合代表里按质量排序取 `target` 个，但**保证若存在 suspected_serve 且 target>=2，至少含 1 个发球**；结果按时间升序返回。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_select.py
from app.schemas import SwingEvent
from app.cv.select import select_best

def _ev(i, ts, q, serve=False):
    return SwingEvent(peak_idx=i, peak_ts=ts, prep_idx=i-3, follow_idx=i+3,
                      max_speed=10, quality=q, suspected_serve=serve)

def test_picks_top_quality_across_rallies():
    # 两个回合（间隔>6s）：回合1 两个动作，回合2 一个动作
    evs = [_ev(10, 1.0, 0.3), _ev(20, 2.0, 0.9), _ev(200, 20.0, 0.8)]
    out = select_best(evs, target=3, gap_seconds=6.0)
    tss = [e.peak_ts for e in out]
    assert 2.0 in tss and 20.0 in tss       # 每回合取最优代表
    assert 1.0 not in tss                    # 回合1 内质量低的被去掉

def test_keeps_a_serve_when_available():
    evs = [_ev(5, 0.5, 0.5, serve=True), _ev(50, 5.0, 0.95), _ev(150, 15.0, 0.9)]
    out = select_best(evs, target=2, gap_seconds=6.0)
    assert any(e.suspected_serve for e in out)
    assert len(out) == 2

def test_respects_target_count():
    evs = [_ev(i, i * 10.0, 0.8) for i in range(1, 6)]
    assert len(select_best(evs, target=3, gap_seconds=6.0)) == 3
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_select.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 select.py**

```python
def _rallies(events, gap_seconds):
    events = sorted(events, key=lambda e: e.peak_ts)
    rallies, cur = [], []
    for e in events:
        if cur and e.peak_ts - cur[-1].peak_ts > gap_seconds:
            rallies.append(cur); cur = []
        cur.append(e)
    if cur:
        rallies.append(cur)
    return rallies

def select_best(events, target, gap_seconds):
    reps = [max(r, key=lambda e: e.quality) for r in _rallies(events, gap_seconds)]
    reps.sort(key=lambda e: -e.quality)
    chosen = reps[:target]
    serves = [e for e in reps if e.suspected_serve and e not in chosen]
    if target >= 2 and serves and not any(e.suspected_serve for e in chosen):
        chosen[-1] = serves[0]  # 用质量最高的发球替换末位
    return sorted(chosen, key=lambda e: e.peak_ts)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_select.py -v`
Expected: PASS（3 passed）

- [ ] **Step 5: Commit**

```bash
git add backend/app/cv/select.py backend/tests/test_select.py
git commit -m "feat: rally clustering and best-action selection"
```

---

## Task 7: 拼贴图 montage.py

**Files:**
- Create: `backend/app/cv/montage.py`
- Test: `backend/tests/test_montage.py`（用合成黑帧，验证产出文件存在且尺寸正确）

**Interfaces:**
- Consumes: 抽好的帧 `list[np.ndarray]`、一个 `SwingEvent`、`FrameDet` 列表、帧宽高、`keyframes.crop_box_for`、`config.crop_margin_ratio`。
- Produces: `make_montage(frames, dets, event, out_path, frame_w, frame_h) -> None`：取 prep/peak/follow 三帧，各自按人物框裁剪、缩放到统一高度，横向拼接，顶部用中文标注"准备 / 击球 / 随挥"，写入 JPG。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_montage.py
import numpy as np
from pathlib import Path
from app.schemas import FrameDet, SwingEvent
from app.cv.montage import make_montage

def test_montage_written(tmp_path):
    frames = [np.zeros((480, 640, 3), dtype=np.uint8) for _ in range(20)]
    dets = [FrameDet(i, i/15.0, player_box=(100, 60, 300, 440), player_conf=0.9, pose_ok=True)
            for i in range(20)]
    ev = SwingEvent(peak_idx=10, peak_ts=0.6, prep_idx=6, follow_idx=14, max_speed=10)
    out = tmp_path / "m.jpg"
    make_montage(frames, dets, ev, out, 640, 480)
    assert out.exists() and out.stat().st_size > 0
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_montage.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 montage.py**

```python
import cv2
import numpy as np
from ..config import settings
from .keyframes import crop_box_for

# OpenCV putText 不支持中文字体，用英文标签（语义：准备/击球/随挥）
LABELS = ["Ready", "Impact", "Follow"]
H = 360  # 统一高度

def _crop_resize(frame, det, w, h):
    x1, y1, x2, y2 = crop_box_for(det, w, h, settings.crop_margin_ratio)
    crop = frame[max(0,y1):y2, max(0,x1):x2]
    if crop.size == 0:
        crop = frame
    scale = H / crop.shape[0]
    return cv2.resize(crop, (max(1, int(crop.shape[1] * scale)), H))

def make_montage(frames, dets, event, out_path, frame_w, frame_h):
    idxs = [event.prep_idx, event.peak_idx, event.follow_idx]
    tiles = []
    for label, idx in zip(LABELS, idxs):
        tile = _crop_resize(frames[idx], dets[idx], frame_w, frame_h)
        cv2.putText(tile, label, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0,255,0), 2)
        tiles.append(tile)
    montage = np.hstack(tiles)
    cv2.imwrite(str(out_path), montage)
```
注：OpenCV `putText` 不支持中文字体，故标签用英文 `Ready / Impact / Follow`（语义即准备/击球/随挥）；如需中文标注，后续可改用 PIL 绘制。

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_montage.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/cv/montage.py backend/tests/test_montage.py
git commit -m "feat: three-frame montage builder"
```

---

## Task 8: 抽帧 frames.py

**Files:**
- Create: `backend/app/cv/frames.py`

**Interfaces:**
- Produces: `extract_frames(video_path: Path, fps: float) -> tuple[list[np.ndarray], list[float], int, int]`：返回帧列表、每帧时间戳（秒）、帧宽、帧高。用 OpenCV `VideoCapture`，按目标 fps 跳帧读取。无法打开时抛 `ValueError`。

- [ ] **Step 1: 实现 frames.py**

```python
import cv2
from pathlib import Path

def extract_frames(video_path: Path, fps: float):
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise ValueError(f"cannot open video: {video_path}")
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    step = max(1, round(src_fps / fps))
    frames, ts = [], []
    idx = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if idx % step == 0:
            frames.append(frame)
            ts.append(idx / src_fps)
        idx += 1
    cap.release()
    if not frames:
        raise ValueError("no frames decoded")
    h, w = frames[0].shape[:2]
    return frames, ts, w, h
```

- [ ] **Step 2: 手动验证**（无样本视频时跳过自动测试）

Run: 在 Python 里 `from app.cv.frames import extract_frames; from pathlib import Path; f,ts,w,h = extract_frames(Path('<某段.mp4>'), 15.0); print(len(f), w, h)`
Expected: 打印帧数与分辨率；坏路径抛 ValueError。

- [ ] **Step 3: Commit**

```bash
git add backend/app/cv/frames.py
git commit -m "feat: frame extraction at target fps"
```

---

## Task 9: YOLO 检测跟踪包装 detect.py（集成层）

**Files:**
- Create: `backend/app/cv/detect.py`

**Interfaces:**
- Produces:
  - `class Detector`：`__init__()` 加载 `yolo11n-pose.pt`（pose 模型同时输出 box+keypoints；person/racket 中 racket 用 `yolo11n.pt` 检测，或在同模型按 COCO 类过滤）。
  - `detect_frames(frames, target_player=None) -> list[FrameDet]`：逐帧检测；用 Ultralytics `model.track(persist=True)` 拿 track id；若 `target_player` 为 None 且画面多人，默认取画面中最大的 person；记录该 person 的 box/conf、其附近最近的 racket box/conf、持拍侧手腕关键点（取两手中更低/更靠近球拍的那只）、pose_ok（17 点中可见数 >= 12）。

**实现要点（手动验证，不写单测）：**
- 模型：`from ultralytics import YOLO; pose = YOLO("yolo11n-pose.pt")`。pose 模型检测 person 并给 17 关键点；racket 用 `det = YOLO("yolo11n.pt")`，取 class 38（tennis racket）。
- 跟踪：`pose.track(frame, persist=True, classes=[0], device=...)`；Mac 用 `device="mps"`，失败回退 `"cpu"`。
- 手腕：COCO 关键点索引 9（左手腕）、10（右手腕）；选距球拍中心更近的那只；无球拍时取 y 更大（更低）的手。
- 首帧球员选择由前端完成（Task 17 传坐标）；本任务先实现"取最大 person"，并支持 `target_player=(cx,cy)` 参数选距该点最近的 person。

- [ ] **Step 1: 实现 detect.py**（按上述要点；封装为类，模型只加载一次）

```python
import math
from ..schemas import FrameDet

class Detector:
    def __init__(self, device=None):
        from ultralytics import YOLO
        self.pose = YOLO("yolo11n-pose.pt")
        self.det = YOLO("yolo11n.pt")
        self.device = device or self._pick_device()
        self._track_id = None

    def _pick_device(self):
        import torch
        return "mps" if torch.backends.mps.is_available() else "cpu"

    def detect_frames(self, frames, timestamps, target_player=None):
        out = []
        for i, frame in enumerate(frames):
            r = self.pose.track(frame, persist=True, classes=[0],
                                device=self.device, verbose=False)[0]
            rd = self.det(frame, classes=[38], device=self.device, verbose=False)[0]
            det = self._pick_player(r, frame.shape, target_player)
            racket = self._nearest_racket(rd, det)
            wrist = self._wrist(r, det, racket)
            out.append(FrameDet(
                frame_idx=i, ts=timestamps[i],
                player_box=det["box"], player_conf=det["conf"],
                racket_box=racket["box"], racket_conf=racket["conf"],
                wrist=wrist, pose_ok=det["pose_ok"]))
        return out
    # _pick_player / _nearest_racket / _wrist 为内部辅助：
    #  _pick_player: 取 track id 稳定的目标；无 _track_id 时选距 target_player 最近或面积最大的 person，记录其 id
    #  _nearest_racket: 在所有 class 38 框里选距目标人物框中心最近的
    #  _wrist: keypoints idx 9/10，选距球拍中心近者，无球拍则取 y 大者
```
（三个内部辅助方法在实现时补全；返回 `{"box":(x1,y1,x2,y2), "conf":float, "pose_ok":bool}` 等。）

- [ ] **Step 2: 手动验证**

Run: `python -c "from app.cv.detect import Detector; from app.cv.frames import extract_frames; from pathlib import Path; f,ts,w,h=extract_frames(Path('<视频>'),15); d=Detector(); dets=d.detect_frames(f[:10],ts[:10]); print([(x.player_conf, x.racket_conf, x.wrist) for x in dets])"`
Expected: 首次自动下载 yolo11n 权重；打印每帧人物/球拍置信度与手腕坐标，人物稳定跟踪。

- [ ] **Step 3: Commit**

```bash
git add backend/app/cv/detect.py
git commit -m "feat: YOLO person/racket/pose detection wrapper"
```

---

## Task 10: LLM JSON 解析 parse.py

**Files:**
- Create: `backend/app/llm/__init__.py`（空）
- Create: `backend/app/llm/parse.py`
- Test: `backend/tests/test_parse.py`

**Interfaces:**
- Produces: `parse_analysis(text: str) -> dict`：从回复文本抽取 JSON 对象；容错 ```json 代码块与前后多余文字；返回规范化 dict（含 stroke_type/scores/overall/issues/advice 字段，缺失给默认）。无法解析时抛 `ValueError`。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_parse.py
import pytest
from app.llm.parse import parse_analysis

def test_plain_json():
    d = parse_analysis('{"stroke_type":"forehand","scores":{"准备":8},"overall":7.5,"issues":["a"],"advice":"x"}')
    assert d["stroke_type"] == "forehand" and d["overall"] == 7.5

def test_json_in_code_fence():
    txt = '好的，分析如下：\n```json\n{"stroke_type":"serve","scores":{},"overall":8,"issues":[],"advice":"y"}\n```'
    assert parse_analysis(txt)["stroke_type"] == "serve"

def test_json_with_surrounding_text():
    txt = '结果是 {"stroke_type":"backhand","scores":{},"overall":6,"issues":[],"advice":"z"} 希望有帮助'
    assert parse_analysis(txt)["stroke_type"] == "backhand"

def test_invalid_raises():
    with pytest.raises(ValueError):
        parse_analysis("对不起，我无法分析这张图片")

def test_normalizes_missing_fields():
    d = parse_analysis('{"stroke_type":"forehand"}')
    assert set(["scores","overall","issues","advice"]) <= set(d.keys())
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_parse.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 parse.py**

```python
import json, re

def _extract_object(text):
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fence:
        return fence.group(1)
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        return text[start:end + 1]
    raise ValueError("no json object found")

def parse_analysis(text):
    raw = _extract_object(text)
    try:
        d = json.loads(raw)
    except json.JSONDecodeError:
        raise ValueError("invalid json")
    return {
        "stroke_type": d.get("stroke_type"),
        "scores": d.get("scores", {}) or {},
        "overall": d.get("overall"),
        "issues": d.get("issues", []) or [],
        "advice": d.get("advice", ""),
    }
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_parse.py -v`
Expected: PASS（5 passed）

- [ ] **Step 5: Commit**

```bash
git add backend/app/llm/parse.py backend/tests/test_parse.py
git commit -m "feat: tolerant LLM JSON response parser"
```

---

## Task 11: 提示词与选择器配置

**Files:**
- Create: `backend/app/llm/prompts.py`
- Create: `backend/app/llm/selectors.py`

**Interfaces:**
- Produces: `prompts.ANALYSIS_PROMPT`（str）；`selectors.SELECTORS`（dict，通义千问页面元素定位）。

- [ ] **Step 1: 写 prompts.py**

```python
ANALYSIS_PROMPT = (
    "你是专业网球教练。这张图从左到右是同一个击球动作的三个阶段："
    "准备(引拍)、击球瞬间、随挥。请判断动作类型并给出技术纠错。\n"
    "只返回一个 JSON 对象，不要输出任何其他文字，格式：\n"
    '{"stroke_type":"forehand 或 backhand 或 serve",'
    '"scores":{"准备":0-10整数,"击球点":0-10整数,"随挥":0-10整数},'
    '"overall":0-10的数字,'
    '"issues":["问题1","问题2"],'
    '"advice":"一段改进建议"}\n'
    "stroke_type 只能是 forehand(正手)、backhand(反手)、serve(发球) 之一。"
)
```

- [ ] **Step 2: 写 selectors.py**

```python
# 通义千问网页选择器。网页改版时只需修改此处。
# 占位选择器在 Task 12 手动登录后用浏览器 DevTools 核对并填准。
TONGYI_URL = "https://www.tongyi.com"

SELECTORS = {
    "upload_button": "input[type=file]",          # 文件上传 input
    "chat_input":   "textarea",                    # 消息输入框
    "send_button":  "button[data-testid='send']",  # 发送按钮（核对）
    "stop_button":  "button[aria-label*='停止']",  # 生成中出现
    "reply_block":  "div.message-assistant",       # 助手回复容器（核对）
    "new_chat":     "button:has-text('新对话')",   # 新开对话（核对）
}
```
注：这些是初始猜测值；Task 12 会打开浏览器实测，用 DevTools 核对真实选择器并回填本文件。

- [ ] **Step 3: Commit**

```bash
git add backend/app/llm/prompts.py backend/app/llm/selectors.py
git commit -m "feat: LLM prompt and tongyi selectors config"
```

---

## Task 12: Playwright 持久浏览器会话 + 登录 browser.py（集成层）

**Files:**
- Create: `backend/app/llm/browser.py`

**Interfaces:**
- Produces:
  - `class BrowserSession`：`start()`（用 `playwright.chromium.launch_persistent_context(settings.data_dir, headless=False)` 打开通义千问）、`is_logged_in() -> bool`（检测页面有无登录按钮/扫码区 vs 聊天输入框）、`open_for_login()`（把窗口带到前台，等用户登录）、`page` 属性。
  - 全局单例 `browser = BrowserSession()`，由 main.py 启动时 `start()`。

- [ ] **Step 1: 实现 browser.py**

```python
from ..config import settings
from .selectors import TONGYI_URL

class BrowserSession:
    def __init__(self):
        self._pw = None
        self.context = None
        self.page = None

    def start(self):
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        self.context = self._pw.chromium.launch_persistent_context(
            str(settings.data_dir), headless=False,
            accept_downloads=True, args=["--start-maximized"])
        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
        self.page.goto(TONGYI_URL)

    def is_logged_in(self):
        if not self.page:
            return False
        # 有聊天输入框视为已登录；出现"登录/扫码"视为未登录
        try:
            self.page.wait_for_selector("textarea", timeout=3000)
            return True
        except Exception:
            return False

    def open_for_login(self):
        if self.page:
            self.page.bring_to_front()
            self.page.goto(TONGYI_URL)

browser = BrowserSession()
```

- [ ] **Step 2: 手动验证登录流程**

Run: `python -c "from app.llm.browser import browser; browser.start(); import time; print('logged_in:', browser.is_logged_in()); time.sleep(120)"`
Expected: 弹出 Chromium 打开通义千问；首次手动扫码/账号登录；120 秒内登录后打印 `logged_in: True`；关闭后 `settings.data_dir` 保留登录态，再次运行无需登录。

- [ ] **Step 3: 核对并回填选择器**

登录后用 DevTools 检查上传、输入框、发送、停止、回复容器、新对话按钮的真实定位，更新 `selectors.py`。

- [ ] **Step 4: Commit**

```bash
git add backend/app/llm/browser.py backend/app/llm/selectors.py
git commit -m "feat: persistent playwright browser session with login"
```

---

## Task 13: 通义千问交互 + 串行队列 tongyi.py（集成层）

**Files:**
- Create: `backend/app/llm/tongyi.py`

**Interfaces:**
- Consumes: `browser.browser`、`selectors.SELECTORS`、`prompts.ANALYSIS_PROMPT`、`parse.parse_analysis`、`config`（延时/重试）。
- Produces:
  - `analyze_image(image_path: Path) -> dict`：完整一次"新对话→上传图→填提示词→发送→等回复→解析"，成功返回规范化 dict，失败重试至 `llm_max_retries`，最终失败抛 `RuntimeError`。
  - `class LLMSerialQueue`：`submit(image_path) -> dict`（用一把锁保证串行；任务间 `random.uniform(min,max)` 延时）。全局 `llm_queue = LLMSerialQueue()`。

- [ ] **Step 1: 实现 tongyi.py**

```python
import random, time
from pathlib import Path
from ..config import settings
from .browser import browser
from .selectors import SELECTORS
from .prompts import ANALYSIS_PROMPT
from .parse import parse_analysis

def _wait_reply(page, timeout_s=180):
    # 等待"停止生成"出现再消失，表示回复完成
    try:
        page.wait_for_selector(SELECTORS["stop_button"], timeout=15000)
    except Exception:
        pass
    page.wait_for_selector(SELECTORS["stop_button"], state="detached", timeout=timeout_s * 1000)
    blocks = page.query_selector_all(SELECTORS["reply_block"])
    return blocks[-1].inner_text() if blocks else ""

def analyze_image(image_path: Path) -> dict:
    page = browser.page
    page.goto("https://www.tongyi.com")
    page.wait_for_selector(SELECTORS["chat_input"], timeout=30000)
    page.set_input_files(SELECTORS["upload_button"], str(image_path))
    page.wait_for_timeout(2000)  # 等上传完成
    page.fill(SELECTORS["chat_input"], ANALYSIS_PROMPT)
    page.click(SELECTORS["send_button"])
    text = _wait_reply(page)
    return parse_analysis(text)  # 失败抛 ValueError

class LLMSerialQueue:
    def __init__(self):
        import threading
        self._lock = threading.Lock()

    def submit(self, image_path):
        with self._lock:
            last = None
            for attempt in range(settings.llm_max_retries + 1):
                try:
                    result = analyze_image(Path(image_path))
                    time.sleep(random.uniform(settings.llm_min_delay_s, settings.llm_max_delay_s))
                    return result
                except Exception as e:
                    last = e
                    time.sleep(2.0)
            raise RuntimeError(f"llm failed after retries: {last}")

llm_queue = LLMSerialQueue()
```

- [ ] **Step 2: 手动验证单张分析**

Run: `python -c "from app.llm.browser import browser; from app.llm.tongyi import llm_queue; from pathlib import Path; browser.start(); print(llm_queue.submit(Path('<某拼贴图.jpg>')))"`
Expected: 浏览器自动新对话、上传、发送、等待，终端打印出含 stroke_type/scores/overall 的 dict。若选择器不准，回到 selectors.py 修正。

- [ ] **Step 3: Commit**

```bash
git add backend/app/llm/tongyi.py
git commit -m "feat: tongyi image analysis with serial queue"
```

---

## Task 14: 任务编排 jobs.py + 管线 pipeline.py

**Files:**
- Create: `backend/app/pipeline.py`
- Create: `backend/app/jobs.py`

**Interfaces:**
- Consumes: 全部 cv 模块、`llm.tongyi.llm_queue`、`storage`、`schemas`。
- Produces:
  - `pipeline.run_pipeline(job_id, target_player=None, on_progress=callable) -> JobResult`
  - `jobs.JobManager`：`create(video_path, target_player) -> job_id`（后台线程跑 pipeline）、`get(job_id) -> JobResult|None`、`subscribe(job_id) -> queue.Queue`（SSE 用）、内部进度回调把 `(stage,progress,message)` 推给订阅者并落盘。

- [ ] **Step 1: 实现 pipeline.py**

```python
from pathlib import Path
from .config import settings
from .schemas import JobResult, ActionRecord
from . import storage
from .cv.frames import extract_frames
from .cv.detect import Detector
from .cv.geometry import point_speed, smooth, find_peaks, box_center
from .cv.keyframes import build_swing_events
from .cv.quality import score_event
from .cv.select import select_best
from .cv.montage import make_montage
from .llm.tongyi import llm_queue

def run_pipeline(job_id, target_player=None, on_progress=None):
    def prog(pct, stage, msg=""):
        if on_progress: on_progress(pct, stage, msg)

    video = storage.video_path(job_id)
    result = JobResult(job_id=job_id, video_path=video.name, status="running")
    prog(5, "extracting", "抽帧中")
    frames, ts, w, h = extract_frames(video, settings.extract_fps)

    prog(15, "detecting", "检测球员中")
    detector = Detector()
    dets = detector.detect_frames(frames, ts, target_player)
    valid = [d for d in dets if d.player_box]
    if not valid:
        result.status = "error"; result.message = "未检测到球员，请更换视频"
        storage.save_result(result); return result

    # 速度序列：优先球拍中心，缺失回退手腕
    pts = []
    for d in dets:
        if d.racket_box: pts.append(box_center(d.racket_box))
        else: pts.append(d.wrist)
    speed = smooth(point_speed(pts), settings.speed_smooth_window)
    import numpy as np
    baseline = float(np.median([s for s in speed if s > 0]) or 1.0)
    peaks = find_peaks(speed, settings.peak_prominence_ratio, settings.speed_smooth_window)
    events = build_swing_events(dets, peaks, speed)
    for e in events:
        score_event(dets[e.peak_idx], e, w, h, baseline)
    if not events:
        result.status = "error"; result.message = "未找到清晰动作，请换更清晰的视频"
        storage.save_result(result); return result

    best = select_best(events, settings.target_actions, settings.rally_gap_seconds)
    prog(55, "montage", "生成关键帧")
    records = []
    for aid, e in enumerate(best):
        mp = storage.montage_path(job_id, aid)
        make_montage(frames, dets, e, mp, w, h)
        records.append(ActionRecord(action_id=aid, peak_ts=e.peak_ts,
                                    montage_path=f"montages/{mp.name}",
                                    suspected_serve=e.suspected_serve))
    result.actions = records
    storage.save_result(result)

    prog(70, "analyzing", f"大模型分析 0/{len(records)}")
    for rec in records:
        try:
            data = llm_queue.submit(storage.job_dir(job_id) / rec.montage_path)
            rec.status = "ok"; rec.stroke_type = data["stroke_type"]
            rec.scores = data["scores"]; rec.overall = data["overall"]
            rec.issues = data["issues"]; rec.advice = data["advice"]
        except Exception as ex:
            rec.status = "failed"; rec.raw_reply = str(ex)
        prog(70 + 25 * (rec.action_id + 1) / len(records), "analyzing",
             f"大模型分析 {rec.action_id + 1}/{len(records)}")
        storage.save_result(result)

    result.status = "done"; result.progress = 100; result.stage = "done"
    storage.save_result(result)
    prog(100, "done", "完成")
    return result
```

- [ ] **Step 2: 实现 jobs.py**

```python
import queue, threading, uuid
from . import storage
from .pipeline import run_pipeline

class JobManager:
    def __init__(self):
        self._subs = {}   # job_id -> list[queue.Queue]
        self._lock = threading.Lock()

    def create(self, video_src_path, filename, target_player=None):
        job_id = uuid.uuid4().hex[:12]
        storage.create_job(job_id, filename)
        import shutil
        shutil.copy(video_src_path, storage.video_path(job_id))
        threading.Thread(target=self._run, args=(job_id, target_player), daemon=True).start()
        return job_id

    def _run(self, job_id, target_player):
        def on_progress(pct, stage, msg):
            r = storage.load_result(job_id)
            if r is None:
                from .schemas import JobResult
                r = JobResult(job_id=job_id, video_path="")
            r.progress, r.stage, r.message, r.status = pct, stage, msg, "running"
            storage.save_result(r)
            self._publish(job_id, {"progress": pct, "stage": stage, "message": msg})
        try:
            run_pipeline(job_id, target_player, on_progress)
        except Exception as e:
            r = storage.load_result(job_id)
            if r:
                r.status = "error"; r.message = str(e); storage.save_result(r)
            self._publish(job_id, {"stage": "error", "message": str(e)})

    def get(self, job_id):
        return storage.load_result(job_id)

    def subscribe(self, job_id):
        q = queue.Queue()
        with self._lock:
            self._subs.setdefault(job_id, []).append(q)
        return q

    def unsubscribe(self, job_id, q):
        with self._lock:
            if job_id in self._subs and q in self._subs[job_id]:
                self._subs[job_id].remove(q)

    def _publish(self, job_id, event):
        with self._lock:
            for q in self._subs.get(job_id, []):
                q.put(event)

job_manager = JobManager()
```

- [ ] **Step 3: 跑全部纯逻辑单测确保无回归**

Run: `pytest tests/ -v`
Expected: 此前所有单测 PASS（pipeline/jobs 依赖 YOLO/浏览器，不在这里单测）。

- [ ] **Step 4: Commit**

```bash
git add backend/app/pipeline.py backend/app/jobs.py
git commit -m "feat: pipeline orchestration and job manager"
```

---

## Task 15: HTTP 路由 + main 接线

**Files:**
- Create: `backend/app/routes/__init__.py`（空）
- Create: `backend/app/routes/upload.py`
- Create: `backend/app/routes/progress.py`
- Create: `backend/app/routes/results.py`
- Create: `backend/app/routes/session.py`
- Modify: `backend/app/main.py`

**Interfaces:**
- Produces:
  - `POST /api/jobs`：multipart 上传 `video` + 可选表单 `cx,cy`（球员点选），返回 `{job_id}`。
  - `GET /api/jobs/{job_id}/events`：SSE，推送进度事件，任务结束后关闭。
  - `GET /api/jobs/{job_id}/result`：返回 JobResult JSON。
  - `GET /api/jobs/{job_id}/montage/{name}`：返回拼贴图。
  - `GET /api/llm/login-status` → `{logged_in: bool}`；`POST /api/llm/login` → 打开登录窗口。

- [ ] **Step 1: 写 upload.py**

```python
import tempfile
from fastapi import APIRouter, UploadFile, File, Form
from ..jobs import job_manager

router = APIRouter()

@router.post("/api/jobs")
async def create_job(video: UploadFile = File(...), cx: float = Form(None), cy: float = Form(None)):
    suffix = "." + video.filename.split(".")[-1]
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await video.read())
        tmp_path = tmp.name
    target = (cx, cy) if cx is not None and cy is not None else None
    job_id = job_manager.create(tmp_path, video.filename, target)
    return {"job_id": job_id}
```

- [ ] **Step 2: 写 progress.py（SSE）**

```python
import json
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from ..jobs import job_manager

router = APIRouter()

@router.get("/api/jobs/{job_id}/events")
def events(job_id: str):
    q = job_manager.subscribe(job_id)
    def stream():
        try:
            while True:
                ev = q.get(timeout=15)
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
                if ev.get("stage") in ("done", "error"):
                    break
        except Exception:
            pass
        finally:
            job_manager.unsubscribe(job_id, q)
    return StreamingResponse(stream(), media_type="text/event-stream")
```

- [ ] **Step 3: 写 results.py**

```python
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from dataclasses import asdict
from ..jobs import job_manager
from .. import storage

router = APIRouter()

@router.get("/api/jobs/{job_id}/result")
def result(job_id: str):
    r = job_manager.get(job_id)
    if r is None:
        raise HTTPException(404, "job not found")
    return asdict(r)

@router.get("/api/jobs/{job_id}/montage/{name}")
def montage(job_id: str, name: str):
    p = storage.job_dir(job_id) / "montages" / name
    if not p.exists():
        raise HTTPException(404, "montage not found")
    return FileResponse(p)
```

- [ ] **Step 4: 写 session.py**

```python
from fastapi import APIRouter
from ..llm.browser import browser

router = APIRouter()

@router.get("/api/llm/login-status")
def login_status():
    return {"logged_in": browser.is_logged_in()}

@router.post("/api/llm/login")
def login():
    browser.open_for_login()
    return {"ok": True}
```

- [ ] **Step 5: 修改 main.py 接线（含启动浏览器）**

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .routes import upload, progress, results, session

def create_app() -> FastAPI:
    app = FastAPI(title="tennis-ai")
    app.add_middleware(CORSMiddleware, allow_origins=["*"],
                       allow_methods=["*"], allow_headers=["*"])
    app.include_router(upload.router)
    app.include_router(progress.router)
    app.include_router(results.router)
    app.include_router(session.router)

    @app.on_event("startup")
    def _start_browser():
        try:
            from .llm.browser import browser as b
            b.start()
        except Exception as e:
            print("browser start failed:", e)

    @app.get("/api/health")
    def health():
        return {"ok": True}
    return app

app = create_app()
```

- [ ] **Step 6: 启动并冒烟测试各接口**

Run: `uvicorn app.main:app --port 8000`；另开终端：
`curl -s localhost:8000/api/health`、`curl -s localhost:8000/api/llm/login-status`
Expected: health 返回 ok；login-status 返回 JSON（浏览器弹出并打开通义千问）。

- [ ] **Step 7: Commit**

```bash
git add backend/app/routes backend/app/main.py
git commit -m "feat: http routes (upload, sse, results, session) and app wiring"
```

---

## Task 16: 前端脚手架 + API 封装

**Files:**
- Create: `frontend/`（Vite React TS）
- Create: `frontend/src/types.ts`
- Create: `frontend/src/api.ts`

**Interfaces:**
- Produces: 前端类型 `ActionRecord`、`JobResult`、`ProgressEvent`；API：`createJob(file, cx?, cy?): Promise<job_id>`、`streamEvents(job_id, cb)`、`getResult(job_id)`、`montageUrl(job_id, path)`、`getLoginStatus()`、`login()`。

- [ ] **Step 1: 脚手架**

Run: `cd /Users/winniehe/project/Sync-Grid/tennis-ai && npm create vite@latest frontend -- --template react-ts && cd frontend && npm install`
Expected: 生成可运行的 Vite React TS 项目；`npm run dev` 可起。

- [ ] **Step 2: 写 types.ts**

```ts
export interface ActionRecord {
  action_id: number; peak_ts: number; montage_path: string;
  suspected_serve: boolean; status: string;
  stroke_type: string | null; scores: Record<string, number>;
  overall: number | null; issues: string[]; advice: string; raw_reply: string;
}
export interface JobResult {
  job_id: string; status: string; progress: number; stage: string;
  message: string; actions: ActionRecord[];
}
export interface ProgressEvent { progress: number; stage: string; message: string; }
```

- [ ] **Step 3: 写 api.ts**

```ts
const BASE = "http://localhost:8000";

export async function createJob(file: File, cx?: number, cy?: number): Promise<string> {
  const fd = new FormData();
  fd.append("video", file);
  if (cx != null && cy != null) { fd.append("cx", String(cx)); fd.append("cy", String(cy)); }
  const r = await fetch(`${BASE}/api/jobs`, { method: "POST", body: fd });
  return (await r.json()).job_id;
}

export function streamEvents(jobId: string, cb: (e: ProgressEvent) => void): () => void {
  const es = new EventSource(`${BASE}/api/jobs/${jobId}/events`);
  es.onmessage = (m) => cb(JSON.parse(m.data));
  return () => es.close();
}

export async function getResult(jobId: string): Promise<JobResult> {
  return (await fetch(`${BASE}/api/jobs/${jobId}/result`)).json();
}

export function montageUrl(jobId: string, path: string): string {
  return `${BASE}/api/jobs/${jobId}/${path}`;
}

export async function getLoginStatus(): Promise<boolean> {
  return (await fetch(`${BASE}/api/llm/login-status`)).json().then(r => r.logged_in);
}
export async function login(): Promise<void> {
  await fetch(`${BASE}/api/llm/login`, { method: "POST" });
}
```

- [ ] **Step 4: Commit**

```bash
git add frontend
git commit -m "feat: frontend scaffold with api client"
```

---

## Task 17: 上传 + 球员点选 + 进度 + 结果组件

**Files:**
- Create: `frontend/src/components/Uploader.tsx`
- Create: `frontend/src/components/PlayerPicker.tsx`
- Create: `frontend/src/components/Progress.tsx`
- Create: `frontend/src/components/Results.tsx`
- Modify: `frontend/src/App.tsx`

**Interfaces:**
- Consumes: Task 16 的 api.ts。
- 流程：App 状态机 `upload → pick → progress → results`。

- [ ] **Step 1: Uploader.tsx**

```tsx
import { useState } from "react";

export function Uploader({ onFile }: { onFile: (f: File) => void }) {
  const [file, setFile] = useState<File | null>(null);
  return (
    <div style={{ padding: 24 }}>
      <h1>网球动作分析</h1>
      <input type="file" accept="video/*" onChange={e => setFile(e.target.files?.[0] ?? null)} />
      <button disabled={!file} onClick={() => file && onFile(file)}>上传并分析</button>
    </div>
  );
}
```

- [ ] **Step 2: PlayerPicker.tsx**（点选要分析的球员；简化：显示视频首帧，点击坐标传 cx,cy；也可"跳过=自动选最大"）

```tsx
import { useRef } from "react";

export function PlayerPicker({ file, onPick, onSkip }:
  { file: File; onPick: (x: number, y: number) => void; onSkip: () => void }) {
  const videoRef = useRef<HTMLVideoElement>(null);
  function handleClick(e: React.MouseEvent<HTMLVideoElement>) {
    const v = videoRef.current!;
    const cx = (e.nativeEvent.offsetX / v.clientWidth) * v.videoWidth;
    const cy = (e.nativeEvent.offsetY / v.clientHeight) * v.videoHeight;
    onPick(cx, cy);
  }
  return (
    <div>
      <p>点击要分析的球员（多人时），或直接跳过自动选择：</p>
      <video ref={videoRef} src={URL.createObjectURL(file)} controls style={{ maxWidth: 640 }}
             onClick={handleClick} />
      <button onClick={onSkip}>跳过，自动选择</button>
    </div>
  );
}
```

- [ ] **Step 3: Progress.tsx**

```tsx
import { ProgressEvent } from "../types";
export function Progress({ ev }: { ev: ProgressEvent | null }) {
  const pct = Math.round(ev?.progress ?? 0);
  return (
    <div style={{ padding: 24 }}>
      <h2>分析中…</h2>
      <p>{ev?.message ?? "准备中"}</p>
      <progress value={pct} max={100} style={{ width: "100%" }} /> {pct}%
    </div>
  );
}
```

- [ ] **Step 4: Results.tsx**

```tsx
import { JobResult } from "../types";
import { montageUrl } from "../api";
const TYPE: Record<string, string> = { forehand: "正手", backhand: "反手", serve: "发球" };

export function Results({ job }: { job: JobResult }) {
  return (
    <div style={{ padding: 24 }}>
      <h1>分析结果</h1>
      {job.status === "error" && <p style={{ color: "red" }}>出错：{job.message}</p>}
      {job.actions.map(a => (
        <div key={a.action_id} style={{ border: "1px solid #ccc", borderRadius: 8, padding: 12, margin: "12px 0" }}>
          <img src={montageUrl(job.job_id, a.montage_path)} style={{ width: "100%", maxWidth: 720 }} />
          <h3>动作 {a.action_id + 1}：{a.status === "ok" ? TYPE[a.stroke_type!] ?? a.stroke_type
              : a.status === "failed" ? "分析失败" : "待分析"}
            {a.suspected_serve && <span style={{ fontSize: 12, color: "#888" }}>（本地疑似发球）</span>}
          </h3>
          {a.status === "ok" && (
            <>
              <p>总分：<b>{a.overall}</b> / 10</p>
              <p>分项：{Object.entries(a.scores).map(([k, v]) => `${k} ${v}`).join("，")}</p>
              <ul>{a.issues.map((s, i) => <li key={i}>{s}</li>)}</ul>
              <p>建议：{a.advice}</p>
            </>
          )}
          {a.status === "failed" && <pre style={{ whiteSpace: "pre-wrap" }}>{a.raw_reply}</pre>}
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 5: App.tsx 状态机**

```tsx
import { useState } from "react";
import { Uploader } from "./components/Uploader";
import { PlayerPicker } from "./components/PlayerPicker";
import { Progress } from "./components/Progress";
import { Results } from "./components/Results";
import { createJob, streamEvents, getResult, getLoginStatus, login } from "./api";
import { JobResult, ProgressEvent } from "./types";

type Phase = "upload" | "pick" | "progress" | "results";

export default function App() {
  const [phase, setPhase] = useState<Phase>("upload");
  const [file, setFile] = useState<File | null>(null);
  const [jobId, setJobId] = useState("");
  const [ev, setEv] = useState<ProgressEvent | null>(null);
  const [job, setJob] = useState<JobResult | null>(null);

  async function start(cx?: number, cy?: number) {
    if (!(await getLoginStatus())) { alert("通义千问未登录，即将打开浏览器，请先登录"); await login(); return; }
    const id = await createJob(file!, cx, cy);
    setJobId(id); setPhase("progress");
    streamEvents(id, async (e) => {
      setEv(e);
      if (e.stage === "done" || e.stage === "error") {
        setJob(await getResult(id)); setPhase("results");
      }
    });
  }

  if (phase === "upload") return <Uploader onFile={f => { setFile(f); setPhase("pick"); }} />;
  if (phase === "pick") return <PlayerPicker file={file!} onPick={(x, y) => start(x, y)} onSkip={() => start()} />;
  if (phase === "progress") return <Progress ev={ev} />;
  return <Results job={job!} />;
}
```

- [ ] **Step 6: 手动端到端验证**

Run: 后端 `uvicorn app.main:app --port 8000`；前端 `npm run dev`。浏览器打开前端 → 上传一段练球视频 → （点球员或跳过）→ 看进度 → 出结果卡片。
Expected: 完整黄金路径跑通；若某阶段报错，按 message 定位。

- [ ] **Step 7: Commit**

```bash
git add frontend/src
git commit -m "feat: upload, player pick, progress, results UI"
```

---

## Task 18: 端到端验收与收尾

- [ ] **Step 1: 跑全部后端单测**

Run: `cd backend && pytest tests/ -v`
Expected: 纯逻辑测试全部 PASS。

- [ ] **Step 2: 黄金路径手动验收**（用 1 段真实练球视频）
- 上传 → 球员点选/跳过 → 进度推进 → 2~3 张拼贴图生成 → 通义千问自动分析 → 前端展示动作类型/评分/点评。
- 边界：未登录时提示登录；无人物视频给出"未检测到球员"；模糊视频给出"未找到清晰动作"。

- [ ] **Step 3: 写 README（运行说明）**

Create `README.md`：依赖安装（后端 venv、`playwright install chromium`、首次登录通义千问）、启动后端与前端命令、目录说明。

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: setup and run instructions"
```

---

## Self-Review 备注

- **Spec 覆盖**：抽帧(T8)、检测跟踪+姿态(T9)、挥拍峰值(T3/T4)、三帧拼贴(T7)、质量打分(T5)、择优2~3+发球保留(T6)、Playwright 登录(T12)、通义上传抓回复(T13)、JSON 解析(T10)、串行+重试+延时(T13)、SSE 进度(T14/T15)、结果落盘(T2/T14)、前端四屏(T16/T17)、错误提示(T14/T18) 均有对应任务。
- **类型一致性**：`FrameDet/SwingEvent/ActionRecord/JobResult` 在 T1 定义，后续任务字段名一致；`select_best(events,target,gap)`、`score_event(det,ev,w,h,baseline)`、`make_montage(frames,dets,ev,path,w,h)`、`parse_analysis(text)->dict`、`llm_queue.submit(path)` 签名在各任务间对齐。
- **已知降级**：拼贴中文标注改用英文（OpenCV 不支持中文字体），已在 T7 注明；通义选择器为初始猜测，T12 实测回填。
```