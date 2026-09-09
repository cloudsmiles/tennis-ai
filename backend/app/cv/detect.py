# YOLO 检测/跟踪集成层：person 跟踪 + racket 检测 + 持拍手腕关键点
# ultralytics/torch 只允许在本模块 import（见实现计划 Task 9）。
#
# 两段式：先对整段帧做 track（persist 分配 track id），再在"用户点击时刻"那帧
# 按坐标锁定目标球员的 track id，最后用该 id 贯穿整段选框——这样无论用户在哪一
# 帧点选，跟踪都会自动跟随这名球员穿过整个动作（点击帧与取帧窗口起点不同也无妨）。
import sys

from ..schemas import FrameDet

WRIST_LEFT, WRIST_RIGHT = 9, 10   # COCO 关键点索引
KP_CONF = 0.3                     # 关键点可见性阈值
POSE_OK_MIN = 12                  # 17 点中至少 12 点可见才算 pose_ok


def _box_center(box):
    x1, y1, x2, y2 = box
    return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)


def _box_area(box):
    x1, y1, x2, y2 = box
    return max(0.0, float(x2) - float(x1)) * max(0.0, float(y2) - float(y1))


def _dist2(a, b):
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2


def _ensure_lap():
    """保证 `import lap` 可用（Ultralytics track() 模块级无条件依赖）。

    ultralytics 8.3 的 trackers/utils/matching.py 在模块级 `import lap`；本环境
    未安装 lap 且约定不 pip-install。缺失时注入基于 scipy 的兼容实现（语义同
    ultralytics 自带的 use_lap=False 回退路径）。若环境已装 lap 则用原生版本。
    必须在首次调用 model.track() 前执行。
    """
    if "lap" in sys.modules:
        return
    try:
        import lap  # noqa: F401
        if getattr(lap, "__version__", None):
            return  # 原生 lap 可用
    except ImportError:
        pass

    import types
    import numpy as np
    from scipy.optimize import linear_sum_assignment

    def _lapjv(cost, extend_cost=False, cost_limit=None):
        """lap.lapjv 的 scipy 实现：返回 (total_cost, x, y)，未分配下标为 -1。"""
        cost = np.asarray(cost, dtype=np.float64)
        n_rows, n_cols = cost.shape
        if extend_cost or n_rows != n_cols:
            n = max(n_rows, n_cols)
            pad = (float(cost_limit) + 1.0) if cost_limit is not None else \
                (float(cost.max()) if cost.size else 0.0)
            ext = np.full((n, n), pad, dtype=np.float64)
            ext[:n_rows, :n_cols] = cost
            cost = ext
        x = np.full(n_rows, -1, dtype=int)
        y = np.full(n_cols, -1, dtype=int)
        if n_rows == 0 or n_cols == 0:
            return 0.0, x, y
        rows, cols = linear_sum_assignment(cost)
        total = 0.0
        for r, c in zip(rows.tolist(), cols.tolist()):
            if r >= n_rows or c >= n_cols:
                continue  # 扩展出的虚拟行/列 → 视为未分配
            c_val = float(cost[r, c])
            if cost_limit is not None and c_val > cost_limit:
                continue
            x[r] = c
            y[c] = r
            total += c_val
        return total, x, y

    mod = types.ModuleType("lap")
    mod.__version__ = "0.0.0+scipy-shim"
    mod.lapjv = _lapjv
    sys.modules["lap"] = mod


