import numpy as np
from pathlib import Path
from app.schemas import FrameDet, SwingEvent
from app.cv.montage import make_annotated_montage, make_montage

def test_montage_written(tmp_path):
    frames = [np.zeros((480, 640, 3), dtype=np.uint8) for _ in range(20)]
    dets = [FrameDet(i, i/15.0, player_box=(100, 60, 300, 440), player_conf=0.9, pose_ok=True)
            for i in range(20)]
    ev = SwingEvent(peak_idx=10, peak_ts=0.6, prep_idx=4, load_idx=7,
                    follow_idx=15, max_speed=10)
    out = tmp_path / "m.jpg"
    make_montage(frames, dets, ev, out, 640, 480)
    assert out.exists() and out.stat().st_size > 0


def test_annotated_montage_written(tmp_path):
    frames = [np.zeros((480, 640, 3), dtype=np.uint8) for _ in range(20)]
    dets = [FrameDet(i, i / 15.0, player_box=(100, 60, 300, 440), player_conf=0.9,
                     wrist=(180.0, 200.0), racket_box=(160, 170, 220, 240),
                     pose_ok=True)
            for i in range(20)]
    ev = SwingEvent(peak_idx=10, peak_ts=0.6, prep_idx=4, back_idx=6, load_idx=8,
                    extend_idx=13, follow_idx=15, max_speed=10)
    out = tmp_path / "m_debug.jpg"
    make_annotated_montage(frames, dets, ev, out, 640, 480)
    assert out.exists() and out.stat().st_size > 0
