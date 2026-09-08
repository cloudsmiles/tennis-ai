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
    # 手动模式：用户只标动作"大致开始"的时间点，后端在标注点之后的窗口内用速度
    # 峰值定位击球帧，再以击球帧为锚点按固定时长取四帧（见 manual_*_s）。
    manual_before_margin_s: float = 0.7   # 标注点之前的余量（截引拍起点用）
    manual_forward_ground_s: float = 1.7  # 正手/反手前向窗口
    manual_forward_serve_s: float = 3.8   # 发球前向窗口（抛球+举拍+挥击更长）
    # 击球帧搜索范围：只在标注点之后的这段时间内找最强速度峰（避免抓到邻近动作）
    manual_peak_search_ground_s: float = 1.2
    manual_peak_search_serve_s: float = 2.6
    # 以击球帧为锚的四帧时间偏移（秒）：引拍起点 / 随挥结束
    manual_ready_before_ground_s: float = 0.65
    manual_ready_before_serve_s: float = 1.3
    manual_follow_after_ground_s: float = 0.5
    manual_follow_after_serve_s: float = 0.6
    llm_min_delay_s: float = 2.0
    llm_max_delay_s: float = 5.0
    llm_max_retries: int = 2
    data_dir: Path = BASE_DIR / ".pw-data"  # Playwright 持久用户目录
    sources_dir: Path = BASE_DIR / "sources"  # B站等链接下载的源视频


settings = Settings()
JOBS_DIR.mkdir(parents=True, exist_ok=True)
