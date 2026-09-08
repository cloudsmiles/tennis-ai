"""parse_analysis 容错强化（final review fix 1）：overall / issues 类型收敛。

合法但字段类型奇怪的 JSON 不能把管线或 UI 弄崩：
- overall：int/float/数字字符串 → float；其余（None、乱串、bool）→ None
- issues：单个字符串 → [字符串]；非列表（含 None/缺失）→ []
"""
import json

from app.llm.parse import parse_analysis


def _parse(**overrides):
    d = {
        "stroke_type": "forehand",
        "scores": {},
        "overall": 8,
        "issues": [],
        "advice": "x",
    }
    d.update(overrides)
    return parse_analysis(json.dumps(d, ensure_ascii=False))


def test_overall_int_becomes_float():
    assert _parse(overall=7)["overall"] == 7.0
    assert isinstance(_parse(overall=7)["overall"], float)


def test_overall_numeric_string_coerced():
    assert _parse(overall="8.5")["overall"] == 8.5


def test_overall_garbage_string_becomes_none():
    assert _parse(overall="abc")["overall"] is None


def test_overall_none_and_bool_become_none():
    assert _parse(overall=None)["overall"] is None
    assert _parse(overall=True)["overall"] is None


def test_issues_single_string_wrapped():
    assert _parse(issues="一条问题")["issues"] == ["一条问题"]


def test_issues_non_list_becomes_empty():
    assert _parse(issues=42)["issues"] == []
    assert _parse(issues={"a": 1})["issues"] == []
    assert _parse(issues=None)["issues"] == []


def test_issues_list_passthrough():
    assert _parse(issues=["a", "b"])["issues"] == ["a", "b"]
