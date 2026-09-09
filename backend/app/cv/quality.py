from .geometry import box_area, dist_to_edge

def _clamp(x): return max(0.0, min(1.0, x))

def score_event(det, ev, frame_w, frame_h, baseline_speed):
    s = 0.0
    s += 0.25 * _clamp(det.player_conf)
    area_ratio = box_area(det.player_box) / float(frame_w * frame_h) if det.player_box else 0.0
    s += 0.25 * _clamp(area_ratio / 0.15)          # 人物占画面 ~15% 视为满分
    if det.player_box:
        s += 0.20 * _clamp(dist_to_edge(det.player_box, frame_w, frame_h) / 0.05)
    s += 0.15 * _clamp(det.racket_conf)
    sharp = (ev.max_speed / baseline_speed) if baseline_speed > 1e-6 else 1.0
    s += 0.10 * _clamp(sharp / 5.0)
    s += 0.05 * (1.0 if det.pose_ok else 0.0)
    ev.quality = _clamp(s)
    return ev.quality
