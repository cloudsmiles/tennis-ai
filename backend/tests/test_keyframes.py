import numpy as np

from app.schemas import FrameDet
from app.cv.geometry import box_center, point_speed, smooth
from app.cv.keyframes import (
    _pose_dist, _swing_track_points, action_span, build_swing_events,
    crop_box_for, event_frame_specs, is_overhead, make_event, manual_event,
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

def _sweep(waypoints, n, fps=15.0):
    """按关键帧折线 [(frame, (x, y)), ...] 生成逐帧手腕轨迹、dets 与 speed。"""
    ks = [k for k, _ in waypoints]
    xs = np.interp(np.arange(n), ks, [p[0] for _, p in waypoints])
    ys = np.interp(np.arange(n), ks, [p[1] for _, p in waypoints])
    pts = [(float(xs[i]), float(ys[i])) for i in range(n)]
    dets = [_det(i, i / fps, (10, 10, 110, 310), wrist=pts[i]) for i in range(n)]
    speed = smooth(point_speed(pts), 5)
    return dets, speed, pts


def test_manual_forehand_six_frames_and_impact_is_highest_point():
    # 用户框出单个正手的范围 [20,42]（起=准备，止=随挥扫到对侧之后），出六帧：
    # 准备 → 引拍后摆 → 引拍顶点(蓄力) → 击球 → 随挥前送 → 随挥结束。
    n, contact, start, end = 60, 30, 20, 42
    # 关键：这个机位下触球瞬间手腕几乎只有纵向微小位移（29→30 仅 ~21px），
    # 而随挥前送横移巨大（30→34）、引拍上举也快——旧的"像平面最大步长"会把
    # 击球误判到 31。击球帧的可靠地标是前挥段里持拍点的最高点（归一化 y 最小）：
    # 蓄力时拍头下沉(y260)，触球在最高处(y150)，收拍上肩(y160) 虽也高但落在
    # 中段搜索窗之外（37 以后），不会顶替。
    way = [(0, (210, 210)), (20, (210, 210)), (23, (300, 240)),
           (26, (320, 260)), (29, (300, 170)), (contact, (295, 150)),
           (34, (90, 180)), (38, (40, 160)), (n - 1, (40, 160))]
    dets, speed, pts = _sweep(way, n)
    e = manual_event(dets, speed, start, end, "forehand")
    assert e.peak_idx == contact  # 最高点=触球，而非横移最大的随挥帧
    assert e.toss_idx is None and e.trophy_idx is None
    assert e.back_idx is not None and e.extend_idx is not None
    labels = [lab for _, lab in event_frame_specs(e)]
    assert labels == ["Ready", "Back", "Load", "Impact", "Extend", "Follow"]
    # 准备固定为范围起点、随挥固定为终点，六帧严格有序
    assert e.prep_idx == start and e.follow_idx == end
    assert (e.prep_idx < e.back_idx < e.load_idx < e.peak_idx
            < e.extend_idx < e.follow_idx)
    assert abs(e.load_idx - 26) <= 1  # 蓄力≈引拍顶点（拍头最低处）
    # 核心物理约束：蓄力在击球点一侧、随挥必然在另一侧（拍扫过身体）
    assert pts[e.load_idx][0] > pts[contact][0]
    assert pts[e.follow_idx][0] < pts[contact][0]


def test_manual_serve_splits_six_phases_by_height():
    # 用户框出单个发球范围 [18,55]。纵向为主（手腕 y：越小=举得越高），六阶段：
    # 站位(y210) → 抛球下摆(y275) → trophy 引拍上举(y150) → 拍头下坠(y305,蓄力)
    #   → 击球在头顶最高(y80) → 随挥从上往下扫、横越到对侧(y340, x120)。
    n, contact, start, end = 80, 40, 18, 55
    way = [(0, (150, 210)), (18, (150, 210)), (22, (160, 275)),
           (30, (150, 150)), (36, (165, 305)), (contact, (150, 80)),
           (50, (120, 340)), (n - 1, (120, 340))]
    dets, speed, pts = _sweep(way, n)
    e = manual_event(dets, speed, start, end, "serve")
    assert e.toss_idx is not None and e.trophy_idx is not None
    assert len(event_frame_specs(e)) == 6   # 发球六帧
    assert e.peak_idx == contact            # 范围内拍子最高点即击球
    # 准备/随挥钉在用户框的起/止
    assert e.prep_idx == start and e.follow_idx == end
    # 严格顺序：准备 < 抛球 < trophy < 拍头下坠(蓄力) < 击球 < 随挥
    assert (e.prep_idx < e.toss_idx < e.trophy_idx < e.load_idx
            < e.peak_idx < e.follow_idx)
    # trophy 是上举高点、蓄力(拍头下坠)在其后且明显更低
    assert pts[e.trophy_idx][1] < pts[e.load_idx][1]
    assert abs(e.load_idx - 36) <= 1
    # 击球是整个挥拍的最高点（比 trophy 还高）
    assert pts[e.peak_idx][1] < pts[e.trophy_idx][1]
    # 抛球下摆早于、且低于 trophy
    assert pts[e.toss_idx][1] > pts[e.trophy_idx][1]
    # 随挥：从上往下大幅扫，并横越身体到对侧
    assert pts[e.follow_idx][1] - pts[e.peak_idx][1] > 150
    assert pts[e.follow_idx][0] <= pts[e.peak_idx][0]


def _racket_dets(n, fps, body, rack_wp, wrist_wp):
    """据拍心/手腕折线生成带 racket_box 的逐帧 dets（拍心折线点为框中心）。"""
    def build(wp):
        ks = [k for k, _ in wp]
        xs = np.interp(np.arange(n), ks, [p[0] for _, p in wp])
        ys = np.interp(np.arange(n), ks, [p[1] for _, p in wp])
        return xs, ys

    rx, ry = build(rack_wp)
    wx, wy = build(wrist_wp)
    dets = []
    for i in range(n):
        rcx, rcy = float(rx[i]), float(ry[i])
        dets.append(FrameDet(
            frame_idx=i, ts=i / fps, player_box=body, player_conf=0.9,
            wrist=(float(wx[i]), float(wy[i])),
            racket_box=(rcx - 8, rcy - 14, rcx + 8, rcy + 14), pose_ok=True))
    return dets, [(float(wx[i]), float(wy[i])) for i in range(n)]


def test_manual_groundstroke_follow_uses_racket_wrap_across_body():
    # 正反手随挥按**球拍**判定：手腕几乎贴身体（小摆幅），拍头引拍到身体一侧、
    # 随挥前送后包绕到另一侧。身体中线 x=200；据拍心在范围 [20,46] 内选六帧。
    fps = 15.0
    n, contact, start, end = 60, 30, 20, 46
    body = (130, 60, 270, 360)  # cx=200
    # 击球定位按持拍手腕高度（中段最高=触球）；选帧按拍心姿态差异。
    # 36=前送充分伸展（仍在击球侧前方），42 起包绕到另一侧。
    rack_wp = [(0, (205, 200)), (20, (205, 200)), (25, (300, 190)),
               (29, (260, 185)), (contact, (200, 150)),
               (36, (150, 155)), (42, (120, 190)), (n - 1, (120, 190))]
    wrist_wp = [(0, (200, 210)), (25, (215, 205)), (contact, (200, 180)),
                (42, (185, 205)), (n - 1, (185, 205))]
    dets, wp = _racket_dets(n, fps, body, rack_wp, wrist_wp)
    speed = smooth(point_speed(wp), 5)
    e = manual_event(dets, speed, start, end, "forehand")
    rc = lambda i: box_center(dets[i].racket_box)
    body_cx = (body[0] + body[2]) / 2.0
    assert e.peak_idx == contact
    labels = [lab for _, lab in event_frame_specs(e)]
    assert labels == ["Ready", "Back", "Load", "Impact", "Extend", "Follow"]
    assert e.prep_idx == start and e.follow_idx == end
    assert (e.prep_idx < e.back_idx < e.load_idx < e.peak_idx
            < e.extend_idx < e.follow_idx)
    assert abs(e.load_idx - 25) <= 1
    # 蓄力拍在持拍侧、随挥拍包绕到另一侧（按球拍，而非几乎不动的手腕）
    assert rc(e.load_idx)[0] > body_cx + 40
    assert rc(e.follow_idx)[0] < body_cx - 40
    # 相邻拼贴帧姿态差异明显（归一化拍/腕位置距离），而非时间上挤在一起
    pts = _swing_track_points(dets)
    assert _pose_dist(dets, pts, e.prep_idx, e.back_idx) > 0.12
    assert _pose_dist(dets, pts, e.back_idx, e.load_idx) > 0.10
    assert _pose_dist(dets, pts, e.load_idx, e.peak_idx) > 0.30
    assert _pose_dist(dets, pts, e.peak_idx, e.extend_idx) > 0.14
    assert _pose_dist(dets, pts, e.extend_idx, e.follow_idx) > 0.12


def test_manual_serve_prefers_racket_and_follow_crosses_body():
    # 发球：拍头上下幅度远大于手腕（肘高抬、手腕只小幅下沉），据拍心定位六帧。
    # 身体中线 x=200（球员框 130~270）。击球前拍在持拍侧(x>200)，随挥扫到左侧
    # (x<200) 并下到最低。范围 [18,55]，击球=范围内拍最高点。
    fps = 15.0
    n, contact, start, end = 80, 40, 18, 55
    body = (130, 10, 270, 380)  # cx=200
    wrist_wp = [(0, (200, 190)), (30, (205, 180)), (36, (215, 200)),
                (contact, (202, 120)), (50, (180, 210)), (n - 1, (180, 210))]
    rack_wp = [(0, (200, 250)), (22, (205, 275)), (30, (210, 120)),
               (36, (225, 320)), (contact, (205, 60)), (50, (160, 340)),
               (n - 1, (160, 340))]
    dets, wp = _racket_dets(n, fps, body, rack_wp, wrist_wp)
    speed = smooth(point_speed(wp), 5)
    e = manual_event(dets, speed, start, end, "serve")
    assert len(event_frame_specs(e)) == 6
    assert e.peak_idx == contact
    assert e.prep_idx == start and e.follow_idx == end
    assert (e.prep_idx < e.toss_idx < e.trophy_idx < e.load_idx
            < e.peak_idx < e.follow_idx)
    rc = lambda i: box_center(dets[i].racket_box)
    body_cx = (body[0] + body[2]) / 2.0
    assert rc(e.peak_idx)[1] < rc(e.trophy_idx)[1]     # 击球点比 trophy 还高
    assert rc(e.load_idx)[1] > rc(e.trophy_idx)[1]     # 蓄力=拍头下坠，远低于上举
    assert abs(e.load_idx - 36) <= 1
    assert rc(e.follow_idx)[1] - rc(e.peak_idx)[1] > 150  # 随挥大幅下扫
    # 核心：击球前拍在持拍侧（身体中线一侧），随挥拍已转到另一侧
    assert rc(e.trophy_idx)[0] > body_cx
    assert rc(e.follow_idx)[0] < body_cx


def test_manual_event_static_track_keeps_user_endpoints_ordered():
    # 跟踪点几乎不动（没捕捉到挥拍）：范围端点仍被尊重，六帧严格有序、击球落范围内，
    # 不崩溃也不越界——准备/随挥就是用户框的起/止，无需固定时间兜底。
    fps = 15.0
    n, start, end = 60, 10, 40
    dets = [_det(i, i / fps, (10, 10, 110, 310), wrist=(100.0, 200.0))
            for i in range(n)]
    speed = [1.0] * n
    e = manual_event(dets, speed, start, end, "forehand")
    assert e.prep_idx == start and e.follow_idx == end
    assert (start < e.back_idx < e.load_idx < e.peak_idx
            < e.extend_idx < end)
    assert len(event_frame_specs(e)) == 6
