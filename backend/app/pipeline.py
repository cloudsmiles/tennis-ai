"""编排分析管线：抽帧 → 检测 → 拼贴图 → 通义千问分析。

两种入口：
- 自动模式（hit_ts=None）：抽全片帧 → 检测 → 速度峰值/择优 → 选最好的 2~3 个动作；
- 手动模式（hit_ts 给定）：只抽用户指定击球时间戳附近的一个窗口，检测/跟踪所选
  球员，按固定偏移出 Ready/Impact/Follow 三联帧，动作类型用用户标注的 stroke_type。

由 JobManager 的工作线程调用（LLM 浏览器操作经 browser/tongyi 的单工作线程
marshal，见 app/llm/browser.py）。所有失败路径都以 status="error" 的
JobResult 返回（不抛异常），错误信息为中文用户提示。
"""
import numpy as np

from . import storage
from .config import settings
from .cv.detect import Detector
from .cv.frames import extract_frames, extract_frames_window
from .cv.geometry import box_center, find_peaks, point_speed, smooth
from .cv.keyframes import build_swing_events
from .cv.montage import make_montage
from .cv.quality import score_event
from .cv.select import select_best
from .llm.tongyi import LLMParseError, NotLoggedInError, llm_queue
from .schemas import ActionRecord, JobResult, SwingEvent

LOGIN_REQUIRED_NOTE = "通义千问未登录，请在浏览器中登录后重试"


def _montageable(event, dets) -> bool:
    """montage/裁剪假定三帧都有人物框：prep/peak/follow 任一缺失即不可用。"""
    return all(
        dets[i].player_box is not None
        for i in (event.prep_idx, event.peak_idx, event.follow_idx)
    )


def run_pipeline(job_id, target_player=None, on_progress=None, skip_llm=False,
                 hit_ts=None, stroke_type=None) -> JobResult:
    """跑完分析管线并落盘；失败时返回 status="error" 的结果（不抛异常）。

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

    # 1-4. 取帧 + 检测 + 选出要出图的动作 ------------------------------
    if hit_ts is not None:
        events, frames, dets, w, h = _manual_events(
            video, hit_ts, target_player, prog, fail
        )
    else:
        events, frames, dets, w, h = _auto_events(
            video, target_player, prog, fail
        )
    if events is None:
        return result  # fail() 已把错误结果写入 result

    # 5. 拼贴图 --------------------------------------------------------
    prog(55, "montage", "生成关键帧")
    records = []
    for aid, ev in enumerate(events):
        make_montage(frames, dets, ev, storage.montage_path(job_id, aid), w, h)
        records.append(
            ActionRecord(
                action_id=aid,
                peak_ts=ev.peak_ts,
                montage_path=f"montages/action_{aid}.jpg",
                suspected_serve=ev.suspected_serve,
                status="pending",
                # 手动模式：用户已标注动作类型，直接落库（自动模式为 None）
                stroke_type=stroke_type if hit_ts is not None else None,
            )
        )
    result.actions = records
    storage.save_result(result)

    # 预览模式：只生成动作帧拼贴图，不调用大模型（动作保持 pending）
    if skip_llm:
        result.status = "done"
        result.progress = 100
        result.stage = "done"
        result.message = f"已生成 {len(records)} 张动作帧拼贴图（预览模式，未调用大模型）"
        storage.save_result(result)
        prog(100, "done", result.message)
        return result

    # 6. 通义千问分析（串行队列） --------------------------------------
    total = len(records)
    prog(70, "analyzing", f"大模型分析 0/{total}")
    for rec in records:
        try:
            data = llm_queue.submit(
                storage.job_dir(job_id) / rec.montage_path, rec.stroke_type
            )
            rec.status = "ok"
            # 手动模式已带用户标注的类型，保留之；自动模式才用模型分类结果
            if rec.stroke_type is None:
                rec.stroke_type = data["stroke_type"]
            rec.scores = data["scores"]
            rec.overall = data["overall"]
            rec.issues = data["issues"]
            rec.advice = data["advice"]
        except LLMParseError as ex:
            # 回复无法解析为 JSON（spec §4）：保留模型原文，仅本动作标记
            # parse_failed，其余动作照常分析（不终结任务、不触发登录）
            rec.status = "parse_failed"
            rec.raw_reply = ex.raw
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


def _auto_events(video, target_player, prog, fail):
    """自动模式：全片抽帧 → 检测 → 速度峰值 → 择优。返回 (events, frames, dets, w, h)。

    失败时返回 (None, None, None, None, None)，且 fail() 已把错误写入结果。
    """
    prog(5, "extracting", "抽帧中")
    try:
        frames, ts, w, h = extract_frames(video, settings.extract_fps)
    except ValueError:
        fail(5, "无法读取视频文件")
        return None, None, None, None, None

    prog(15, "detecting", "检测球员中")
    try:
        detector = Detector()
        dets = detector.detect_frames(frames, ts, target_player)
    except Exception as ex:
        fail(15, f"检测模型运行失败：{ex}")
        return None, None, None, None, None

    if not any(d.player_box for d in dets):
        fail(15, "未检测到球员，请更换视频")
        return None, None, None, None, None

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
        fail(15, "未找到清晰的挥拍动作，请换一段球员更完整入镜的视频")
        return None, None, None, None, None

    for e in events:
        score_event(dets[e.peak_idx], e, w, h, baseline)

    # 丢弃无法生成拼贴图的事件（三帧任一缺人物框）
    events = [e for e in events if _montageable(e, dets)]
    if not events:
        fail(15, "未找到足够清晰的动作")
        return None, None, None, None, None

    events = select_best(events, settings.target_actions, settings.rally_gap_seconds)
    return events, frames, dets, w, h


def _manual_events(video, hit_ts, target_player, prog, fail):
    """手动模式：围绕 hit_ts 抽窗口帧 → 检测 → 出单个动作事件。

    不做速度峰值搜索：击球帧取距 hit_ts 最近的帧，引拍/随挥按固定偏移取。
    返回值约定同 _auto_events。
    """
    prog(5, "extracting", "截取动作片段")
    try:
        frames, ts, w, h = extract_frames_window(
            video, settings.extract_fps, hit_ts,
            settings.manual_window_before_s, settings.manual_window_after_s,
        )
    except ValueError:
        fail(5, "无法读取视频文件")
        return None, None, None, None, None

    prog(15, "detecting", "检测球员中")
    try:
        detector = Detector()
        dets = detector.detect_frames(frames, ts, target_player)
    except Exception as ex:
        fail(15, f"检测模型运行失败：{ex}")
        return None, None, None, None, None

    if not any(d.player_box for d in dets):
        fail(15, "该时间点附近未检测到球员，请把进度条拖到球员清晰入镜的击球瞬间")
        return None, None, None, None, None

    peak_idx = min(range(len(dets)), key=lambda i: abs(dets[i].ts - hit_ts))
    prep_idx = max(0, peak_idx - settings.manual_prep_offset_frames)
    follow_idx = min(len(dets) - 1, peak_idx + settings.manual_follow_offset_frames)
    event = SwingEvent(
        peak_idx=peak_idx,
        peak_ts=dets[peak_idx].ts,
        prep_idx=prep_idx,
        follow_idx=follow_idx,
        max_speed=0.0,
        suspected_serve=False,
    )
    if not _montageable(event, dets):
        fail(15, "该时间点附近球员不够清晰，请把进度条拖到球员完整入镜的击球瞬间")
        return None, None, None, None, None

    return [event], frames, dets, w, h
