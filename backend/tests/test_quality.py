from app.schemas import FrameDet, SwingEvent
from app.cv.quality import score_event

def _ev():
    return SwingEvent(peak_idx=5, peak_ts=0.3, prep_idx=2, follow_idx=8, max_speed=20.0)

def test_good_clear_player_scores_higher_than_small_edge():
    good = FrameDet(5, 0.3, player_box=(60, 60, 200, 420), player_conf=0.95,
                    racket_box=(90, 200, 130, 260), racket_conf=0.9, wrist=(100, 220), pose_ok=True)
    bad = FrameDet(5, 0.3, player_box=(0, 0, 30, 60), player_conf=0.4,
                   racket_box=None, racket_conf=0.0, wrist=None, pose_ok=False)
    sg = score_event(good, _ev(), 640, 480, baseline_speed=2.0)
    sb = score_event(bad, _ev(), 640, 480, baseline_speed=2.0)
    assert sg > sb and sg > 0.6 and sb < 0.4
