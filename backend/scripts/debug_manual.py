"""手动选帧排查脚本：把检测器看到的东西画出来，解释关键帧是怎么选出来的。

用法（在 backend/ 下）：
  .venv/bin/python scripts/debug_manual.py JOB_ID --center 8.2 --before 1.6 --after 1.6
  .venv/bin/python scripts/debug_manual.py JOB_ID --start 7.4 --end 9.0 --stroke forehand

输出到 /tmp/debug_JOBID/：
  - sheet.jpg      时间窗内每一帧的联系表（人物框/球拍框/手腕点/实际跟踪点 + 帧号/时间/步长）
  - keyframes.jpg  复算选中的关键帧拼贴（带同样标注；仅在给了 --start/--end 时）
终端打印：跟踪点来源（拍/腕）、各自覆盖率与摆幅、逐帧表、击球帧定位依据、
选中帧之间的姿态距离。
"""
import argparse
import math
from pathlib import Path

import cv2
import numpy as np

from app import storage
from app.config import settings
from app.cv.detect import Detector
from app.cv.frames import extract_frames_window
from app.cv.geometry import box_center
from app.cv.keyframes import (
    _find_impact,
    _pose_dist,
    _swing_track_points,
    crop_box_for,
    event_frame_specs,
    manual_event,
)

GREEN = (0, 200, 0)
ORANGE = (0, 165, 255)
BLUE = (255, 80, 0)
RED = (40, 40, 235)
WHITE = (255, 255, 255)

PHASE_COLORS = {
    "Ready": (0, 200, 0),
    "Load": (0, 200, 230),
    "Drop": (0, 200, 230),
    "Toss": (200, 120, 0),
    "Trophy": (200, 0, 200),
    "Impact": (40, 40, 235),
    "Follow": (0, 80, 0),
}

THUMB_H = 220


def draw_full(frame, det, chosen_pt):
    """在整帧上叠加检测标注，返回新图。"""
    img = frame.copy()
    if det.player_box is not None:
        x1, y1, x2, y2 = (int(v) for v in det.player_box)
        cv2.rectangle(img, (x1, y1), (x2, y2), GREEN, 2)
    if det.racket_box is not None:
        x1, y1, x2, y2 = (int(v) for v in det.racket_box)
        cv2.rectangle(img, (x1, y1), (x2, y2), ORANGE, 2)
        rc = box_center(det.racket_box)
        cv2.circle(img, (int(rc[0]), int(rc[1])), 4, ORANGE, -1)
    if det.wrist is not None:
        cv2.circle(img, (int(det.wrist[0]), int(det.wrist[1])), 5, BLUE, -1)
    if chosen_pt is not None:
        x, y = int(chosen_pt[0]), int(chosen_pt[1])
        cv2.circle(img, (x, y), 11, RED, 2)
        cv2.drawMarker(img, (x, y), RED, cv2.MARKER_CROSS, 16, 2)
    return img


def crop_tile(frame, det, w, h, height=THUMB_H):
    box = crop_box_for(det, w, h, settings.crop_margin_ratio)
    x1, y1, x2, y2 = box
    crop = frame[max(0, y1):y2, max(0, x1):x2]
    if crop.size == 0:
        crop = frame
    scale = height / crop.shape[0]
    return cv2.resize(crop, (max(1, int(crop.shape[1] * scale)), height))


def step_series(pts):
    n = len(pts)
    xs = np.array([p[0] if p else np.nan for p in pts])
    ys = np.array([p[1] if p else np.nan for p in pts])
    hv = np.where(~np.isnan(xs))[0]
    if len(hv) < 2:
        return np.zeros(n - 1)
    xi = np.interp(np.arange(n), hv, xs[hv])
    yi = np.interp(np.arange(n), hv, ys[hv])
    return np.hypot(np.diff(xi), np.diff(yi))


def coverage_report(dets, pts):
    n = len(dets)
    wrist = [d.wrist for d in dets]
    racket = [box_center(d.racket_box) if d.racket_box else None for d in dets]
    w_cov = sum(p is not None for p in wrist) / n
    r_cov = sum(p is not None for p in racket) / n

    def span(pp):
        xs = [p[0] for p in pp if p]
        ys = [p[1] for p in pp if p]
        return math.hypot(max(xs) - min(xs), max(ys) - min(ys)) if xs else -1.0

    chosen = "拍心" if pts is racket else ("手腕" if pts is wrist else "?")
    print(f"跟踪点来源：{chosen}  | 球拍覆盖率 {r_cov:.0%}、摆幅 {span(racket):.0f}px"
          f"  | 手腕覆盖率 {w_cov:.0%}、摆幅 {span(wrist):.0f}px")
    return chosen


