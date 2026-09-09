import math

import numpy as np

from ..schemas import FrameDet, SwingEvent
from ..config import settings
from .geometry import box_center


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


def _swing_track_points(dets):
    """挥拍跟踪点：优先拍子——拍头的引拍/随挥幅度（正反手横向过身、发球纵向
    上举下坠）都远大于手腕（手腕被手臂/身体带动，幅度小、过身不明显）。在两种
    点都足够可用（覆盖过半帧）时，取二维摆幅更大的那个（通常是拍心）；拍心漏检
    过半则回退手腕。全程统一用一种点，不逐帧混用（手腕与拍心相差近一米，混用会
    在距离信号上造出假峰值）。"""
    wrist = [d.wrist for d in dets]
    racket = [box_center(d.racket_box) if d.racket_box else None for d in dets]
    need = max(1, int(0.5 * len(dets)))

    def span(pts):
        xs = [p[0] for p in pts if p is not None]
        ys = [p[1] for p in pts if p is not None]
        if len(xs) < need:
            return -1.0
        return math.hypot(max(xs) - min(xs), max(ys) - min(ys))

    return racket if span(racket) > span(wrist) else wrist


def _hitting_height(dets, pts, i):
    """持拍点击中高度的尺度无关特征（归一化 y，越小=点举得越高）。

    优先用持拍手腕：触球瞬间球拍常因运动模糊整段漏检（拍心轨迹在此缺帧），
    但姿态模型仍能看到整条手臂；手腕缺失时退回拍/腕跟踪点。以球员框中心与
    框高归一化，远近不同的画面也可比。
    """
    box = dets[i].player_box
    if box is None:
        return None
    h = max(1.0, box[3] - box[1])
    cy = (box[1] + box[3]) / 2.0
    if dets[i].wrist is not None:
        return (dets[i].wrist[1] - cy) / h
    f = _pose_feat(dets, pts, i)
    return None if f is None else f[1]


def _find_impact(dets, pts, a, b, is_serve):
    """在用户框定的紧区间 [a,b] 内定位击球帧。

    区间已紧贴单个动作（起=引拍/抛球，止=随挥结束），故：
      - 发球：击球点是整个动作里拍子举到最高处（y 最小）的帧；
      - 正反手：前挥段里持拍点（手腕）举到最高、最接近肩部的帧。高机位/侧后
        机位下触球位移沿视线方向，像平面手腕速度在触球瞬间反而≈0（拍在引拍
        和随挥阶段移动更快），拍速峰会落在随挥上；而高度地标稳定：蓄力时拍头
        下沉、触球在挥拍弧顶、收拍包绕虽可能再次抬高，但那已在搜索窗之外。
        搜索窗取区间中段（去掉两端各 20~25%），并给前/后各留足两帧放引拍与
        随挥关键帧。
    """
    n = len(dets)
    a, b = max(0, a), min(n - 1, b)
    if b <= a:
        return min(n - 1, a + 1)
    valid = [i for i in range(a, b + 1)
             if pts[i] is not None and dets[i].player_box is not None]
    if not valid:
        return (a + b) // 2

    if is_serve:
        idx = min(valid, key=lambda i: pts[i][1])  # 拍子最高
        lo_clamp, hi_clamp = a + 4, b - 1
    else:
        lo = int(a + 0.25 * (b - a))
        hi = max(lo, int(b - 0.20 * (b - a)))
        cands = [(hh, i) for i in range(lo, hi + 1)
                 if (hh := _hitting_height(dets, pts, i)) is not None]
        if cands:
            idx = min(cands, key=lambda z: z[0])[1]
        else:
            idx = (a + b) // 2
        # 前面要放 Back+Load 两帧、后面要放 Extend（Follow 固定为 b）
        lo_clamp, hi_clamp = a + 2, b - 2
    return int(min(max(idx, lo_clamp), hi_clamp))


def _pose_feat(dets, pts, i):
    """尺度无关的姿态特征：跟踪点（拍/腕）相对球员框中心的位置，除以框高归一化。
    球员离镜头远近不同也可比较；用来衡量两帧"动作姿态差多少"。"""
    if i >= len(pts):
        return None
    b, p = dets[i].player_box, pts[i]
    if b is None or p is None:
        return None
    h = max(1.0, b[3] - b[1])
    return ((p[0] - (b[0] + b[2]) / 2.0) / h,
            (p[1] - (b[1] + b[3]) / 2.0) / h)


