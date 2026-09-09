import math
from typing import Optional

import numpy as np

def box_center(box):
    x1, y1, x2, y2 = box
    return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)

def box_area(box):
    x1, y1, x2, y2 = box
    return max(0.0, x2 - x1) * max(0.0, y2 - y1)

def dist_to_edge(box, w, h):
    x1, y1, x2, y2 = box
    return float(min(x1, y1, w - x2, h - y2)) / max(1.0, min(w, h))

def point_speed(points):
    out = [0.0] * len(points)
    prev = None
    for i, p in enumerate(points):
        if p is not None and prev is not None:
            out[i] = math.dist(p, prev)
        prev = p  # prev 即上一帧（含缺失帧），缺失帧之后的一帧速度记 0
    return out

def smooth(values, window):
    if window <= 1:
        return list(values)
    k = np.ones(window) / window
    pad = window // 2
    padded = np.pad(values, (pad, pad), mode="edge")
    conv = np.convolve(padded, k, mode="valid")
    return list(conv[: len(values)])

def find_peaks(speed, prominence_ratio, min_gap):
    n = len(speed)
    if n < 3:
        return []
    s = np.asarray(speed, dtype=float)
    baseline = np.median(s[s > 0]) if np.any(s > 0) else 0.0
    thr = baseline * prominence_ratio
    cand = [i for i in range(1, n - 1) if s[i] >= s[i - 1] and s[i] >= s[i + 1] and s[i] > thr]
    cand.sort(key=lambda i: -s[i])  # 强峰优先
    picked = []
    for i in cand:
        if all(abs(i - j) >= min_gap for j in picked):
            picked.append(i)
    return sorted(picked)
