"""编排一条完整管线：抽帧 → 检测 → 峰值/择优 → 拼贴图 → 通义千问分析。

由 JobManager 的工作线程调用（LLM 浏览器操作经 browser/tongyi 的单工作线程
marshal，见 app/llm/browser.py）。所有失败路径都以 status="error" 的
JobResult 返回（不抛异常），错误信息为中文用户提示。
"""
import numpy as np

from . import storage
from .config import settings
from .cv.detect import Detector
from .cv.frames import extract_frames
from .cv.geometry import box_center, find_peaks, point_speed, smooth
from .cv.keyframes import build_swing_events
from .cv.montage import make_montage
from .cv.quality import score_event
from .cv.select import select_best
from .llm.tongyi import NotLoggedInError, llm_queue
from .schemas import ActionRecord, JobResult

LOGIN_REQUIRED_NOTE = "通义千问未登录，请在浏览器中登录后重试"


def _montageable(event, dets) -> bool:
    """montage/裁剪假定三帧都有人物框：prep/peak/follow 任一缺失即不可用。"""
    return all(
        dets[i].player_box is not None
        for i in (event.prep_idx, event.peak_idx, event.follow_idx)
    )


def run_pipeline(job_id, target_player=None, on_progress=None) -> JobResult:
    """跑完整个分析管线并落盘；失败时返回 status="error" 的结果（不抛异常）。

    on_progress(pct, stage, msg) 在每个阶段回调一次；终端事件（done /
    error / login_required）由调用方（JobManager）在返回后统一补发。
    """
    video = storage.video_path(job_id)
    result = JobResult(job_id=job_id, video_path=video.name, status="running")

    def prog(pct: float, stage: str, msg: str = "") -> None:
        # 同步更新管线内的 result，避免随后的 save_result 把进度回退
        result.progress, result.stage, result.message = pct, stage, msg
        if on_progress:
            on_progress(pct, stage, msg)

    def fail(pct: float, message: str, stage: str = "error"):
        result.status = "error"
        result.progress = pct
        result.stage = stage
        result.message = message
        storage.save_result(result)
        return result

    # 1. 抽帧 ---------------------------------------------------------
    prog(5, "extracting", "抽帧中")
    try:
        frames, ts, w, h = extract_frames(video, settings.extract_fps)
    except ValueError:
        return fail(5, "无法读取视频文件")

    # 2. 检测（模型加载昂贵，只建一次；失败给干净提示） ----------------
    prog(15, "detecting", "检测球员中")
    try:
        detector = Detector()
        dets = detector.detect_frames(frames, ts, target_player)
    except Exception as ex:
        return fail(15, f"检测模型运行失败：{ex}")

    if not any(d.player_box for d in dets):
        return fail(15, "未检测到球员，请更换视频")

    # 3. 速度信号 → 峰值 → 挥拍事件 -----------------------------------
    # 逐帧追踪点：优先球拍中心，缺失回退持拍手腕（可为 None，point_speed 容忍）
    points = [box_center(d.racket_box) if d.racket_box else d.wrist for d in dets]
    speed = smooth(point_speed(points), settings.speed_smooth_window)
    positive = [s for s in speed if s > 0]
    baseline = float(np.median(positive)) if positive else 1.0
    peaks = find_peaks(
        speed, settings.peak_prominence_ratio, settings.speed_smooth_window
    )
    events = build_swing_events(dets, peaks, speed)
    if not events:
        return fail(15, "未找到清晰的挥拍动作，请换一段球员更完整入镜的视频")

    for e in events:
        score_event(dets[e.peak_idx], e, w, h, baseline)

    # 4. 丢弃无法生成拼贴图的事件（三帧任一缺人物框） ------------------
    events = [e for e in events if _montageable(e, dets)]
    if not events:
        return fail(15, "未找到足够清晰的动作")

    best = select_best(events, settings.target_actions, settings.rally_gap_seconds)

    # 5. 拼贴图 --------------------------------------------------------
    prog(55, "montage", "生成关键帧")
    records = []
    for aid, ev in enumerate(best):
        make_montage(frames, dets, ev, storage.montage_path(job_id, aid), w, h)
        records.append(
            ActionRecord(
                action_id=aid,
                peak_ts=ev.peak_ts,
                montage_path=f"montages/action_{aid}.jpg",
                suspected_serve=ev.suspected_serve,
                status="pending",
            )
        )
    result.actions = records
    storage.save_result(result)

    # 6. 通义千问分析（串行队列） --------------------------------------
    total = len(records)
    prog(70, "analyzing", f"大模型分析 0/{total}")
    for rec in records:
        try:
            data = llm_queue.submit(storage.job_dir(job_id) / rec.montage_path)
            rec.status = "ok"
            rec.stroke_type = data["stroke_type"]
            rec.scores = data["scores"]
            rec.overall = data["overall"]
            rec.issues = data["issues"]
            rec.advice = data["advice"]
        except NotLoggedInError:
            # 登录缺失重试无意义：本动作标记失败并终止整个分析阶段
            rec.status = "failed"
            rec.raw_reply = LOGIN_REQUIRED_NOTE
            result.status = "error"
            result.stage = "login_required"
            result.message = LOGIN_REQUIRED_NOTE
            storage.save_result(result)
            return result
        except Exception as ex:
            rec.status = "failed"
            rec.raw_reply = str(ex)  # 单个失败不影响其余动作
        prog(
            70 + 25.0 * (rec.action_id + 1) / total,
            "analyzing",
            f"大模型分析 {rec.action_id + 1}/{total}",
        )
        storage.save_result(result)

    # 7. 完成 ----------------------------------------------------------
    result.status = "done"
    result.progress = 100
    result.stage = "done"
    storage.save_result(result)
    prog(100, "done", "完成")
    return result
