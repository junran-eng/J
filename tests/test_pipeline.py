# ============================================================
# tests/test_pipeline.py — Pipeline 集成测试（mock LLM）
# ============================================================
import sys, os, json, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# Mock LLM: 不调用真实 API，返回预设 JSON
_call_count = 0

def mock_call_llm(system, user):
    global _call_count
    _call_count += 1

    if "评审" in system or "评分" in system:
        return json.dumps({
            "score": 85,
            "term_accuracy": 0.95,
            "report": "内容质量良好",
            "suggestions": ["补充数据"],
            "passed": True,
        }, ensure_ascii=False)
    elif "主编" in system or "标题" in system or "PAS" in system:
        return json.dumps({
            "title": "测试标题：低温干化技术前沿",
            "body": "这是一篇关于低温干化技术的测试文章。\n\n## 技术原理\n低温干化技术通过热泵循环实现...\n\n## 应用场景\n在市政污泥领域...",
            "image_prompt": "A low temperature drying equipment in an industrial setting",
        }, ensure_ascii=False)
    else:
        return f"研究员报告：关于低温干化的{len(user)}字报告"


# 替换模块中的 call_llm
import infra.llm as llm_mod
import agents.researcher as researcher_mod
import agents.editor as editor_mod
import agents.critic as critic_mod

_orig_call_llm = llm_mod.call_llm

llm_mod.call_llm = lambda s, u, m, ak, ab, t=0.5, mt=4096, to=300: mock_call_llm(s, u)


def mock_scrape(topic, keywords, timeout=15):
    return {
        "吉康官网": ("成功", "[吉康官网] 1234字节"),
        "生态环境部": ("成功", "[生态环境部] 5678字节"),
        "工信部": ("失败", "超时"),
    }


def test_pipeline_classifier_flow():
    """测试内容类型识别在 pipeline 中的流转"""
    from agents.classifier import detect_content_type
    ct = detect_content_type("低温除湿干化设备", ["原理", "工艺"])
    assert ct == "tech"

    from agents.classifier import get_research_foci
    foci = get_research_foci(ct)
    assert len(foci) == 3


def test_editor_generates_valid_structure():
    """测试 editor 输出格式正确"""
    mock_llm = lambda s, u: mock_call_llm(s, u)
    from agents.editor import generate_variants
    versions = generate_variants("低温干化技术", "技术", {"R1": "r1", "R2": "r2", "R3": "r3"}, "", mock_llm)
    assert len(versions) == 3
    for v in versions:
        assert "title" in v
        assert "body" in v
        assert "style" in v
        assert len(v["body"]) > 0


def test_critic_scores_versions():
    """测试 critic 评分并排序"""
    mock_llm = lambda s, u: json.dumps({
        "score": 80,
        "term_accuracy": 0.9,
        "report": "ok",
        "suggestions": [],
        "passed": True,
    }, ensure_ascii=False)

    from agents.critic import evaluate_and_pick
    versions = [
        {"style": "标准版", "title": "A", "body": "正文A" * 50, "image_prompt": "", "score": 0},
        {"style": "数据版", "title": "B", "body": "正文B" * 50, "image_prompt": "", "score": 0},
    ]
    result = evaluate_and_pick(versions, mock_llm)
    assert len(result) == 2
    assert result[0]["score"] >= result[1]["score"]


def test_config_loads():
    from config import get_config
    cfg = get_config()
    assert cfg.model_name is not None
    assert cfg.api_base is not None
    assert cfg.output_dir is not None


def test_memory_init():
    from infra.memory import init_db, get_stats
    init_db()
    stats = get_stats()
    assert "total" in stats
    assert "avg_score" in stats


if __name__ == "__main__":
    test_pipeline_classifier_flow()
    test_editor_generates_valid_structure()
    test_critic_scores_versions()
    test_config_loads()
    test_memory_init()
    print("ALL INTEGRATION TESTS PASSED")
