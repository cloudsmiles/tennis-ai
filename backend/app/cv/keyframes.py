import numpy as np

from ..schemas import FrameDet, SwingEvent
from ..config import settings


def _baseline(speed):
    positive = [s for s in speed if s > 0]
    return float(np.median(positive)) if positive else 1.0


def action_span(speed, peak_idx, n, baseline):
    """由速度包络确定动作完整区间 (onset, offset)。

    以击球峰值为中心，向两侧扩展到速度回落到阈值之下：左侧 onset 即挥拍/引拍
    启动点，右侧 offset 即随挥结束点。阈值取基线与峰值之间、靠近基线 30% 处，
    既能覆盖引拍与随挥的明显移动，又不把静止漂移算进来。
    """
    peak_s = float(speed[peak_idx]) if peak_idx < len(speed) else 0.0
    thr = baseline + 0.30 * max(0.0, peak_s - baseline)

    onset = peak_idx
    while onset > 0 and onset - 1 < len(speed) and speed[onset - 1] > thr:
        onset -= 1

    offset = peak_idx
    while offset < n - 1 and offset + 1 < len(speed) and speed[offset + 1] > thr:
        offset += 1

    return onset, offset


def make_event(dets, speed, peak_idx, baseline=None):
    """围绕击球峰值帧构造一个四帧动作事件（准备/蓄力/击球/随挥）。

    先由 action_span 得到完整动作区间，再切四帧：准备=动作启动、击球=峰值、
    随挥=动作结束；蓄力取准备与击球的中点。固定偏移仅作为"四帧互不重合"的
    下限保证（包络检测过早/过晚时兜底）。
    """
    n = len(dets)
    if baseline is None:
        baseline = _baseline(speed)
    onset, offset = action_span(speed, peak_idx, n, baseline)

    min_gap = max(settings.prep_min_gap_frames, settings.follow_offset_frames)
    ready = min(onset, max(0, peak_idx - min_gap))
    follow = max(offset, min(n - 1, peak_idx + settings.follow_offset_frames))
    load = (ready + peak_idx) // 2
    if load <= ready:  # 退化情况（ready 与 peak 几乎重合）：夹紧到二者之间
        load = min(peak_idx, ready + 1)

    return SwingEvent(
        peak_idx=peak_idx,
        peak_ts=dets[peak_idx].ts,
        prep_idx=ready,
        load_idx=load,
        follow_idx=follow,
        max_speed=float(speed[peak_idx]) if peak_idx < len(speed) else 0.0,
        suspected_serve=is_overhead(dets, peak_idx),
    )


def build_swing_events(dets, peaks, speed, baseline=None):
    """对每个速度峰值构造一个四帧挥拍事件（自动模式用）。"""
    if baseline is None:
        baseline = _baseline(speed)
    return [make_event(dets, speed, p, baseline) for p in peaks]


def _nearest_with_player(dets, idx):
    """距 idx 最近、且有人物框的帧索引（向两侧扩展查找）。"""
    n = len(dets)
    idx = max(0, min(n - 1, idx))
    if dets[idx].player_box is not None:
        return idx
    for d in range(1, n):
        for j in (idx - d, idx + d):
            if 0 <= j < n and dets[j].player_box is not None:
                return j
    return idx


def manual_event(dets, speed, peak_idx, stroke_type):
    """手动模式：以击球帧 peak_idx 为锚，按固定时长取四帧。

    引拍/随挥位置由"相对击球帧的时间偏移"决定（不依赖包络阈值，避免击球帧因
    运动模糊导致速度信号失真时把动作截短）。ready=击球前 offset、follow=击球后
    offset，load 取二者中点。
    """
    n = len(dets)
    peak_idx = max(0, min(n - 1, peak_idx))
    if stroke_type == "serve":
        ready_before = settings.manual_ready_before_serve_s
        follow_after = settings.manual_follow_after_serve_s
    else:
        ready_before = settings.manual_ready_before_ground_s
        follow_after = settings.manual_follow_after_ground_s
    peak_ts = dets[peak_idx].ts

    def idx_at(ts):
        j = min(range(n), key=lambda i: abs(dets[i].ts - ts))
        return _nearest_with_player(dets, j)

    ready_idx = idx_at(peak_ts - ready_before)
    follow_idx = idx_at(peak_ts + follow_after)
    load_idx = _nearest_with_player(dets, (ready_idx + peak_idx) // 2)

    # 保证严格顺序：ready < load < peak < follow
    ready_idx = min(ready_idx, peak_idx - 2)
    load_idx = min(max(load_idx, ready_idx + 1), peak_idx - 1)
    follow_idx = max(follow_idx, min(n - 1, peak_idx + 2))

    return SwingEvent(
        peak_idx=peak_idx,
        peak_ts=peak_ts,
        prep_idx=ready_idx,
        load_idx=load_idx,
        follow_idx=follow_idx,
        max_speed=float(speed[peak_idx]) if peak_idx < len(speed) else 0.0,
        suspected_serve=is_overhead(dets, peak_idx),
    )


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
