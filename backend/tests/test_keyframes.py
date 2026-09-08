from app.schemas import FrameDet
from app.cv.keyframes import (
    action_span, build_swing_events, crop_box_for, is_overhead, make_event,
)

def _det(i, ts, pbox, wrist=None, pose_ok=True):
    return FrameDet(frame_idx=i, ts=ts, player_box=pbox, player_conf=0.9,
                    wrist=wrist, pose_ok=pose_ok)

def test_build_swing_events_four_ordered_frames():
    dets = [_det(i, i / 15.0, (10, 10, 100, 300)) for i in range(40)]
    speed = [1.0] * 40; speed[20] = 20.0
    evs = build_swing_events(dets, [20], speed)
    assert len(evs) == 1
    e = evs[0]
    # 四帧按时间顺序：准备 < 蓄力 < 击球(峰) < 随挥
    assert (e.prep_idx < e.load_idx < e.peak_idx < e.follow_idx)
    assert e.peak_idx == 20 and e.max_speed == 20.0

def test_span_covers_full_action():
    # 帧 10~25 为持续明显移动（引拍→击球→随挥），峰值在 20；两端为静止
    speed = [1.0] * 40
    for i in range(10, 26):
        speed[i] = 10.0
    speed[20] = 20.0
    dets = [_det(i, i / 15.0, (10, 10, 100, 300)) for i in range(40)]
    e = make_event(dets, speed, 20, baseline=1.0)
    onset, offset = action_span(speed, 20, 40, 1.0)
    assert onset == 10 and offset == 25      # 完整区间 = 动作启动到随挥结束
    assert e.prep_idx == 10                   # 准备帧取动作启动
    assert e.follow_idx == 26                 # 随挥帧至少峰值后 6 帧（下限保证）
    assert e.prep_idx < e.load_idx < e.peak_idx < e.follow_idx

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
