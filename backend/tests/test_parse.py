import pytest
from app.llm.parse import parse_analysis

def test_plain_json():
    d = parse_analysis('{"stroke_type":"forehand","scores":{"准备":8},"overall":7.5,"issues":["a"],"advice":"x"}')
    assert d["stroke_type"] == "forehand" and d["overall"] == 7.5

def test_json_in_code_fence():
    txt = '好的，分析如下：\n```json\n{"stroke_type":"serve","scores":{},"overall":8,"issues":[],"advice":"y"}\n```'
    assert parse_analysis(txt)["stroke_type"] == "serve"

def test_json_with_surrounding_text():
    txt = '结果是 {"stroke_type":"backhand","scores":{},"overall":6,"issues":[],"advice":"z"} 希望有帮助'
    assert parse_analysis(txt)["stroke_type"] == "backhand"

def test_invalid_raises():
    with pytest.raises(ValueError):
        parse_analysis("对不起，我无法分析这张图片")

def test_normalizes_missing_fields():
    d = parse_analysis('{"stroke_type":"forehand"}')
    assert set(["scores","overall","issues","advice"]) <= set(d.keys())
