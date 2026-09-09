"""一次性探针：区分"单手腕抖动"还是"左右手腕身份逐帧翻转"。

对时间窗内每帧直接跑 pose+det，打印面积最大者（=未点选时锁定的人）的
左手腕(9)/右手腕(10)原始关键点（x,y,conf）、代码实际选用的手腕、所有球拍中心。
并把指定帧范围渲染成左右腕分别标注的联系表。
"""
import sys
from pathlib import Path

import cv2
import numpy as np

from app import storage
from app.config import settings
from app.cv.detect import WRIST_LEFT, WRIST_RIGHT, KP_CONF, Detector, _box_center
from app.cv.frames import extract_frames_window

JOB = sys.argv[1] if len(sys.argv) > 1 else "786ccc373f59"
CENTER = float(sys.argv[2]) if len(sys.argv) > 2 else 8.2
BEFORE = float(sys.argv[3]) if len(sys.argv) > 3 else 1.2
AFTER = float(sys.argv[4]) if len(sys.argv) > 4 else 1.2
LO = int(sys.argv[5]) if len(sys.argv) > 5 else 24
HI = int(sys.argv[6]) if len(sys.argv) > 6 else 38

det = Detector()
frames, ts, w, h = extract_frames_window(
    storage.video_path(JOB), settings.extract_fps, CENTER, BEFORE, AFTER)
print(f"窗口 {CENTER-BEFORE:.2f}~{CENTER+AFTER:.2f}s，共 {len(frames)} 帧")

tiles = []
for i, frame in enumerate(frames):
    pr = det.pose.track(frame, persist=True, classes=[0],
                        device=det.device, verbose=False)[0]
    dr = det.det(frame, classes=[38], device=det.device, verbose=False)[0]
    persons = det._parse_persons(pr)
    rackets = det._parse_rackets(dr)
    if not persons:
        continue
    p = max(persons, key=lambda z: z["area"])
    kp = p["kp"]
    lw = tuple(round(float(v), 1) for v in kp[WRIST_LEFT][:3])
    rw = tuple(round(float(v), 1) for v in kp[WRIST_RIGHT][:3])
    rc = [tuple(round(v, 1) for v in _box_center(r["box"])) for r in rackets]
    chosen = det._pick_wrist(p, det._pick_racket(rackets, p["box"]))
    if LO <= i <= HI:
        print(f"#{i:2d} t={ts[i]:.2f}  L腕={lw}  R腕={rw}  选用={None if chosen is None else tuple(round(v,1) for v in chosen)}  拍={rc}")
        img = frame.copy()
        x1, y1, x2, y2 = (int(v) for v in p["box"])
        cv2.rectangle(img, (x1, y1), (x2, y2), (0, 200, 0), 2)
        if lw[2] > KP_CONF:
            cv2.circle(img, (int(lw[0]), int(lw[1])), 8, (255, 80, 0), -1)  # 左=蓝
            cv2.putText(img, "L", (int(lw[0]) + 8, int(lw[1])),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 80, 0), 2)
        if rw[2] > KP_CONF:
            cv2.circle(img, (int(rw[0]), int(rw[1])), 8, (0, 220, 255), -1)  # 右=黄
            cv2.putText(img, "R", (int(rw[0]) + 8, int(rw[1])),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 220, 255), 2)
        if chosen:
            cv2.drawMarker(img, (int(chosen[0]), int(chosen[1])), (40, 40, 235),
                           cv2.MARKER_TILTED_CROSS, 22, 3)
        for r in rackets:
            rx1, ry1, rx2, ry2 = (int(v) for v in r["box"])
            cv2.rectangle(img, (rx1, ry1), (rx2, ry2), (0, 165, 255), 2)
        # 按人物框裁剪（加边距），让手部标注看得清
        cx1, cy1, cx2, cy2 = (int(v) for v in p["box"])
        bw, bh = cx2 - cx1, cy2 - cy1
        mx, my = int(bw * 0.4), int(bh * 0.25)
        H0, W0 = img.shape[:2]
        img = img[max(0, cy1 - my):min(H0, cy2 + my),
                  max(0, cx1 - mx):min(W0, cx2 + mx)]
        th = 300
        scale = th / img.shape[0]
        t = cv2.resize(img, (int(img.shape[1] * scale), th))
        bar = np.zeros((28, t.shape[1], 3), dtype=np.uint8)
        cv2.putText(bar, f"#{i} t={ts[i]:.2f}", (4, 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
        tiles.append(np.vstack([bar, t]))

if tiles:
    th = tiles[0].shape[0]
    width = max(t.shape[1] for t in tiles)
    norm = []
    for t in tiles:
        if t.shape[1] < width:
            t = np.hstack([t, np.zeros((t.shape[0], width - t.shape[1], 3), np.uint8)])
        norm.append(t)
    rows = []
    for r in range(0, len(norm), 4):
        chunk = list(norm[r:r + 4])
        while len(chunk) < 4:
            chunk.append(np.zeros((th, width, 3), np.uint8))
        rows.append(np.hstack(chunk))
    out = Path("/tmp") / f"probe_{JOB}_wrists.jpg"
    cv2.imwrite(str(out), np.vstack(rows))
    print("联系表：", out)
