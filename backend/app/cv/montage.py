import cv2
import numpy as np
from ..config import settings
from .geometry import box_center
from .keyframes import _swing_track_points, crop_box_for, event_frame_specs

# OpenCV putText 不支持中文字体，用英文标签。正反手六帧
# Ready/Back/Load/Impact/Extend/Follow；发球六帧 Ready/Toss/Trophy/Drop/
# Impact/Follow。
H = 360  # 统一高度

GREEN = (0, 200, 0)      # 球员框
ORANGE = (0, 165, 255)   # 球拍框/拍心
BLUE = (255, 80, 0)      # 持拍手腕
RED = (40, 40, 235)      # 实际用于跟踪/选帧的点


def _crop_resize(frame, det, w, h):
    x1, y1, x2, y2 = crop_box_for(det, w, h, settings.crop_margin_ratio)
    crop = frame[max(0, y1):y2, max(0, x1):x2]
    if crop.size == 0:
        crop = frame
    scale = H / crop.shape[0]
    return cv2.resize(crop, (max(1, int(crop.shape[1] * scale)), H))


def make_montage(frames, dets, event, out_path, frame_w, frame_h):
    tiles = []
    for idx, label in event_frame_specs(event):
        tile = _crop_resize(frames[idx], dets[idx], frame_w, frame_h)
        cv2.putText(tile, label, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 2)
        tiles.append(tile)
    montage = np.hstack(tiles)
    cv2.imwrite(str(out_path), montage)


def _draw_detection(frame, det, chosen):
    """在整帧上叠加检测器实际看到的东西：球员框、球拍框/拍心、持拍手腕、
    以及选帧算法实际跟踪的点（红叉）。先在整帧画再按球员框裁剪。"""
    img = frame.copy()
    if det.player_box is not None:
        x1, y1, x2, y2 = (int(v) for v in det.player_box)
        cv2.rectangle(img, (x1, y1), (x2, y2), GREEN, 3)
    if det.racket_box is not None:
        x1, y1, x2, y2 = (int(v) for v in det.racket_box)
        cv2.rectangle(img, (x1, y1), (x2, y2), ORANGE, 3)
        rc = box_center(det.racket_box)
        cv2.circle(img, (int(rc[0]), int(rc[1])), 6, ORANGE, -1)
    if det.wrist is not None:
        cv2.circle(img, (int(det.wrist[0]), int(det.wrist[1])), 8, BLUE, -1)
    if chosen is not None:
        x, y = int(chosen[0]), int(chosen[1])
        cv2.drawMarker(img, (x, y), RED, cv2.MARKER_TILTED_CROSS, 26, 4)
    return img


def make_annotated_montage(frames, dets, event, out_path, frame_w, frame_h):
    """调试版拼贴：与干净版同样的裁剪/标签，但叠加检测标注，便于核对关键帧
    是怎么识别出来的（不发给大模型）。"""
    pts = _swing_track_points(dets)
    tiles = []
    for idx, label in event_frame_specs(event):
        annotated = _draw_detection(frames[idx], dets[idx], pts[idx])
        tile = _crop_resize(annotated, dets[idx], frame_w, frame_h)
        cv2.rectangle(tile, (0, 0), (tile.shape[1] - 1, tile.shape[0] - 1),
                      (60, 60, 60), 1)
        cv2.putText(tile, label, (10, 32),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9, GREEN, 2)
        cv2.putText(tile, f"#{idx} {dets[idx].ts:.2f}s", (10, 56),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 2)
        tiles.append(tile)
    montage = np.hstack(tiles)
    cv2.imwrite(str(out_path), montage)
