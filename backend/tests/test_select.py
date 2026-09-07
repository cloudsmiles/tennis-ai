from app.schemas import SwingEvent
from app.cv.select import select_best

def _ev(i, ts, q, serve=False):
    return SwingEvent(peak_idx=i, peak_ts=ts, prep_idx=i-3, follow_idx=i+3,
                      max_speed=10, quality=q, suspected_serve=serve)

def test_picks_top_quality_across_rallies():
    # 两个回合（间隔>6s）：回合1 两个动作，回合2 一个动作
    evs = [_ev(10, 1.0, 0.3), _ev(20, 2.0, 0.9), _ev(200, 20.0, 0.8)]
    out = select_best(evs, target=3, gap_seconds=6.0)
    tss = [e.peak_ts for e in out]
    assert 2.0 in tss and 20.0 in tss       # 每回合取最优代表
    assert 1.0 not in tss                    # 回合1 内质量低的被去掉

def test_keeps_a_serve_when_available():
    evs = [_ev(5, 0.5, 0.5, serve=True), _ev(50, 5.0, 0.95), _ev(150, 15.0, 0.9)]
    out = select_best(evs, target=2, gap_seconds=6.0)
    assert any(e.suspected_serve for e in out)
    assert len(out) == 2

def test_respects_target_count():
    evs = [_ev(i, i * 10.0, 0.8) for i in range(1, 6)]
    assert len(select_best(evs, target=3, gap_seconds=6.0)) == 3
