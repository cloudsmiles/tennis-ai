import pytest
from app.llm.parse import parse_analysis

def test_plain_json():
    d = parse_analysis(
        '{"stroke_type":"forehand","level":"3.5","level_note":"转体充分",'
        '"strengths":["平衡好"],"weaknesses":["击球点偏后"],"advice":"多练转肩"}'
    )
    assert d["stroke_type"] == "forehand"
    assert d["level"] == "3.5"
    assert d["strengths"] == ["平衡好"] and d["weaknesses"] == ["击球点偏后"]

def test_json_in_code_fence():
    txt = (
        '好的，分析如下：\n```json\n{"stroke_type":"serve","level":"4.0",'
        '"level_note":"抛球稳定","strengths":[],"weaknesses":[],"advice":"y"}\n```'
    )
    assert parse_analysis(txt)["stroke_type"] == "serve"

def test_json_with_surrounding_text():
    txt = ('结果是 {"stroke_type":"backhand","level":"3.0","level_note":"",'
           '"strengths":[],"weaknesses":[],"advice":"z"} 希望有帮助')
    assert parse_analysis(txt)["stroke_type"] == "backhand"

def test_legacy_issues_falls_back_to_weaknesses():
    # 旧版回复仍用 issues：weaknesses 自动回退取 issues
    d = parse_analysis(
        '{"stroke_type":"forehand","issues":["随挥不完整"],"advice":"x"}'
    )
    assert d["weaknesses"] == ["随挥不完整"]

def test_missing_colon_after_key_is_repaired():
    # 实测：DOM 抓取/模型漏吐导致 "weaknesses" [ 缺冒号（键引号也可能丢）
    txt = (
        '{"stroke_type":"forehand","level":"3.0","level_note":"x",'
        '"strengths":["a"],"weaknesses ["b"],"advice":"c"}'
    )
    d = parse_analysis(txt)
    assert d["weaknesses"] == ["b"]

def test_invalid_raises():
    with pytest.raises(ValueError):
        parse_analysis("对不起，我无法分析这张图片")

def test_normalizes_missing_fields():
    d = parse_analysis('{"stroke_type":"forehand"}')
    assert set(["level", "level_note", "strengths", "weaknesses", "advice"]) <= set(d.keys())
