def _rallies(events, gap_seconds):
    events = sorted(events, key=lambda e: e.peak_ts)
    rallies, cur = [], []
    for e in events:
        if cur and e.peak_ts - cur[-1].peak_ts > gap_seconds:
            rallies.append(cur); cur = []
        cur.append(e)
    if cur:
        rallies.append(cur)
    return rallies

def select_best(events, target, gap_seconds):
    reps = [max(r, key=lambda e: e.quality) for r in _rallies(events, gap_seconds)]
    reps.sort(key=lambda e: -e.quality)
    chosen = reps[:target]
    # 发球候选取自全部事件（发球可能在回合内被质量更高的动作挤掉）
    serves = [e for e in events if e.suspected_serve and e not in chosen]
    serves.sort(key=lambda e: -e.quality)
    if target >= 2 and serves and not any(e.suspected_serve for e in chosen):
        chosen[-1] = serves[0]  # 用质量最高的发球替换末位
    return sorted(chosen, key=lambda e: e.peak_ts)
