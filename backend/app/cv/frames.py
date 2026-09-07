import cv2
from pathlib import Path

def extract_frames(video_path: Path, fps: float):
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise ValueError(f"cannot open video: {video_path}")
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    step = max(1, round(src_fps / fps))
    frames, ts = [], []
    idx = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if idx % step == 0:
            frames.append(frame)
            ts.append(idx / src_fps)
        idx += 1
    cap.release()
    if not frames:
        raise ValueError("no frames decoded")
    h, w = frames[0].shape[:2]
    return frames, ts, w, h
