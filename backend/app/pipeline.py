"""编排分析管线：抽帧 → 检测 → 拼贴图 → 通义千问分析。

两种入口：
- 自动模式（start_ts/end_ts 缺省）：抽全片帧 → 检测 → 速度峰值/择优 → 选最好的 2~3 个动作；
- 手动模式（start_ts/end_ts 给定）：用户用进度条框出单个动作的时间范围
  （起=准备/引拍开始，止=随挥结束），后端在这个紧贴动作的区间内检测/跟踪所选
  球员、自动找击球帧，并按姿态差异选关键帧（正反手/发球均为六帧）；动作类型用
  用户标注。

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
from .cv.keyframes import build_swing_events, event_frame_specs, manual_event
from .cv.montage import make_annotated_montage, make_montage
from .cv.quality import score_event
from .cv.select import select_best
from .llm.tongyi import (
    CaptchaRequiredError,
    LLMParseError,
    NotLoggedInError,
    llm_queue,
)
from .schemas import ActionRecord, JobResult

LOGIN_REQUIRED_NOTE = "通义千问未登录，请先完成登录后重试"
CAPTCHA_REQUIRED_NOTE = (
    "通义千问弹出了滑块安全验证（第三方风控）。请稍后重试，"
    "或在服务器上以有头模式（QW_HEADLESS=0）登录一次后再分析"
)


def _montageable(event, dets) -> bool:
    """montage/裁剪假定所有拼贴帧都有人物框（正反手/发球均六帧），任一缺失即不可用。"""
    return all(
        dets[i].player_box is not None for i, _ in event_frame_specs(event)
    )


def run_pipeline(job_id, target_player=None, on_progress=None, skip_llm=False,
                 start_ts=None, end_ts=None, stroke_type=None,
                 click_ts=None, delete_video=False) -> JobResult:
    """跑完分析管线并落盘；失败时返回 status="error" 的结果（不抛异常）。

    start_ts/end_ts 给定即手动模式：用户用进度条框出单个动作的时间范围
    （起=准备/引拍开始，止=随挥结束），后端在这个紧贴动作的区间内自动找击球帧、
    再按姿态差异选关键帧。click_ts 为用户点选球员时所在的时间戳，用于在该帧
    锁定球员 track id 并全程跟随。on_progress(pct, stage, msg) 在每个阶段回调
    一次；终端事件（done / error / login_required）由调用方（JobManager）在
    返回后统一补发。
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
    if start_ts is not None and end_ts is not None:
        events, frames, dets, w, h = _manual_events(
            video, start_ts, end_ts, stroke_type, target_player, click_ts,
            prog, fail,
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
        # 调试版：叠加球员框/球拍框/手腕/跟踪点，只供前端查看，不发给大模型
        make_annotated_montage(
            frames, dets, ev, storage.annotated_montage_path(job_id, aid), w, h)
        records.append(
            ActionRecord(
                action_id=aid,
                peak_ts=ev.peak_ts,
                montage_path=f"montages/action_{aid}.jpg",
                debug_montage_path=f"montages/action_{aid}_annotated.jpg",
                suspected_serve=ev.suspected_serve,
                status="pending",
                # 手动模式：用户已标注动作类型，直接落库（自动模式为 None）
                stroke_type=stroke_type if start_ts is not None else None,
            )
        )
    result.actions = records
    storage.save_result(result)

    # 抽帧完成后原视频不再被使用（拼贴图/帧均在内存与 montages/ 中）：
    # 本地上传的视频按约定分析完即删，不长期占用磁盘。
    if delete_video:
        storage.delete_video(job_id)

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
            rec.level = data.get("level") or None
            rec.level_note = data.get("level_note", "")
            rec.strengths = data.get("strengths", [])
            rec.weaknesses = data.get("weaknesses", [])
            rec.advice = data.get("advice", "")
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
        except CaptchaRequiredError:
            # 滑块/安全验证：重试只会再次触发，终止并引导用户处理
            rec.status = "failed"
            rec.raw_reply = CAPTCHA_REQUIRED_NOTE
            result.status = "error"
            result.stage = "captcha_required"
            result.message = CAPTCHA_REQUIRED_NOTE
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

        def det_prog(done, total):
            frac = done / max(1, total)
            prog(15 + 35 * frac, "detecting", f"检测球员中 {done}/{total}")

        dets = detector.detect_frames(frames, ts, target_player,
                                      on_progress=det_prog)
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


def _manual_events(video, start_ts, end_ts, stroke_type, target_player,
                   click_ts, prog, fail):
    """手动模式：用户框定单个动作的时间范围 [start_ts, end_ts]（起=准备/引拍开始，
    止=随挥结束）。抽帧窗口取该范围外加少量边距（供球员跟踪/裁剪），检测并在点击
    帧锁定 track id 全程跟随；随后在范围内自动找击球帧、按姿态差异选关键帧
    （正反手/发球均 6 帧，见 keyframes.manual_event）。返回值同 _auto_events。
    """
    if end_ts <= start_ts:
        fail(5, "动作范围无效：结束时间需晚于开始时间")
        return None, None, None, None, None

    margin = settings.manual_window_margin_s
    t0, t1 = start_ts - margin, end_ts + margin
    if click_ts is not None:  # 点选球员的帧若在范围外，一并纳入以便锁定跟踪
        t0 = min(t0, click_ts - 0.3)
        t1 = max(t1, click_ts + 0.3)
    center = (t0 + t1) / 2.0
    prog(5, "extracting", "截取动作片段")
    try:
        frames, ts, w, h = extract_frames_window(
            video, settings.extract_fps, center, center - t0, t1 - center,
        )
    except ValueError:
        fail(5, "无法读取视频文件")
        return None, None, None, None, None

    prog(15, "detecting", "检测球员并截取关键帧")
    try:
        detector = Detector()

        def det_prog(done, total):
            frac = done / max(1, total)
            prog(15 + 35 * frac, "detecting",
                 f"检测球员并截取关键帧 {done}/{total}")

        dets = detector.detect_frames(
            frames, ts, target_player, target_ts=click_ts,
            on_progress=det_prog,
        )
    except Exception as ex:
        fail(15, f"检测模型运行失败：{ex}")
        return None, None, None, None, None

    if not any(d.player_box for d in dets):
        fail(15, "该范围内未检测到球员，请框出球员清晰入镜的动作片段")
        return None, None, None, None, None

    with_player = [i for i, d in enumerate(dets) if d.player_box is not None]
    a = min(with_player, key=lambda i: abs(dets[i].ts - start_ts))
    b = min(with_player, key=lambda i: abs(dets[i].ts - end_ts))
    if b - a < 5:  # 六帧（准备/后摆/蓄力/击球/前送/随挥）需要至少 6 个有效帧
        fail(15, "动作范围太短，请把开始/结束拉得更开一些（覆盖完整引拍到随挥）")
        return None, None, None, None, None

    points = [box_center(d.racket_box) if d.racket_box else d.wrist for d in dets]
    speed = smooth(point_speed(points), settings.speed_smooth_window)

    event = manual_event(dets, speed, a, b, stroke_type)
    if not _montageable(event, dets):
        fail(15, "该片段中球员不够清晰，请框出球员完整入镜的动作片段")
        return None, None, None, None, None

    return [event], frames, dets, w, h
