import math
from app.cv.geometry import box_center, box_area, dist_to_edge, point_speed, smooth, find_peaks

def test_box_helpers():
    assert box_center((0, 0, 10, 20)) == (5.0, 10.0)
    assert box_area((0, 0, 10, 20)) == 200.0

def test_dist_to_edge_center_is_high():
    assert dist_to_edge((40, 40, 60, 60), 100, 100) > dist_to_edge((0, 0, 20, 20), 100, 100)

def test_point_speed_basic():
    pts = [(0, 0), (3, 4), None, (3, 8)]
    sp = point_speed(pts)
    assert sp[0] == 0.0 and sp[1] == 5.0 and sp[2] == 0.0 and sp[3] == 0.0

def test_smooth_reduces_spike():
    v = [0, 0, 10, 0, 0]
    s = smooth(v, 3)
    assert max(s) < 10

def test_find_peaks_detects_two():
    # 基线 1，两个明显尖峰在 idx 10 和 30
    v = [1.0] * 45
    v[10], v[30] = 10.0, 10.0
    peaks = find_peaks(v, prominence_ratio=3.0, min_gap=5)
    assert 10 in peaks and 30 in peaks

def test_find_peaks_ignores_flat():
    v = [1.0] * 40
    assert find_peaks(v, prominence_ratio=3.0, min_gap=5) == []
