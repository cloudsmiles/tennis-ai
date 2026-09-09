from dataclasses import asdict, dataclass, field, fields
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
    peak_idx: int       # 击球帧（速度峰值 / 用户对准的触球帧）
    peak_ts: float
    prep_idx: int       # 准备帧：动作启动（引拍/站位开始）
    load_idx: int       # 蓄力帧：正反手=引拍顶点；发球=拍头下坠最低点
    follow_idx: int     # 随挥帧：随挥结束（拍扫到身体另一侧）
    max_speed: float
    # 发球专属的额外两帧（toss/trophy 非 None 即发球六帧）
    toss_idx: Optional[int] = None    # 抛球/起势帧
    trophy_idx: Optional[int] = None  # 引拍上举（trophy 姿势）帧
    # 正反手六帧专属的额外两帧（与 toss/trophy 互斥；自动模式四帧时为 None）
    back_idx: Optional[int] = None    # 引拍后摆帧（准备→蓄力之间）
    extend_idx: Optional[int] = None  # 击球后前送帧（击球→随挥结束之间）
    quality: float = 0.0
    suspected_serve: bool = False


@dataclass
class ActionRecord:
    action_id: int
    peak_ts: float
    montage_path: str                 # 相对 job 目录的干净拼贴图路径（发给大模型）
    debug_montage_path: Optional[str] = None  # 叠加检测标注的调试版拼贴图
    suspected_serve: bool = False
    status: str = "pending"           # pending|ok|parse_failed|failed
    stroke_type: Optional[str] = None
    # 大模型点评：NTRP 风格评级（2.0~5.0）+ 定级理由 + 优点 + 缺点 + 训练建议
    level: Optional[str] = None
    level_note: str = ""
    strengths: list = field(default_factory=list)
    weaknesses: list = field(default_factory=list)
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
        # 只认当前数据类字段：旧版 result.json 里的 scores/overall/issues 等
        # 已废弃字段会被静默忽略，避免升级后加载历史任务直接报错。
        action_fields = {f.name for f in fields(ActionRecord)}
        acts = [
            ActionRecord(**{k: v for k, v in a.items() if k in action_fields})
            for a in d.pop("actions", [])
        ]
        job_fields = {f.name for f in fields(JobResult)}
        r = JobResult(**{k: v for k, v in d.items() if k in job_fields})
        r.actions = acts
        return r
