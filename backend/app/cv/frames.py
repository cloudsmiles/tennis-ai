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


def extract_frames_window(video_path: Path, fps: float, center_ts: float,
                          before_s: float, after_s: float):
    """只抽取 [center_ts-before_s, center_ts+after_s] 时间窗内的帧（手动模式）。

    与 extract_frames 同样按 src_fps/fps 步长抽样，时间戳为相对视频起点的
    绝对秒数（窗口帧与全片帧同分辨率，前端点选坐标可直接复用）。
    """
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise ValueError(f"cannot open video: {video_path}")
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    step = max(1, round(src_fps / fps))
    start_t = max(0.0, center_ts - before_s)
    end_t = center_ts + after_s
    start_frame = int(start_t * src_fps)
    cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
    frames, ts = [], []
    i = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        global_idx = start_frame + i
        t = global_idx / src_fps
        if t > end_t:
            break
        if global_idx % step == 0:
            frames.append(frame)
            ts.append(t)
        i += 1
    cap.release()
    if not frames:
        raise ValueError("no frames decoded in window")
    h, w = frames[0].shape[:2]
    return frames, ts, w, h