def print_table(dets, pts, steps, a, b, impact):
    print(f"\n逐帧表（动作范围 a={a} b={b}，步长单位 px/帧）：")
    print(" idx    ts   P R |   wrist    racketC    chosen  step | 备注")
    for i, d in enumerate(dets):
        if i < a - 1 or i > b + 1:
            continue
        w = f"{d.wrist[0]:4.0f},{d.wrist[1]:4.0f}" if d.wrist else "   --    "
        rc = box_center(d.racket_box) if d.racket_box else None
        r = f"{rc[0]:4.0f},{rc[1]:4.0f}" if rc else "   --    "
        c = f"{pts[i][0]:4.0f},{pts[i][1]:4.0f}" if pts[i] else "   --    "
        step = f"{steps[i - 1]:5.1f}" if 0 < i < len(steps) + 1 else "  -- "
        note = ""
        if i == a:
            note += " <- 开始(Ready)"
        if i == impact:
            note += " <- 击球(Impact)"
        if i == b:
            note += " <- 结束(Follow)"
        print(f" {i:3d} {d.ts:5.2f}  {'P' if d.player_box else '·'} "
              f"{'R' if d.racket_box else '·'} | {w}  {r}  {c} {step} |{note}")


def make_sheet(frames, dets, pts, steps, w, h, out, selected=None):
    """整段联系表：每帧缩略图 + 帧号/时间/步长条；选中帧彩色边框。"""
    selected = selected or {}
    tiles = []
    vmax = float(np.percentile(steps, 95)) if len(steps) else 1.0
    vmax = max(vmax, 1.0)
    for i, d in enumerate(dets):
        annotated = draw_full(frames[i], d, pts[i])
        tile = crop_tile(annotated, d, w, h) if d.player_box else \
            cv2.resize(annotated, (int(annotated.shape[1] * THUMB_H / annotated.shape[0]), THUMB_H))
        bar_h = 26
        bar = np.zeros((bar_h, tile.shape[1], 3), dtype=np.uint8)
        bar[:] = (30, 30, 30)
        cv2.putText(bar, f"#{i} t={d.ts:.2f}", (4, 18),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, WHITE, 1)
        frac = float(steps[i - 1]) / vmax if 0 < i < len(steps) + 1 else 0.0
        if frac > 0:
            bw = int(min(1.0, frac) * (tile.shape[1] - 4))
            col = RED if (0 < i < len(steps) + 1 and steps[i - 1] >= vmax * 0.8) else (0, 200, 230)
            cv2.rectangle(bar, (2, 21), (2 + bw, 24), col, -1)
        tile = np.vstack([bar, tile])
        if i in selected:
            cv2.rectangle(tile, (0, 0), (tile.shape[1] - 1, tile.shape[0] - 1),
                          PHASE_COLORS.get(selected[i], RED), 4)
            cv2.putText(tile, selected[i], (8, 52),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8,
                        PHASE_COLORS.get(selected[i], RED), 2)
        tiles.append(tile)
    cols = 6
    width = max(t.shape[1] for t in tiles)
    padded = []
    for t in tiles:
        if t.shape[1] < width:
            pad = np.zeros((t.shape[0], width - t.shape[1], 3), dtype=np.uint8)
            t = np.hstack([t, pad])
        padded.append(t)
    rows = []
    for r0 in range(0, len(padded), cols):
        chunk = padded[r0:r0 + cols]
        while len(chunk) < cols:
            chunk.append(np.zeros_like(padded[0]))
        rows.append(np.hstack(chunk))
    sheet = np.vstack(rows)
    cv2.imwrite(str(out), sheet)
    print(f"联系表已写出：{out}")


