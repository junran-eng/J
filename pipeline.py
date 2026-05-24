# ============================================================
# pipeline.py — 核心流水线编排 v2
# ============================================================
import logging, os, re, threading, time
from datetime import datetime

from agents.classifier import detect_content_type, type_label
from agents.researcher import parallel_research
from agents.editor import generate_variants
from agents.critic import evaluate_and_pick
from infra.llm import call_llm, extract_json
from infra.scraper import scrape_web
from infra.rag import context as rag_context
from infra.memory import save_result, init_db
from infra.image_gen import get_provider
from infra.knowledge_base import load_knowledge_base, retrieve as kb_retrieve

logger = logging.getLogger("pipeline")

_task_sem = threading.Semaphore(2)


def _prune_outputs(output_dir, max_files=None):
    """Remove oldest .txt files when count exceeds max_files"""
    if max_files is None:
        from config import get_config
        max_files = get_config().output_max_files
    try:
        txt_files = sorted(
            [f for f in os.listdir(output_dir) if f.endswith(".txt")],
            key=lambda x: os.path.getctime(os.path.join(output_dir, x))
        )
        while len(txt_files) > max_files:
            oldest = txt_files.pop(0)
            os.remove(os.path.join(output_dir, oldest))
            logger.info("[prune] removed old output: %s", oldest)
    except Exception as e:
        logger.debug("[prune] skipped: %s", e)



def _safe_filename(topic):
    """Sanitize topic for use in filename"""
    safe = re.sub(r'[\/*?:"<>|]', '', topic)
    safe = re.sub(r'\s+', '_', safe.strip())
    return safe[:30]

def run_pipeline(topic, keywords, model, api_key, api_base, output_dir=None, on_progress=None, fast=False, content_type=None, stop_event=None):
    """单次完整推广文生成流水线

    Args:
        fast: True 时只生成标准版（跳过数据版和故事版），省 2/3 LLM 调用
    """
    def prog(msg):
        logger.info(msg)
        if on_progress:
            try:
                on_progress(msg)
            except Exception:
                pass

    def llm(system, user):
        return call_llm(system, user, model, api_key, api_base)

    _task_sem.acquire()
    try:
        start = time.time()
        init_db()

        # Step 1: 内容类型识别
        ct = content_type or detect_content_type(topic, keywords)
        tn = type_label(ct)
        prog(f"[类型] {tn} {'(快速模式)' if fast else ''}")

        # Step 2: RAG
        rag = rag_context(topic, api_key, api_base)
        if rag:
            prog("[RAG] 检索到历史相关文章")

        # Step 3: 知识库检索
        kb_text = kb_retrieve(topic, keywords)
        if kb_text:
            prog(f"[KB] 检索到相关片段 {len(kb_text)}字")

        # Step 4: Phase0 网页抓取
        prog("[Phase0] 网页抓取...")
        sr = scrape_web(topic, keywords)
        sc = sum(1 for s, _ in sr.values() if s == "成功")
        fc = len(sr) - sc
        prog(f"[Phase0] 成功{sc}/{len(sr)}, 失败{fc}")
        if stop_event and stop_event.is_set():
            raise InterruptedError("stopped by user")

        # Step 5: Phase1 三研究员并行
        prog("[Phase1] 三研究员并行...")
        reports = parallel_research(topic, keywords, ct, sr, rag, kb_text, llm)
        if stop_event and stop_event.is_set():
            raise InterruptedError("stopped by user")

        # Step 6: Phase2 版本生成
        n_versions = 1 if fast else 3
        prog(f"[Phase2] {'单' if fast else 'AB三'}版本生成...")
        versions = generate_variants(topic, tn, reports, kb_text, llm, fast=fast)
        if stop_event and stop_event.is_set():
            raise InterruptedError("stopped by user")

        # Step 7: Phase3 评审排序
        prog("[Phase3] 评审...")
        versions = evaluate_and_pick(versions, llm, content_type=ct)
        best = versions[0]
        prog(f"[Phase3] 最优: {best['style']} ({best['score']}分)")

        # Step 8: 图片生成
        img_provider = get_provider(api_key)
        image_url = None
        if best.get("image_prompt"):
            try:
                prog("[图片] 生成封面图...")
                image_url = img_provider.generate(best["image_prompt"])
                if image_url and output_dir:
                    local = img_provider.download(image_url, output_dir)
                    prog(f"[图片] ok {local}" if local else "[图片] ok (URL)")
            except Exception as e:
                prog(f"[图片] fail: {e}")

        elapsed = round(time.time() - start, 1)
        ss = f"成功{sc}/{len(sr)},失败{fc}"

        result = {
            "topic": topic,
            "final_title": best["title"],
            "final_body": best["body"],
            "final_image_prompt": best["image_prompt"],
            "image_url": image_url,
            "scrape_status": ss,
            "content_type": tn,
            "evaluation": {"overall_score": best["score"], "report": "", "suggestions": []},
            "versions": [
                {
                    "style": v["style"], "title": v["title"],
                    "score": v["score"], "body": v["body"][:300] + "...",
                    "image_prompt": v["image_prompt"],
                }
                for v in versions
            ],
            "elapsed_seconds": elapsed,
        }

        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
            fn = os.path.join(output_dir, f"推广_{_safe_filename(topic)}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
            with open(fn, "w", encoding="utf-8") as f:
                f.write(f"{'='*60}\n标题：{result['final_title']}\n{'='*60}\n\n{result['final_body']}\n\n评分：{best['score']}/100\n")

        save_result(topic, ct, result, output_dir)

        from infra.rag import index
        index(result["final_body"], f"gen_{int(time.time())}", api_key, api_base)

        prog(f"完成: {best['score']}分, {elapsed}s")
        return result
    except InterruptedError:
        prog("[stop] user cancelled")
        return {"topic": topic, "final_title": "", "final_body": "", "evaluation": {"overall_score": 0}, "stopped": True}
    finally:
        _task_sem.release()

