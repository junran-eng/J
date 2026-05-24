# ============================================================
# tests/test_classifier.py — 内容类型检测单元测试
# ============================================================
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.classifier import detect_content_type, get_research_foci, type_label


def test_detect_tech():
    assert detect_content_type("低温除湿干化技术原理", ["原理", "热泵"]) == "tech"


def test_detect_policy():
    assert detect_content_type("环保排放新标准解读", ["标准", "法规"]) == "policy"


def test_detect_event():
    assert detect_content_type("行业展会参展纪要", ["展会", "论坛"]) == "event"


def test_empty_keywords():
    ct = detect_content_type("低温干化设备选型指南", [])
    assert ct == "tech"


def test_research_foci_tech():
    foci = get_research_foci("tech")
    assert len(foci) == 3
    assert "技术原理" in foci[0]


def test_research_foci_policy():
    foci = get_research_foci("policy")
    assert len(foci) == 3
    assert "政策背景" in foci[0]


def test_research_foci_event():
    foci = get_research_foci("event")
    assert len(foci) == 3
    assert "事件背景" in foci[0]


def test_type_label():
    assert type_label("tech") == "技术"
    assert type_label("policy") == "政策"
    assert type_label("event") == "事件"


if __name__ == "__main__":
    test_detect_tech()
    test_detect_policy()
    test_detect_event()
    test_empty_keywords()
    test_research_foci_tech()
    test_research_foci_policy()
    test_research_foci_event()
    test_type_label()
    print("ALL TESTS PASSED")
