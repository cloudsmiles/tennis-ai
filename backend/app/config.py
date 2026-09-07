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
