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
    peak_idx: int       # 击球帧（速度峰值）
    peak_ts: float
    prep_idx: int       # 准备帧：动作启动（引拍开始）
    load_idx: int       # 蓄力帧：引拍完成、准备击球（prep 与 peak 之间）
    follow_idx: int     # 随挥帧：随挥结束
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
