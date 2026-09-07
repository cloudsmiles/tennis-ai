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

def parse_analysis(text):
    raw = _extract_object(text)
    try:
        d = json.loads(raw)
    except json.JSONDecodeError:
        raise ValueError("invalid json")
    return {
        "stroke_type": d.get("stroke_type"),
        "scores": d.get("scores", {}) or {},
        "overall": d.get("overall"),
        "issues": d.get("issues", []) or [],
        "advice": d.get("advice", ""),
    }
