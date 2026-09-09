# 回归：持拍臂身份必须在整段内锁定，不能在左右手腕之间逐帧翻转。
#
# 真实事故（左手持拍球员的正手）：击球瞬间运动模糊导致球拍整段漏检，代码在
# "无球拍时取更低的那只手腕"，而击球瞬间两手几乎等高，关键点轻微一抖就把选点
# 在左右臂之间横跳 ~40px，造出假速度尖峰、带偏击球帧与蓄力帧。修复：先用"有
# 球拍"的帧投票判定持拍臂，其后即便球拍漏检也始终跟同一只手腕。
#
# 不加载 YOLO：object.__new__ 绕过 __init__，直接测纯函数式的判定/选腕方法。
import numpy as np

from app.cv.detect import WRIST_LEFT, WRIST_RIGHT, Detector


def _person(lw, rw, box=(0, 0, 100, 300)):
    kp = np.zeros((17, 3), dtype=np.float32)
    kp[WRIST_LEFT] = (*lw, 0.9)
    kp[WRIST_RIGHT] = (*rw, 0.9)
    return {"box": box, "kp": kp}


def _racket(cx, cy, half=12):
    return {"box": (cx - half, cy - half, cx + half, cy + half), "conf": 0.8}


def _detector():
    return object.__new__(Detector)


def test_racket_frames_vote_for_actual_hitting_arm():
    d = _detector()
    # 左手持拍：球拍框中心始终贴着左手腕，右手在胸口（远）
    chosen = [
        (_person((40, 200), (75, 210)), _racket(48, 198)),
        (_person((44, 196), (74, 206)), _racket(50, 194)),
        (_person((38, 205), (76, 212)), _racket(46, 203)),
    ]
    assert d._racket_arm_side(chosen) == WRIST_LEFT


def test_no_racket_frames_stick_to_voted_arm_even_when_other_lower():
    d = _detector()
    voted = [(_person((40, 200), (75, 210)), _racket(48, 198))]
    arm = d._racket_arm_side(voted)
    assert arm == WRIST_LEFT

    # 击球窗口球拍全部漏检（None）；两手几乎等高，右手时高时低。
    # 旧逻辑会在 9/10 之间翻；锁定持拍臂后必须每帧都返回左手腕。
    seq = [
        ((879.7, 381.2), (920.2, 380.7)),  # 右手略高 -> 旧逻辑取左
        ((881.0, 381.6), (921.3, 381.9)),  # 右手略低 -> 旧逻辑翻到右
        ((881.6, 388.9), (914.9, 388.8)),  # 右手略高
        ((879.4, 395.1), (913.1, 398.2)),  # 右手明显更低
    ]
    for lw, rw in seq:
        picked = d._pick_wrist(_person(lw, rw), {"box": None, "conf": 0.0}, arm)
        assert picked is not None
        assert abs(picked[0] - lw[0]) < 1e-3 and abs(picked[1] - lw[1]) < 1e-3


def test_two_handed_close_wrists_do_not_lock_side():
    d = _detector()
    # 双手握拍：两只手腕几乎重合且都贴着球拍，无法也不应锁定单侧
    chosen = [
        (_person((90, 200), (96, 201)), _racket(93, 175)),
        (_person((92, 198), (98, 199)), _racket(95, 173)),
    ]
    assert d._racket_arm_side(chosen) is None


def test_without_racket_evidence_falls_back_to_lower_wrist():
    d = _detector()
    assert d._racket_arm_side([(_person((40, 200), (70, 220)),
                                {"box": None, "conf": 0.0})]) is None
    # 无锁定时沿用旧的"更低的手腕"回退
    p = _person((40, 200), (70, 220))
    got = d._pick_wrist(p, {"box": None, "conf": 0.0}, None)
    assert got == (70, 220)
