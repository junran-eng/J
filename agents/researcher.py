# ============================================================
# agents/researcher.py — Phase1 三研究员并行
# ============================================================
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from infra.prompts import P_RESEARCHER
from agents.classifier import get_research_foci, type_label

logger = logging.getLogger("agents.researcher")


def parallel_research(topic, keywords, content_type, scrape_result, rag_context, kb_text, call_llm_fn):
    """三研究员并行生成专业报告

    Args:
        topic: 主题
        keywords: 关键词列表
        content_type: tech/policy/event
        scrape_result: web 抓取结果 dict
        rag_context: RAG 检索上下文
        kb_text: 知识库文本
        call_llm_fn: LLM 调用函数，签名 (system_prompt, user_message) -> str

    Returns:
        dict: {"R1": report_text, "R2": report_text, "R3": report_text}
    """
    foci = get_research_foci(content_type)
    tn = type_label(content_type)

    sctx = "".join(
        f"{'ok' if status == '成功' else 'fail'} {name}: {detail}\n"
        for name, (status, detail) in scrape_result.items()
    )

    results = {}
    with ThreadPoolExecutor(max_workers=3) as ex:
        futures = {}
        for n, focus in enumerate(foci, 1):
            msg = f"内容类型：{tn}。撰写关于「{focus}」的专业报告。800-1200字。"
            if sctx:
                msg += f"\n\n网页参考:\n{sctx}"
            if rag_context:
                msg += f"\n{rag_context}"
            if kb_text:
                msg += f"\n\n企业知识库参考:\n{kb_text[:2000]}"
            futures[ex.submit(call_llm_fn, P_RESEARCHER, msg)] = f"R{n}"

        for f in as_completed(futures):
            name = futures[f]
            try:
                results[name] = f.result()
                logger.info("[R%d] ok (%d chars)", int(name[1]), len(results[name]))
            except Exception as e:
                logger.error("[%s] failed: %s", name, e)
                results[name] = f"（{name}失败）"

    return results
