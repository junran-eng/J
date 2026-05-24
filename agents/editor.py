# ============================================================
# agents/editor.py — Phase2 版本生成（prompt 延迟构建）
# ============================================================
import logging

from infra.llm import extract_json, clean_text
from infra.prompts import build_editor_prompt, get_brand_profile

logger = logging.getLogger("agents.editor")


def _get_editor_prompt():
    """每次调用时重新构建，支持热重载品牌准则"""
    return build_editor_prompt()


def generate_variants(topic, content_type_label, research_reports, kb_text, call_llm_fn, fast=False):
    brand_profile = get_brand_profile()
    P_EDITOR = _get_editor_prompt()

    base_ep = f"## 客户\n{topic}\n## 类型\n{content_type_label}\n"
    for k, v in research_reports.items():
        base_ep += f"## {k}\n{v}\n"
    if kb_text:
        base_ep += f"## 知识库参考\n{kb_text[:3000]}\n"
    if brand_profile:
        base_ep += f"## 公司简介\n{brand_profile}"

    if fast:
        styles = [("标准版", base_ep + "\n请整合撰写。数据版、故事版灵活运用。")]
    else:
        styles = [
            ("标准版", base_ep + "\n请整合撰写。"),
            ("数据版", base_ep + "\n风格：数据驱动，每段至少一个数字，多用对比表格。"),
            ("故事版", base_ep + "\n风格：以客户案例故事开头，标题要有网感有传播力。"),
        ]

    versions = []
    for sname, sep in styles:
        art = extract_json(call_llm_fn(P_EDITOR, sep))
        t = art.get("title", "")
        b = art.get("body", "")
        imp = art.get("image_prompt", "")

        if len(b) < 500:
            logger.info("[Editor] %s too short (%d chars), retry", sname, len(b))
            art2 = extract_json(call_llm_fn(P_EDITOR, sep + "\n务必1500字以上！"))
            t = art2.get("title", t)
            b = art2.get("body", b)
            imp = art2.get("image_prompt", imp)

        versions.append({
            "style": sname,
            "title": clean_text(t),
            "body": clean_text(b),
            "image_prompt": imp.strip() if imp else "",
            "score": 0,
        })
        logger.info("[Editor] %s: %d chars", sname, len(b))

    return versions
