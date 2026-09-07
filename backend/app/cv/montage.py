import cv2
import numpy as np
from ..config import settings
from .keyframes import crop_box_for

# OpenCV putText 不支持中文字体，用英文标签（语义：准备/击球/随挥）
LABELS = ["Ready", "Impact", "Follow"]
H = 360  # 统一高度

def _crop_resize(frame, det, w, h):
    x1, y1, x2, y2 = crop_box_for(det, w, h, settings.crop_margin_ratio)
    crop = frame[max(0,y1):y2, max(0,x1):x2]
    if crop.size == 0:
        crop = frame
    scale = H / crop.shape[0]
    return cv2.resize(crop, (max(1, int(crop.shape[1] * scale)), H))

def make_montage(frames, dets, event, out_path, frame_w, frame_h):
    idxs = [event.prep_idx, event.peak_idx, event.follow_idx]
    tiles = []
    for label, idx in zip(LABELS, idxs):
        tile = _crop_resize(frames[idx], dets[idx], frame_w, frame_h)
        cv2.putText(tile, label, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0,255,0), 2)
        tiles.append(tile)
    montage = np.hstack(tiles)
    cv2.imwrite(str(out_path), montage)
