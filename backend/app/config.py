import os
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
    # 手动模式：用户用进度条框出单个动作的时间范围 [start_ts, end_ts]
    # （起=准备/引拍开始，止=随挥结束）。抽帧窗口取该范围外加这段边距，
    # 供边缘裁剪与球员全程跟踪使用；后端在范围内自动找击球帧、按姿态差异选帧。
    manual_window_margin_s: float = 0.35
    llm_min_delay_s: float = 2.0
    llm_max_delay_s: float = 5.0
    llm_max_retries: int = 2
    data_dir: Path = BASE_DIR / ".pw-data"  # Playwright 持久用户目录
    sources_dir: Path = BASE_DIR / "sources"  # B站等链接下载的源视频
    # 无头浏览器：Linux 部署默认无头；本机调试可设 QW_HEADLESS=0 弹出窗口人工观察。
    # 登录走网页内手机号+验证码，整个浏览器对终端用户不可见（客户无感）。
    headless: bool = os.environ.get("QW_HEADLESS", "1").lower() not in (
        "0",
        "false",
        "no",
    )
    viewport_width: int = 1440
    viewport_height: int = 900


settings = Settings()
JOBS_DIR.mkdir(parents=True, exist_ok=True)
