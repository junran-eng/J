# ============================================================
# agents/critic.py — Phase3 评审排序
# ============================================================
import logging

from infra.llm import extract_json, clean_text
from infra.prompts import P_CRITIC, build_editor_prompt

logger = logging.getLogger("agents.critic")


def evaluate_and_pick(versions, call_llm_fn, content_type=None):
    """Score each version, auto-revise if <80, sort best first.

    If content_type is provided and enough performance data exists,
    a small boost is applied based on historical engagement.

    Returns:
        list: versions sorted by score descending
    """
    P_EDITOR = build_editor_prompt()

    # Performance boost: read historical engagement data
    perf_boost = 0
    if content_type:
        try:
            from infra.memory import get_performance_stats
            pstats = get_performance_stats()
            total_cnt = sum(r.get("cnt", 0) for r in pstats)
            if total_cnt >= 10:
                avg_reads = sum(r.get("avg_reads", 0) * r.get("cnt", 0) for r in pstats) / total_cnt
                for r in pstats:
                    if r.get("content_type") == content_type and r.get("avg_reads", 0) > avg_reads:
                        from config import get_config
                        perf_boost = int(r["avg_reads"] / max(avg_reads, 1) * get_config().perf_boost_weight * 100)
                        logger.info("[Critic] perf boost for %s: +%d", content_type, perf_boost)
                        break
        except Exception as e:
            logger.debug("[Critic] perf boost skipped: %s", e)

    for v in versions:
        ev = extract_json(call_llm_fn(P_CRITIC, f"## 标题\n{v['title']}\n## 正文\n{v['body'][:4000]}\n评估。"))
        score = ev.get("score", 0)
        v["score"] = score

        # 低于 80 分自动修订一次
        if score < 80 and score > 0:
            rp = (
                f"评审: {ev.get('report', '')}\n"
                f"建议: {'; '.join(ev.get('suggestions', []))}\n"
                f"原标题: {v['title']}\n"
                f"原文: {v['body'][:3000]}\n"
                f"输出JSON。"
            )
            ra = extract_json(call_llm_fn(P_EDITOR, rp))
            if ra.get("body"):
                v["title"] = clean_text(ra.get("title", v["title"]))
                v["body"] = clean_text(ra["body"])
                v["image_prompt"] = ra.get("image_prompt", v["image_prompt"])

            # 修订后重新评分
            ev2 = extract_json(call_llm_fn(
                P_CRITIC, f"## 标题\n{v['title']}\n## 正文\n{v['body'][:4000]}\n评估。"
            ))
            v["score"] = ev2.get("score", score)

        if perf_boost:
            v["score"] = min(100, v["score"] + perf_boost)
        logger.info("[Critic] %s: %d pts%s (%d chars)", v["style"], v["score"],
                    f" (boost +{perf_boost})" if perf_boost else "", len(v["body"]))

    versions.sort(key=lambda x: x["score"], reverse=True)
    return versions
