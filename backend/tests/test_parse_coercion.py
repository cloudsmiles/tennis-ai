"""parse_analysis 容错：评级/列表字段类型收敛。

合法但字段类型奇怪的 JSON 不能把管线或 UI 弄崩：
- level / level_note / advice：非字符串 → ""
- strengths / weaknesses：字符串 → [字符串]；非列表（含 None/数字/字典）→ []；
  列表内非字符串条目转字符串，空白条目丢弃。
"""
import json

from app.llm.parse import parse_analysis


def _parse(**overrides):
    d = {
        "stroke_type": "forehand",
        "level": "3.5",
        "level_note": "发力链顺畅",
        "strengths": [],
        "weaknesses": [],
        "advice": "x",
    }
    d.update(overrides)
    return parse_analysis(json.dumps(d, ensure_ascii=False))


def test_strings_passthrough():
    d = _parse(level="4.5", level_note="稳定", advice="多练抛球")
    assert d["level"] == "4.5" and d["level_note"] == "稳定"
    assert d["advice"] == "多练抛球"


def test_non_string_text_fields_become_empty():
    d = _parse(level=3.5, level_note=None, advice=True)
    assert d["level"] == "" and d["level_note"] == "" and d["advice"] == ""


def test_single_string_wrapped_into_list():
    assert _parse(strengths="平衡好")["strengths"] == ["平衡好"]
    assert _parse(weaknesses="击球点偏后")["weaknesses"] == ["击球点偏后"]


def test_non_list_becomes_empty():
    assert _parse(strengths=42)["strengths"] == []
    assert _parse(weaknesses={"a": 1})["weaknesses"] == []
    assert _parse(strengths=None)["strengths"] == []


def test_list_filters_blank_and_stringifies():
    d = _parse(strengths=["a", "  ", 7, None], weaknesses=["x", "y"])
    assert d["strengths"] == ["a", "7"]
    assert d["weaknesses"] == ["x", "y"]
