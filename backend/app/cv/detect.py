# YOLO 检测/跟踪集成层：person 跟踪 + racket 检测 + 持拍手腕关键点
# ultralytics/torch 只允许在本模块 import（见实现计划 Task 9）。
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
        self._track_id = None                 # 已锁定球员的 track id

    def _pick_device(self):
        import torch
        return "mps" if torch.backends.mps.is_available() else "cpu"

    # ------------------------------------------------------------------
    def detect_frames(self, frames, timestamps, target_player=None):
        """frames: BGR ndarray 列表; timestamps: 每帧时间戳;
        target_player=(cx,cy): 首帧选距该点最近的 person（前端点选），None 取最大者。"""
        self._track_id = None  # 每次调用视为一段新片段，重新锁定
        out = []
        for i, frame in enumerate(frames):
            r = self.pose.track(frame, persist=True, classes=[0],
                                device=self.device, verbose=False)[0]
            rd = self.det(frame, classes=[38], device=self.device, verbose=False)[0]
            det = self._pick_player(r, target_player)
            racket = self._nearest_racket(rd, det)
            wrist = self._wrist(r, det, racket)
            out.append(FrameDet(
                frame_idx=i, ts=float(timestamps[i]),
                player_box=det["box"], player_conf=det["conf"],
                racket_box=racket["box"], racket_conf=racket["conf"],
                wrist=wrist, pose_ok=det["pose_ok"]))
        return out

    # ------------------------------------------------------------------
    def _pick_player(self, res, target_player=None):
        """选目标球员。返回 {"box","conf","pose_ok","id"}（box 可为 None）。

        - 未锁定 id 时（首帧）：有 target_player 取距其最近的 person，否则取面积
          最大的；记录所选 person 的 track id。
        - 已锁定 id：取同 id 的 box；该帧缺失时回退为该帧面积最大的 person
          （锁定 id 保持不变）。
        """
        boxes = res.boxes
        n = int(boxes.xyxy.shape[0]) if boxes is not None else 0
        if n == 0:
            return {"box": None, "conf": 0.0, "pose_ok": False, "id": None}

        ids = boxes.id  # track() 下为 (n,) tensor；无 id 时为 None
        persons = []
        for j in range(n):
            box = tuple(float(v) for v in boxes.xyxy[j])
            persons.append({
                "box": box,
                "conf": float(boxes.conf[j]),
                "id": int(ids[j]) if ids is not None else None,
                "area": _box_area(box),
            })

        chosen = None
        if self._track_id is not None:
            chosen = next((j for j, p in enumerate(persons)
                           if p["id"] == self._track_id), None)
        if chosen is None:  # 首帧，或锁定 id 在本帧丢失
            first_pick = self._track_id is None
            if target_player is not None and first_pick:
                chosen = min(range(n),
                             key=lambda j: _dist2(_box_center(persons[j]["box"]),
                                                  target_player))
            else:
                chosen = max(range(n), key=lambda j: persons[j]["area"])
            if first_pick and persons[chosen]["id"] is not None:
                self._track_id = persons[chosen]["id"]  # 仅首帧锁定；丢失回退不改锁

        p = persons[chosen]
        return {"box": p["box"], "conf": p["conf"],
                "pose_ok": self._pose_ok(res, chosen), "id": p["id"]}

    def _pose_ok(self, res, idx):
        """第 idx 个人的 17 关键点中置信度 > 0.3 的数量 >= 12。"""
        kpts = self._person_keypoints(res, idx)
        if kpts is None:
            return False
        visible = sum(1 for j in range(min(17, int(kpts.shape[0])))
                      if float(kpts[j][2]) > KP_CONF)
        return visible >= POSE_OK_MIN

    def _person_keypoints(self, res, idx):
        """第 idx 个人的关键点 (17,3)（x,y,conf）；无关键点时返回 None。"""
        kp = getattr(res, "keypoints", None)
        data = getattr(kp, "data", None) if kp is not None else None
        if data is None or int(data.shape[0]) <= idx:
            return None
        return data[idx]

    # ------------------------------------------------------------------
    def _nearest_racket(self, res, det):
        """在 class 38 框中取中心距目标球员框中心最近者。返回 {"box","conf"}。"""
        boxes = res.boxes
        n = int(boxes.xyxy.shape[0]) if boxes is not None else 0
        if n == 0:
            return {"box": None, "conf": 0.0}
        cand = [{"box": tuple(float(v) for v in boxes.xyxy[j]),
                 "conf": float(boxes.conf[j])} for j in range(n)]
        pbox = det.get("box")
        if pbox is None:
            best = max(cand, key=lambda c: c["conf"])  # 无球员可参照：取置信度最高
        else:
            pc = _box_center(pbox)
            best = min(cand, key=lambda c: _dist2(_box_center(c["box"]), pc))
        return best

    # ------------------------------------------------------------------
    def _wrist(self, res, det, racket):
        """持拍侧手腕：(x,y) 或 None。仅统计置信度 > 0.3 的关键点。

        - 有球拍：取距球拍中心最近的那只手腕；
        - 无球拍：取 y 更大（位置更低）的那只。
        """
        if det.get("box") is None:
            return None
        # det["box"] 由 _pick_player 从 res.boxes 转换而来，按中心距离回找该人索引
        boxes = res.boxes
        n = int(boxes.xyxy.shape[0]) if boxes is not None else 0
        pc = _box_center(det["box"])
        idx, best_d = None, None
        for j in range(n):
            d = _dist2(_box_center(tuple(float(v) for v in boxes.xyxy[j])), pc)
            if best_d is None or d < best_d:
                best_d, idx = d, j
        kpts = self._person_keypoints(res, idx) if idx is not None else None
        if kpts is None or int(kpts.shape[0]) <= WRIST_RIGHT:
            return None

        wrists = []
        for j in (WRIST_LEFT, WRIST_RIGHT):
            x, y, c = (float(v) for v in kpts[j][:3])
            if c > KP_CONF:
                wrists.append((x, y))
        if not wrists:
            return None
        if racket.get("box") is not None:
            rc = _box_center(racket["box"])
            x, y = min(wrists, key=lambda p: _dist2(p, rc))
        else:
            x, y = max(wrists, key=lambda p: p[1])
        return (float(x), float(y))
