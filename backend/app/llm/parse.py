import json
import re


def _extract_object(text):
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fence:
        return fence.group(1)
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        return text[start:end + 1]
    raise ValueError("no json object found")


def _as_str(v):
    """文本字段容错：字符串原样；None/非字符串 → ""。"""
    return v if isinstance(v, str) else ""


def _as_str_list(v):
    """列表字段容错：字符串包成单元素列表；非列表（含 None/数字/字典）→ []。

    列表内只保留字符串条目，并去除空白。
    """
    if isinstance(v, str):
        return [v] if v.strip() else []
    if isinstance(v, list):
        out = []
        for x in v:
            if isinstance(x, bool) or not isinstance(x, (str, int, float)):
                continue  # None / dict / list 等无法作为点评条目，丢弃
            s = str(x).strip()
            if s:
                out.append(s)
        return out
    return []


def _loose_json_loads(raw):
    """json.loads 的轻量容错：先严格解析；失败再修复常见小笔误。

    覆盖实测形态：键后缺冒号甚至缺闭合引号（"weaknesses" [ 或 "weaknesses [
    应为 "weaknesses": [，DOM 渲染层丢字符或模型漏吐都可能产生）。只修
    「开引号 + 纯键名 + 可选冒号 + [/{」，合法 JSON 中该写法只会原样重写，
    不会误伤正常内容。
    """
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    fixed = re.sub(
        r'"([A-Za-z_]\w*)"?\s*:?\s*(\[|\{)',
        lambda m: f'"{m.group(1)}": {m.group(2)}',
        raw,
    )
    return json.loads(fixed)  # 仍失败则抛出，由调用方记 parse_failed


def parse_analysis(text):
    raw = _extract_object(text)
    try:
        d = _loose_json_loads(raw)
    except json.JSONDecodeError:
        raise ValueError("invalid json")
    # weaknesses 兼容旧字段名 issues（老版本 prompt 的回复）
    weaknesses = d.get("weaknesses")
    if weaknesses is None:
        weaknesses = d.get("issues", [])
    return {
        "stroke_type": d.get("stroke_type"),
        "level": _as_str(d.get("level")),
        "level_note": _as_str(d.get("level_note")),
        "strengths": _as_str_list(d.get("strengths")),
        "weaknesses": _as_str_list(weaknesses),
        "advice": _as_str(d.get("advice")),
    }
