# ============================================================
# tests/test_llm.py — JSON 解析 + 文本清洗单元测试
# ============================================================
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from infra.llm import extract_json, clean_text


def test_extract_raw_json():
    assert extract_json('{"score": 85}') == {"score": 85}


def test_extract_markdown_block():
    result = extract_json('```json\n{"title": "test", "body": "hello"}\n```')
    assert result["title"] == "test"


def test_extract_nested_json():
    text = 'some text {"score": 90, "passed": true} more text'
    result = extract_json(text)
    assert result["score"] == 90


def test_extract_empty():
    assert extract_json("") == {}


def test_extract_invalid():
    assert extract_json("not json at all") == {}


def test_clean_text_normal():
    assert clean_text("hello world") == "hello world"


def test_clean_text_crlf():
    assert clean_text("line1\r\nline2") == "line1\nline2"


def test_clean_text_multi_newlines():
    result = clean_text("a\n\n\n\nb")
    assert result == "a\n\nb" or "\n\n\n" not in result


def test_clean_text_none():
    assert clean_text(None) == ""


if __name__ == "__main__":
    test_extract_raw_json()
    test_extract_markdown_block()
    test_extract_nested_json()
    test_extract_empty()
    test_extract_invalid()
    test_clean_text_normal()
    test_clean_text_crlf()
    test_clean_text_multi_newlines()
    test_clean_text_none()
    print("ALL TESTS PASSED")
