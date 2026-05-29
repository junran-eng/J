# ============================================================
# agents/classifier.py — 内容类型识别（LLM 优先，关键词兜底）
# ============================================================
import logging

from infra.prompts import get_content_signals, reload_prompts

logger = logging.getLogger("agents.classifier")

_signals = get_content_signals()
EVENT_SIGNALS = _signals["event"]
POLICY_SIGNALS = _signals["policy"]
TECH_SIGNALS = _signals["tech"]

TYPE_LABELS = {"tech": "技术", "policy": "政策", "event": "事件"}


def detect_content_type(topic, keywords):
    """关键词快速分类"""
    text = topic + " " + " ".join(keywords) if keywords else topic
    e = sum(1 for s in EVENT_SIGNALS if s in text)
    p = sum(1 for s in POLICY_SIGNALS if s in text)
    t = sum(1 for s in TECH_SIGNALS if s in text)
    if p >= e and p >= t:
        return "policy"
    if e >= p and e >= t:
        return "event"
    return "tech"


def classify_with_llm(topic, keywords, call_llm_fn):
    """用 LLM 做精确分类（成本低，一次调用）"""
    text = topic + " " + " ".join(keywords[:3]) if keywords else topic
    prompt = (
        f'判断以下主题属于哪类内容，只回复一个词：技术/政策/事件\n'
        f'主题：{text[:200]}\n'
        f'类型：'
    )
    try:
        result = call_llm_fn("你是内容分类助手。只回复一个词。", prompt).strip()
        result = result.replace("类型：", "").replace(":", "").strip()
        if "政策" in result or "policy" in result:
            return "policy"
        if "事件" in result or "event" in result:
            return "event"
        return "tech"
    except Exception as e:
        logger.warning("[classifier] LLM classification failed, fallback to keywords: %s", e)
        return detect_content_type(topic, keywords)


def get_research_foci(content_type):
    if content_type == "tech":
        return ["技术原理与路线对比", "设备参数与能效数据", "应用场景与经济效益"]
    elif content_type == "policy":
        return ["政策背景与原文要点", "对行业的影响分析", "企业应对策略"]
    else:
        return ["事件背景与行业意义", "吉康参与角色", "市场反响与展望"]


def type_label(content_type):
    return TYPE_LABELS.get(content_type, "技术")


def reload_signals():
    """热重载关键词信号"""
    global EVENT_SIGNALS, POLICY_SIGNALS, TECH_SIGNALS, _signals
    _signals = reload_prompts()
    EVENT_SIGNALS = _signals["event"]
    POLICY_SIGNALS = _signals["policy"]
    TECH_SIGNALS = _signals["tech"]
    logger.info("[classifier] signals reloaded: event=%d policy=%d tech=%d",
                len(EVENT_SIGNALS), len(POLICY_SIGNALS), len(TECH_SIGNALS))
