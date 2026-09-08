# 冒烟测试：无真实网球视频，用合成黑帧验证 Detector 不崩溃、类型正确。
# 黑帧下检测不到人/球拍是预期结果——只断言长度与字段类型，不断言检出。
import numpy as np
import pytest

from app.cv.detect import Detector
from app.schemas import FrameDet


@pytest.fixture(scope="module")
def detector():
    return Detector()  # 首次运行会自动下载 yolo11n-pose.pt / yolo11n.pt


def _assert_frame_det(fd, i):
    assert isinstance(fd, FrameDet)
    assert isinstance(fd.frame_idx, int) and fd.frame_idx == i
    assert isinstance(fd.ts, float)
    for box in (fd.player_box, fd.racket_box):
        assert box is None or (
            type(box) is tuple and len(box) == 4
            and all(type(v) is float for v in box))
    assert type(fd.player_conf) is float
    assert type(fd.racket_conf) is float
    assert fd.wrist is None or (
        type(fd.wrist) is tuple and len(fd.wrist) == 2
        and all(type(v) is float for v in fd.wrist))
    assert type(fd.pose_ok) is bool


def test_detect_black_frames(detector):
    frames = [np.zeros((480, 640, 3), dtype=np.uint8) for _ in range(3)]
    ts = [0, 1, 2]
    dets = detector.detect_frames(frames, ts)
    assert isinstance(dets, list) and len(dets) == 3
    for i, fd in enumerate(dets):
        _assert_frame_det(fd, i)


def test_detect_black_frames_with_target_player(detector):
    frames = [np.zeros((480, 640, 3), dtype=np.uint8) for _ in range(3)]
    ts = [0, 1, 2]
    dets = detector.detect_frames(frames, ts, target_player=(320, 240))
    assert isinstance(dets, list) and len(dets) == 3
    for i, fd in enumerate(dets):
        _assert_frame_det(fd, i)
