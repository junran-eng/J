# ============================================================
# infra/prompts.py — Prompt 模板（支持热重载）
# ============================================================
import logging, os, re

logger = logging.getLogger("infra.prompts")

SKILL_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "jikang-marketing-skill")


def _readf(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""


_brand = ""
_types = ""


def _load_all():
    global _brand, _types
    _brand = _readf(os.path.join(SKILL_DIR, "references", "brand_guidelines.md"))
    _types = _readf(os.path.join(SKILL_DIR, "references", "content_types.md"))


_load_all()


def get_brand_profile():
    m = re.search(r"> 广东吉康环境系统科技有限公司[\s\S]*?(?=\n\n|\n#|\Z)", _brand)
    return m.group().strip() if m else ""


def get_content_signals():
    event_s = policy_s = tech_s = None
    m = re.search(r"事件[信号|].*?[：:]\s*(.*?)(?:\n|$)", _types)
    if m:
        event_s = [s.strip() for s in m.group(1).split("、")]
    m = re.search(r"政策[信号|].*?[：:]\s*(.*?)(?:\n|$)", _types)
    if m:
        policy_s = [s.strip() for s in m.group(1).split("、")]
    m = re.search(r"技术[信号|].*?[：:]\s*(.*?)(?:\n|$)", _types)
    if m:
        tech_s = [s.strip() for s in m.group(1).split("、")]

    return {
        "event": event_s or ["展会", "发布会", "签约", "竣工", "考察", "访问", "会议", "论坛", "峰会"],
        "policy": policy_s or ["标准", "法规", "政策", "通知", "意见", "规划", "排放", "环保", "国标", "污染防治"],
        "tech": tech_s or ["原理", "工艺", "设备", "参数", "对比", "选型", "应用案例", "技术路线", "能效", "节能"],
    }


def reload_prompts():
    """热重载：重新读取 brand + content_types"""
    _load_all()
    logger.info("[prompts] reloaded brand_guidelines + content_types")
    return get_content_signals()


P_RESEARCHER = (
    "你是低温干化设备行业研究员。"
    "根据内容类型撰写专业报告（800-1200字，数据【】标注，纯文本）。"
)


def build_editor_prompt():
    profile = get_brand_profile()
    return (
        f"你是「广东吉康环境系统科技有限公司」公众号主编。\n"
        f"品牌准则: {profile}\n"
        f"写作框架: PAS公式（Problem-Agitate-Solve），1500-2500字，文末公司简介。\n"
        f'输出JSON: {{"title":"...","body":"...","image_prompt":"..."}}'
    )


P_CRITIC = (
    "你是内容质量评审官。五维评分：品牌合规30/数据25/逻辑20/语言15/客户价值10。\n"
    '输出JSON: {"score":85,"term_accuracy":0.95,"report":"...","suggestions":["..."],"passed":true}'
)
