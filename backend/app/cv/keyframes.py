from ..schemas import FrameDet, SwingEvent
from ..config import settings
from .geometry import box_center

def build_swing_events(dets, peaks, speed):
    events = []
    n = len(dets)
    for p in peaks:
        prep = max(0, p - max(settings.prep_min_gap_frames, settings.follow_offset_frames))
        # 引拍：往回找一个局部低速点
        j = p - 1
        while j > 0 and speed[j] > speed[j - 1] and j > p - 15:
            j -= 1
        prep = max(0, j)
        follow = min(n - 1, p + settings.follow_offset_frames)
        serve = is_overhead(dets, p)
        events.append(SwingEvent(
            peak_idx=p, peak_ts=dets[p].ts, prep_idx=prep, follow_idx=follow,
            max_speed=float(speed[p]), suspected_serve=serve))
    return events

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
