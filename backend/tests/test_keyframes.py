from app.schemas import FrameDet
from app.cv.keyframes import build_swing_events, crop_box_for, is_overhead

def _det(i, ts, pbox, wrist=None, pose_ok=True):
    return FrameDet(frame_idx=i, ts=ts, player_box=pbox, player_conf=0.9,
                    wrist=wrist, pose_ok=pose_ok)

def test_build_swing_events_indices():
    dets = [_det(i, i / 15.0, (10, 10, 100, 300)) for i in range(40)]
    speed = [1.0] * 40; speed[20] = 20.0
    evs = build_swing_events(dets, [20], speed)
    assert len(evs) == 1
    e = evs[0]
    assert e.peak_idx == 20 and e.prep_idx < 20 and e.follow_idx > 20 and e.max_speed == 20.0

def test_crop_box_clamped_and_margined():
    det = _det(0, 0, (40, 40, 60, 400))
    x1, y1, x2, y2 = crop_box_for(det, 200, 500, 0.2)
    assert x1 >= 0 and y1 >= 0 and x2 <= 200 and y2 <= 500
    assert (x2 - x1) > 20  # 加了边距比原框宽

def test_overhead_serve_detected():
    # 手腕在画面很高处（y 很小）
    dets = [_det(i, i/15.0, (10, 10, 100, 300), wrist=(50, 30)) for i in range(10)]
    assert is_overhead(dets, 5) is True

def test_overhead_not_when_wrist_low():
    dets = [_det(i, i/15.0, (10, 10, 100, 300), wrist=(50, 250)) for i in range(10)]
    assert is_overhead(dets, 5) is False
