import json, re

def _extract_object(text):
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fence:
        return fence.group(1)
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        return text[start:end + 1]
    raise ValueError("no json object found")

def _as_float(v):
    """overall 容错：int/float/数字字符串 → float，其余（None、乱串、bool）→ None。"""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v)
        except ValueError:
            return None
    return None

def _as_issues(v):
    """issues 容错：单个字符串包成单元素列表；非列表（含 None/缺失）→ []。"""
    if isinstance(v, list):
        return v
    if isinstance(v, str):
        return [v]
    return []

def parse_analysis(text):
    raw = _extract_object(text)
    try:
        d = json.loads(raw)
    except json.JSONDecodeError:
        raise ValueError("invalid json")
    return {
        "stroke_type": d.get("stroke_type"),
        "scores": d.get("scores", {}) or {},
        "overall": _as_float(d.get("overall")),
        "issues": _as_issues(d.get("issues")),
        "advice": d.get("advice", ""),
    }