def _pose_dist(dets, pts, i, j):
    """两帧之间的姿态差异（归一化后的拍/腕位置欧氏距离）。"""
    a, c = _pose_feat(dets, pts, i), _pose_feat(dets, pts, j)
    if a is None or c is None:
        return 0.0
    return math.hypot(a[0] - c[0], a[1] - c[1])


def _spread(idxs, zones, fixed, dets, pts, anchor=None, passes=3):
    """在保持阶段顺序与各阶段区间的前提下选帧：对每个可动阶段，在其区间内挑
    "与相邻已选帧姿态差异最大"的帧。于是相邻拼贴帧对应动作差别最大的几个瞬间
    （按姿态选，而非按时间均分）。fixed 帧（用户定的起/止、自动识别的击球）不动。
    并列时取离 anchor（击球帧）最近者。最后保证索引严格递增。"""
    m, n = len(idxs), len(dets)
    if anchor is None:
        anchor = next((idxs[k] for k in range(m) if fixed[k]), idxs[m // 2])
    for _ in range(passes):
        moved = False
        for k in range(m):
            if fixed[k]:
                continue
            lo, hi = zones[k]
            if k > 0:
                lo = max(lo, idxs[k - 1] + 1)
            if k < m - 1:
                hi = min(hi, idxs[k + 1] - 1)
            lo, hi = max(0, lo), min(n - 1, hi)
            cand = [i for i in range(lo, hi + 1)
                    if pts[i] is not None and dets[i].player_box is not None]
            if not cand:
                continue
            nbrs = (([idxs[k - 1]] if k > 0 else [])
                    + ([idxs[k + 1]] if k < m - 1 else []))

            def score(i):
                return min((_pose_dist(dets, pts, i, q) for q in nbrs),
                           default=0.0)

            # 姿态差异最大；并列时取离击球帧最近者——准备取引拍启动前最后一帧、
            # 随挥取拍刚扫到对侧那一帧（而非停在动作平台期的任意一帧）
            best = max(cand, key=lambda i: (score(i), -abs(i - anchor)))
            if best != idxs[k]:
                idxs[k], moved = best, True
        if not moved:
            break
    for k in range(1, m):  # 严格递增兜底
        if idxs[k] <= idxs[k - 1]:
            idxs[k] = min(n - 1, idxs[k - 1] + 1)
    return idxs


def event_frame_specs(event):
    """拼贴帧序列 [(frame_idx, 英文标签), ...]：正反手六帧、发球六帧。

    正反手：Ready 准备 → Back 引拍后摆 → Load 引拍蓄力(顶点) → Impact 击球
    → Extend 随挥前送 → Follow 随挥结束；自动模式（back/extend 为 None）退化为
    四帧。发球：Ready → Toss → Trophy → Drop(蓄力) → Impact → Follow。
    """
    serve = event.toss_idx is not None and event.trophy_idx is not None
    specs = [(event.prep_idx, "Ready")]
    if serve:
        specs.append((event.toss_idx, "Toss"))      # 抛球/起势
        specs.append((event.trophy_idx, "Trophy"))  # 引拍上举
        specs.append((event.load_idx, "Drop"))      # 拍头下坠（蓄力）
    else:
        if event.back_idx is not None:
            specs.append((event.back_idx, "Back"))  # 引拍后摆
        specs.append((event.load_idx, "Load"))      # 引拍蓄力顶点
    specs.append((event.peak_idx, "Impact"))
    if not serve and event.extend_idx is not None:
        specs.append((event.extend_idx, "Extend"))  # 击球后前送（尚未包绕）
    specs.append((event.follow_idx, "Follow"))
    return specs


def manual_event(dets, speed, start_idx, end_idx, stroke_type):
    """手动模式入口：用户框定单个动作的时间范围 [start_idx, end_idx]（起=准备/
    引拍开始，止=随挥结束）。后端在这个紧贴动作的区间内自动找击球帧，再按姿态
    差异选帧——起点固定为准备、终点固定为随挥。正反手与发球都出 6 帧。"""
    n = len(dets)
    a = _nearest_with_player(dets, max(0, min(n - 1, start_idx)))
    b = _nearest_with_player(dets, max(0, min(n - 1, end_idx)))
    if b <= a:  # 区间退化：保证至少能拉开若干帧
        a, b = max(0, a - 2), min(n - 1, b + 3)
        if b <= a:
            b = min(n - 1, a + 1)
    if stroke_type == "serve":
        return _manual_serve_event(dets, speed, a, b)
    return _manual_ground_event(dets, speed, a, b)


def _manual_ground_event(dets, speed, a, b):
    """正反手 6 帧：准备 → 引拍后摆 → 引拍蓄力(顶点) → 击球 → 随挥前送 → 随挥结束。

    区间内按持拍点高度自动找击球（见 _find_impact）；准备固定为区间起点、随挥
    固定为终点。蓄力取 (准备,击球) 内与击球姿态差最大者（引拍顶点/拍头最低），
    后摆种子放在准备与蓄力之间；前送限制在击球后的前半段（手臂充分伸展、拍尚未
    包绕到身体另一侧），故与终点的收拍帧不会重合。最后交 _spread 在各自区间内
    按相邻姿态差异最大化定型，保证六帧严格递增。
    """
    pts = _swing_track_points(dets)
    impact = _find_impact(dets, pts, a, b, is_serve=False)

    def valid(i):
        return pts[i] is not None and dets[i].player_box is not None

    pre = [i for i in range(a + 1, impact) if valid(i)]
    load = max(pre, key=lambda i: _pose_dist(dets, pts, i, impact)) \
        if pre else (a + impact) // 2
    back0 = min(load - 1, a + max(1, (load - a) // 2))
    post_ext = max(1, (b - impact) // 2)   # 前送只在击球后前半段选
    extend0 = impact + max(1, min(post_ext, (b - impact) // 3 or 1))

    ready, back, load, peak, extend, follow = _spread(
        [a, back0, load, impact, extend0, b],
        [(a, a), (a + 1, impact - 2), (a + 1, impact - 1), (impact, impact),
         (impact + 1, impact + post_ext), (b, b)],
        [True, False, False, True, False, True],
        dets, pts, anchor=impact)

    return SwingEvent(
        peak_idx=peak,
        peak_ts=dets[peak].ts,
        prep_idx=ready,
        load_idx=load,
        follow_idx=follow,
        back_idx=back,
        extend_idx=extend,
        max_speed=float(speed[peak]) if peak < len(speed) else 0.0,
        suspected_serve=is_overhead(dets, peak),
    )


def _manual_serve_event(dets, speed, a, b):
    """发球 6 帧。区间内击球=拍子举到最高处；准备固定为起点、随挥固定为终点。
    击球前把区间三等分，在各段按拍高交替极值取 抛球(低)→上举(高)→拍头下坠(低)，
    再用相邻姿态差异最大化定型，顺序 ready<toss<trophy<drop<impact<follow。"""
    n = len(dets)
    pts = _swing_track_points(dets)
    contact = _find_impact(dets, pts, a, b, is_serve=True)

    def valid(i):
        return pts[i] is not None and dets[i].player_box is not None

    def argmin_y(lo, hi, default):
        cs = [i for i in range(lo, hi + 1) if valid(i)]
        return min(cs, key=lambda i: pts[i][1]) if cs else default

    def argmax_y(lo, hi, default):
        cs = [i for i in range(lo, hi + 1) if valid(i)]
        return max(cs, key=lambda i: pts[i][1]) if cs else default

    seg = max(1, contact - a)
    q1, q2 = a + seg // 3, a + 2 * seg // 3
    drop = argmax_y(q2, contact - 1, contact - 1)     # 拍头下坠（低）
    trophy = argmin_y(q1, drop - 1, (a + drop) // 2)  # 引拍上举（高）
    toss = argmax_y(a + 1, trophy - 1, (a + trophy) // 2)  # 抛球/起势（低）

    ready, toss, trophy, drop, peak, follow = _spread(
        [a, toss, trophy, drop, contact, b],
        [(a, a), (a + 1, contact - 3), (a + 1, contact - 2),
         (a + 1, contact - 1), (contact, contact), (b, b)],
        [True, False, False, False, True, True], dets, pts, anchor=contact)

    return SwingEvent(
        peak_idx=peak,
        peak_ts=dets[peak].ts,
        prep_idx=ready,
        load_idx=drop,
        follow_idx=follow,
        toss_idx=toss,
        trophy_idx=trophy,
        max_speed=float(speed[peak]) if peak < len(speed) else 0.0,
        suspected_serve=True,
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
