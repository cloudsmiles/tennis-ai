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
    # 手动模式：围绕用户指定击球时间戳取窗口、按固定偏移出三联帧
    manual_window_before_s: float = 0.9   # 取帧窗口起点（击球前）
    manual_window_after_s: float = 0.6    # 取帧窗口终点（击球后）
    manual_prep_offset_frames: int = 8    # 引拍帧在击球帧前多少帧（15fps≈0.53s）
    manual_follow_offset_frames: int = 6  # 随挥帧在击球帧后多少帧（≈0.4s）
    llm_min_delay_s: float = 2.0
    llm_max_delay_s: float = 5.0
    llm_max_retries: int = 2
    data_dir: Path = BASE_DIR / ".pw-data"  # Playwright 持久用户目录


settings = Settings()
JOBS_DIR.mkdir(parents=True, exist_ok=True)