class Detector:
    """逐帧检测目标球员（track 锁定单人）、其网球拍与持拍侧手腕。"""

    def __init__(self, device=None):
        _ensure_lap()
        from ultralytics import YOLO
        self.pose = YOLO("yolo11n-pose.pt")   # person box + 17 keypoints
        self.det = YOLO("yolo11n.pt")         # COCO class 38: tennis racket
        self.device = device or self._pick_device()

    def _pick_device(self):
        import torch
        return "mps" if torch.backends.mps.is_available() else "cpu"

    # ------------------------------------------------------------------
    def detect_frames(self, frames, timestamps, target_player=None,
                      target_ts=None, on_progress=None):
        """frames: BGR ndarray 列表; timestamps: 每帧时间戳（秒）。

        target_player=(cx,cy)：用户点选的视频像素坐标；配合 target_ts（点击发生
        的时间戳）在最近的那帧锁定距该点最近的 person 的 track id，随后整段跟随
        此人。target_ts 为 None 时（自动模式/旧调用）在首帧锁定。target_player
        为 None 时取面积最大者。on_progress(done, total) 在逐帧推理（CPU 上最耗时
        的一段）每完成一帧回调一次，用于驱动进度条。
        """
        # 第一段：整段跟踪，收集每帧的 person / racket 原始信息
        info = []  # [(pose_res, persons, rackets), ...]
        total = len(frames)
        for fi, frame in enumerate(frames):
            pr = self.pose.track(frame, persist=True, classes=[0],
                                 device=self.device, verbose=False)[0]
            dr = self.det(frame, classes=[38], device=self.device,
                          verbose=False)[0]
            info.append((pr, self._parse_persons(pr), self._parse_rackets(dr)))
            if on_progress is not None:
                on_progress(fi + 1, total)

        lock_id = self._choose_lock_id(info, list(timestamps),
                                       target_player, target_ts)

        # 第二段：每帧用锁定的 track id 选人（id 丢失时回退面积最大者）
        chosen = []
        for pr, persons, rackets in info:
            person = self._person_with_id(persons, lock_id)
            box = person["box"] if person else None
            chosen.append((person, self._pick_racket(rackets, box)))

        # 先用"看得到球拍"的帧投票锁定持拍臂：击球瞬间运动模糊常让球拍整段
        # 漏检，若每帧独立取"更低的手腕"，两手近乎等高时会在左右臂间逐帧翻转，
        # 凭空造出大幅位移尖峰。锁定后无球拍帧也始终跟同一只手腕。
        arm_side = self._racket_arm_side(chosen)

        out = []
        for i, (person, racket) in enumerate(chosen):
            box = person["box"] if person else None
            wrist = self._pick_wrist(person, racket, arm_side)
            out.append(FrameDet(
                frame_idx=i, ts=float(timestamps[i]),
                player_box=box,
                player_conf=person["conf"] if person else 0.0,
                racket_box=racket["box"], racket_conf=racket["conf"],
                wrist=wrist,
                pose_ok=person["pose_ok"] if person else False))
        return out

    # ------------------------------------------------------------------
    def _parse_persons(self, res):
        """从 pose.track 结果解析所有人：box/conf/id/area/pose_ok/kp。"""
        boxes = res.boxes
        n = int(boxes.xyxy.shape[0]) if boxes is not None else 0
        persons = []
        for j in range(n):
            box = tuple(float(v) for v in boxes.xyxy[j])
            kp = self._person_keypoints(res, j)
            persons.append({
                "box": box,
                "conf": float(boxes.conf[j]),
                "id": int(boxes.id[j]) if boxes.id is not None else None,
                "area": _box_area(box),
                "pose_ok": self._pose_ok_from_kp(kp),
                "kp": kp,
            })
        return persons

    def _parse_rackets(self, res):
        """从 det 结果解析所有网球拍框：box/conf。"""
        boxes = res.boxes
        n = int(boxes.xyxy.shape[0]) if boxes is not None else 0
        return [{"box": tuple(float(v) for v in boxes.xyxy[j]),
                 "conf": float(boxes.conf[j])} for j in range(n)]

    def _choose_lock_id(self, info, timestamps, target_player, target_ts):
        """确定要跟随的 track id：在目标帧（target_ts 最近帧，否则首帧）选人。

        有 target_player 取距该点最近者，否则取面积最大者；返回其 track id
        （可能为 None——该帧未分配 id 时，随后每帧回退面积最大者）。
        """
        if not info:
            return None
        if target_ts is not None:
            lock_frame = min(range(len(timestamps)),
                             key=lambda i: abs(timestamps[i] - target_ts))
        else:
            lock_frame = 0

        # 目标帧没人时，向邻近帧找第一个有人的帧
        f = lock_frame
        while f < len(info) and not info[f][1]:
            f += 1
        if f >= len(info) or not info[f][1]:
            f = lock_frame
            while f >= 0 and not info[f][1]:
                f -= 1
        if f < 0 or not info[f][1]:
            return None

        persons = info[f][1]
        if target_player is not None:
            chosen = min(persons,
                         key=lambda p: _dist2(_box_center(p["box"]),
                                              target_player))
        else:
            chosen = max(persons, key=lambda p: p["area"])
        return chosen["id"]

    def _person_with_id(self, persons, lock_id):
        """取 track id 匹配的人；缺失或无锁时回退面积最大者。"""
        if not persons:
            return None
        if lock_id is not None:
            for p in persons:
                if p["id"] == lock_id:
                    return p
        return max(persons, key=lambda p: p["area"])

    # ------------------------------------------------------------------
    def _pick_racket(self, rackets, pbox):
        """距目标球员框中心最近的球拍；无球员参照时取置信度最高者。"""
        if not rackets:
            return {"box": None, "conf": 0.0}
        if pbox is None:
            return max(rackets, key=lambda r: r["conf"])
        pc = _box_center(pbox)
        return min(rackets, key=lambda r: _dist2(_box_center(r["box"]), pc))

    # ------------------------------------------------------------------
    def _racket_arm_side(self, chosen):
        """从"看得到球拍"的帧投票判定持拍臂是左手腕还是右手腕。

        chosen: [(person, racket), ...]。逐帧比较两只手腕到球拍中心的距离，
        仅当一只手腕明显更近（距离 < 另一只的 80%）时计一票——双手握拍时两手
        都贴在拍柄、距离相当，此时不锁定（返回 None），交由逐帧回退处理。
        """
        votes = {WRIST_LEFT: 0, WRIST_RIGHT: 0}
        for person, racket in chosen:
            if person is None or racket.get("box") is None:
                continue
            kp = person.get("kp")
            if kp is None or int(kp.shape[0]) <= WRIST_RIGHT:
                continue
            pts = {}
            for j in (WRIST_LEFT, WRIST_RIGHT):
                if float(kp[j][2]) > KP_CONF:
                    pts[j] = (float(kp[j][0]), float(kp[j][1]))
            if len(pts) < 2:
                continue
            rc = _box_center(racket["box"])
            near = min(pts, key=lambda j: _dist2(pts[j], rc))
            other = WRIST_RIGHT if near == WRIST_LEFT else WRIST_LEFT
            if _dist2(pts[near], rc) < 0.64 * _dist2(pts[other], rc):
                votes[near] += 1
        best = max(votes, key=votes.get)
        return best if votes[best] > 0 else None

    # ------------------------------------------------------------------
    def _pick_wrist(self, person, racket, arm_side=None):
        """持拍侧手腕 (x,y) 或 None。

        - 有球拍：取距球拍中心最近的那只手腕；
        - 无球拍、已锁定持拍臂(arm_side)：始终取该侧手腕（身份不随帧翻转）；
        - 无球拍、未锁定：取 y 更大（位置更低）的那只（旧回退）。
        仅统计置信度 > 0.3 的关键点。
        """
        if person is None:
            return None
        kp = person.get("kp")
        if kp is None or int(kp.shape[0]) <= WRIST_RIGHT:
            return None
        wrists = {}
        for j in (WRIST_LEFT, WRIST_RIGHT):
            x, y, c = (float(v) for v in kp[j][:3])
            if c > KP_CONF:
                wrists[j] = (x, y)
        if not wrists:
            return None
        if racket.get("box") is not None:
            rc = _box_center(racket["box"])
            j = min(wrists, key=lambda k: _dist2(wrists[k], rc))
        elif arm_side is not None and arm_side in wrists:
            j = arm_side
        else:
            j = max(wrists, key=lambda k: wrists[k][1])
        x, y = wrists[j]
        return (float(x), float(y))

    # ------------------------------------------------------------------
    def _person_keypoints(self, res, idx):
        """第 idx 个人的关键点 (17,3)（x,y,conf）；无关键点时返回 None。"""
        kp = getattr(res, "keypoints", None)
        data = getattr(kp, "data", None) if kp is not None else None
        if data is None or int(data.shape[0]) <= idx:
            return None
        return data[idx]

    def _pose_ok_from_kp(self, kp):
        """17 关键点中置信度 > 0.3 的数量 >= 12。"""
        if kp is None:
            return False
        visible = sum(1 for j in range(min(17, int(kp.shape[0])))
                      if float(kp[j][2]) > KP_CONF)
        return visible >= POSE_OK_MIN