def make_keyframe_strip(frames, dets, event, pts, w, h, out):
    tiles = []
    order = event_frame_specs(event)
    for idx, label in order:
        annotated = draw_full(frames[idx], dets[idx], pts[idx])
        tile = crop_tile(annotated, dets[idx], w, h, height=360)
        cv2.putText(tile, f"{label} #{idx} t={dets[idx].ts:.2f}",
                    (8, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.8,
                    PHASE_COLORS.get(label, GREEN), 2)
        tiles.append(tile)
    cv2.imwrite(str(out), np.hstack(tiles))
    print(f"关键帧拼贴已写出：{out}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("job_id")
    ap.add_argument("--center", type=float)
    ap.add_argument("--before", type=float, default=1.6)
    ap.add_argument("--after", type=float, default=1.6)
    ap.add_argument("--start", type=float)
    ap.add_argument("--end", type=float)
    ap.add_argument("--stroke", default="forehand")
    ap.add_argument("--click-ts", type=float, default=None)
    args = ap.parse_args()

    if args.start is not None and args.end is not None:
        center = (args.start + args.end) / 2
        before = center - (args.start - settings.manual_window_margin_s)
        after = args.end + settings.manual_window_margin_s - center
    else:
        center = args.center
        before, after = args.before, args.after
    if center is None:
        ap.error("需要 --start/--end 或 --center")

    outdir = Path("/tmp") / f"debug_{args.job_id}"
    outdir.mkdir(parents=True, exist_ok=True)

    video = storage.video_path(args.job_id)
    frames, ts, w, h = extract_frames_window(
        video, settings.extract_fps, center, before, after)
    print(f"抽帧 {len(frames)} 帧，窗口 {center - before:.2f}~{center + after:.2f}s")

    dets = Detector().detect_frames(
        frames, ts, target_player=None, target_ts=args.click_ts)

    pts = _swing_track_points(dets)
    coverage_report(dets, pts)
    steps = step_series(pts)

    with_player = [i for i, d in enumerate(dets) if d.player_box is not None]
    selected = {}
    event = None
    if args.start is not None and args.end is not None:
        a = min(with_player, key=lambda i: abs(dets[i].ts - args.start))
        b = min(with_player, key=lambda i: abs(dets[i].ts - args.end))
        is_serve = args.stroke == "serve"
        impact = _find_impact(dets, pts, a, b, is_serve)
        print(f"\n范围映射 a={a}(t={dets[a].ts:.2f}) b={b}(t={dets[b].ts:.2f})")
        if is_serve:
            ys = [(i, pts[i][1]) for i in range(a, b + 1) if pts[i]]
            top = min(ys, key=lambda z: z[1])
            print(f"发球击球=窗口内拍最高点 #{top[0]} t={dets[top[0]].ts:.2f}，"
                  f"最终 impact={impact} t={dets[impact].ts:.2f}")
        else:
            from app.cv.keyframes import _hitting_height
            lo = int(a + 0.25 * (b - a))
            hi = max(lo, int(b - 0.20 * (b - a)))
            hs = [(i, _hitting_height(dets, pts, i))
                  for i in range(lo, hi + 1)]
            hs = [(i, v) for i, v in hs if v is not None]
            top = min(hs, key=lambda z: z[1])
            print(f"正反手击球：中段 #{lo}..#{hi} 内持拍点归一化高度最小"
                  f"（点最高）在 #{top[0]} t={dets[top[0]].ts:.2f}"
                  f"（h={top[1]:.3f}），最终 impact={impact} "
                  f"t={dets[impact].ts:.2f}")
        event = manual_event(dets, [0.0] * len(dets), a, b, args.stroke)
        for idx, label in event_frame_specs(event):
            selected[idx] = label
        print("\n选中关键帧：")
        order = event_frame_specs(event)
        for (i, lab), (j, lab2) in zip(order, order[1:]):
            dd = _pose_dist(dets, pts, i, j)
            print(f"  {lab:6s} #{i:3d} t={dets[i].ts:.2f}  ->  "
                  f"{lab2:6s} #{j:3d} t={dets[j].ts:.2f}   姿态距离 {dd:.3f}")
        impact = event.peak_idx
        print_table(dets, pts, steps, a, b, impact)
        make_keyframe_strip(frames, dets, event, pts, w, h,
                            outdir / "keyframes.jpg")
    else:
        print_table(dets, pts, steps, with_player[0], with_player[-1], -1)

    make_sheet(frames, dets, pts, steps, w, h, outdir / "sheet.jpg", selected)


if __name__ == "__main__":
    main()
