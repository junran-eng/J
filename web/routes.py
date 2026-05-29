# ============================================================
# web/routes.py - FastAPI 路由（审核 + 效果 + 过滤 + 热重载）
# ============================================================
import json, logging, os, threading, uuid
from datetime import datetime

from fastapi import FastAPI, Form, Query
from fastapi.responses import JSONResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from config import get_config
from pipeline import run_pipeline
from infra.memory import (
    get_sessions, get_messages, delete_session, get_stats,
    save_schedule, delete_schedule, get_schedules,
    approve_result, reject_result, get_pending_reviews,
    record_performance, get_performance, get_performance_stats,
)
from infra.knowledge_base import reload as kb_reload

logger = logging.getLogger("web")

web_tasks = {}
web_lock = threading.Lock()
web_sched = [None]

TASK_TTL = 300

def _cleanup_tasks():
    import time as _time
    now = _time.time()
    with web_lock:
        stale = [tid for tid, t in web_tasks.items()
                 if t["status"] in ("done", "error")
                 and now - _time.mktime(_time.strptime(t.get("created", "2000-01-01T00:00:00")[:19], "%Y-%m-%dT%H:%M:%S")) > TASK_TTL]
        for tid in stale:
            del web_tasks[tid]
    if stale:
        logger.debug("[TTL] cleaned %d stale tasks", len(stale))


def create_app() -> FastAPI:
    cfg = get_config()
    api_key = cfg.api_key
    api_base = cfg.api_base
    output_dir = cfg.output_dir

    DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    app = FastAPI()
    app.mount("/static", StaticFiles(directory=os.path.join(DIR, "web", "templates")), name="static")

    # 定期清理过期任务
    def _ttl_loop():
        import time as _time
        while True:
            _time.sleep(120)
            _cleanup_tasks()
    threading.Thread(target=_ttl_loop, daemon=True).start()

    # ============================================================
    # 基础
    # ============================================================
    @app.get("/")
    async def index():
        html_path = os.path.join(DIR, "web", "templates", "index.html")
        with open(html_path, "r", encoding="utf-8") as f:
            return HTMLResponse(f.read())

    @app.get("/api/health")
    async def health():
        return {"ok": True}

    @app.get("/api/notifications")
    async def notifications():
        from infra.notify import get_recent
        return {"items": get_recent()}

    @app.get("/api/config/status")
    async def config_status():
        from config import validate_config
        return validate_config()

    @app.get("/api/stats")
    async def stats():
        return get_stats()

    @app.get("/api/stats/tokens")
    async def stats_tokens():
        from infra.memory import get_token_stats
        return get_token_stats()

    @app.get("/api/reload")
    async def reload_api():
        kb_count = kb_reload()
        from infra.prompts import reload_prompts
        reload_prompts()
        from agents.classifier import reload_signals
        reload_signals()
        return {"ok": True, "kb_chunks": kb_count}

    @app.get("/api/calendar")
    async def calendar(days: int = 30):
        import yaml, os
        cal_path = os.path.join(DIR, "jikang-marketing-skill", "assets", "content_calendar.yaml")
        if not os.path.exists(cal_path):
            return {"items": [], "stats": {}}
        with open(cal_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or []
        from datetime import datetime, timedelta
        today = datetime.now().strftime("%Y-%m-%d")
        cutoff = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
        all_future = [i for i in data if i.get("date","") >= today]
        all_done = [i for i in data if i.get("done")]
        # 本月
        this_month = today[:7]
        month_total = [i for i in data if i.get("date","")[:7] == this_month]
        month_done = [i for i in month_total if i.get("done")]
        items = []
        for item in data:
            d = item.get("date", "")
            if today <= d <= cutoff:
                items.append({
                    "date": d, "topic": item.get("topic",""),
                    "type": item.get("type",""), "keywords": item.get("keywords",[]),
                    "priority": item.get("priority","normal"),
                    "series": item.get("series", ""),
                    "done": item.get("done", False),
                })
        items.sort(key=lambda x: x["date"])
        return {
            "items": items,
            "stats": {
                "total_future": len(all_future),
                "total_done": len(all_done),
                "completion_rate": round(len(all_done) / max(len(all_future) + len(all_done), 1) * 100, 1),
                "month_total": len(month_total),
                "month_done": len(month_done),
                "month_rate": round(len(month_done) / max(len(month_total), 1) * 100, 1),
            }
        }

    # 日历 CRUD 辅助
    def _cal_path():
        return os.path.join(DIR, "jikang-marketing-skill", "assets", "content_calendar.yaml")

    def _cal_read():
        import yaml
        p = _cal_path()
        if not os.path.exists(p): return []
        with open(p, "r", encoding="utf-8") as f: return yaml.safe_load(f) or []

    def _cal_write(data):
        import yaml
        p = _cal_path()
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    @app.post("/api/calendar")
    async def cal_add(date: str = Form(...), topic: str = Form(...),
                      type: str = Form("tech"), priority: str = Form("normal"),
                      keywords: str = Form(""), series: str = Form("")):
        kw = [k.strip() for k in keywords.split(",") if k.strip()]
        entry = {"date": date, "topic": topic, "type": type,
                 "keywords": kw, "priority": priority, "done": False}
        if series:
            entry["series"] = series
        data = _cal_read()
        data.append(entry)
        _cal_write(data)
        return {"ok": True}

    @app.put("/api/calendar")
    async def cal_update(date: str = Form(...), topic: str = Form(""),
                         type: str = Form(""), priority: str = Form(""),
                         done: str = Form(""), keywords: str = Form("")):
        data = _cal_read()
        for item in data:
            if item.get("date") == date:
                if topic: item["topic"] = topic
                if type: item["type"] = type
                if priority: item["priority"] = priority
                if done: item["done"] = done == "true"
                if keywords:
                    item["keywords"] = [k.strip() for k in keywords.split(",") if k.strip()]
                break
        _cal_write(data)
        return {"ok": True}

    @app.delete("/api/calendar")
    async def cal_delete(date: str = Form(...)):
        data = _cal_read()
        data = [item for item in data if item.get("date") != date]
        _cal_write(data)
        return {"ok": True}

    # ============================================================
    # 审核
    # ============================================================
    @app.get("/api/review/pending")
    async def review_pending():
        return {"pending": get_pending_reviews()}

    @app.post("/api/review/approve")
    async def review_approve(session_id: str = Form(...), operator: str = Form("reviewer")):
        ok = approve_result(session_id, operator)
        return {"ok": ok}

    @app.post("/api/review/regen")
    async def review_regen(session_id: str = Form(...)):
        msgs = get_messages(session_id)
        if not msgs:
            return JSONResponse({"error": "not found"}, 404)
        user_msg = next((m for m in msgs if m["role"] == "user"), None)
        if not user_msg:
            return JSONResponse({"error": "no user message"}, 400)
        from infra.memory import get_rejected
        topic = user_msg["content"]
        rejected = get_rejected(1)
        reason = ""
        for r in rejected:
            if r["id"] == session_id:
                reason = r.get("reason", "")
                break
        kw = [reason] if reason else []
        from pipeline import run_pipeline
        import threading, uuid
        tid = uuid.uuid4().hex[:12]
        stop_ev = threading.Event()
        with web_lock:
            web_tasks[tid] = {"id": tid, "topic": topic, "status": "pending", "stage": "重新生成中", "log": "", "created": datetime.now().isoformat(), "_stop_event": stop_ev}
        def job():
            try:
                r = run_pipeline(topic, kw, cfg.model_name or 'deepseek-v4-flash', api_key, api_base, output_dir, stop_event=stop_ev, acquire_timeout=60)
                with web_lock:
                    if tid in web_tasks:
                        web_tasks[tid].update({"status": "done", "result": r})
            except InterruptedError:
                with web_lock:
                    if tid in web_tasks:
                        web_tasks[tid].update({"status": "stopped", "stage": "stopped by user"})
            except Exception as e:
                logger.error("[Regen] fail: %s", e)
                with web_lock:
                    if tid in web_tasks:
                        web_tasks[tid].update({"status": "error", "error": str(e)})
        threading.Thread(target=job, daemon=True).start()
        return {"ok": True, "task_id": tid}

    @app.post("/api/review/reject")
    async def review_reject(session_id: str = Form(...), reason: str = Form(""), operator: str = Form("reviewer")):
        ok = reject_result(session_id, reason, operator)
        return {"ok": ok}

    @app.post("/api/review/comment")
    async def review_comment(session_id: str = Form(...), comment: str = Form(...),
                             author: str = Form("reviewer"), stage: str = Form("review")):
        from infra.memory import add_review_comment
        ok = add_review_comment(session_id, comment, author, stage)
        return {"ok": ok}

    @app.get("/api/review/comments/{session_id}")
    async def review_comments(session_id: str):
        from infra.memory import get_review_comments
        return {"comments": get_review_comments(session_id)}

    @app.get("/api/review/audit/{session_id}")
    async def review_audit_log(session_id: str):
        from infra.memory import get_audit_log
        return {"log": get_audit_log(session_id)}

    @app.get("/api/review/rejected")
    async def review_rejected():
        from infra.memory import get_rejected
        return {"rejected": get_rejected()}

    # ============================================================
    # 效果追踪
    # ============================================================
    @app.post("/api/performance")
    async def perf_record(session_id: str = Form(...), reads: int = Form(0),
                          shares: int = Form(0), likes: int = Form(0)):
        ok = record_performance(session_id, int(reads), int(shares), int(likes))
        return {"ok": ok}

    @app.get("/api/performance/{sid}")
    async def perf_get(sid: str):
        return get_performance(sid)

    @app.post("/api/performance/style")
    async def perf_set_style(session_id: str = Form(...), style: str = Form(...)):
        from infra.memory import set_published_style
        ok = set_published_style(session_id, style)
        return {"ok": ok}

    @app.get("/api/performance/stats")
    async def perf_stats():
        return get_performance_stats()

    # ============================================================
    # 质量趋势
    # ============================================================
    @app.get("/api/stats/coverage")
    async def stats_coverage(days: int = 60):
        """内容覆盖率分析：已覆盖话题 vs 选题缺口"""
        import sqlite3, yaml
        db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "memory", "conversations.db")
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            # 已生成内容的主题分类
            generated = conn.execute("""
                SELECT content_type, COUNT(*) as cnt, GROUP_CONCAT(topic, '||') as topics
                FROM stats WHERE status='approved'
                  AND created_at >= date('now', ? || ' days')
                GROUP BY content_type
            """, (f"-{days}",)).fetchall()
            # 所有生成过的主题关键词
            all_topics_rows = conn.execute("""
                SELECT DISTINCT topic FROM stats WHERE status='approved'
                  AND created_at >= date('now', ? || ' days')
                ORDER BY created_at DESC
            """, (f"-{days}",)).fetchall()
            all_topics = [r["topic"] for r in all_topics_rows]
            # 日历待排期选题
            cal_path = os.path.join(DIR, "jikang-marketing-skill", "assets", "content_calendar.yaml")
            calendar_items = []
            if os.path.exists(cal_path):
                with open(cal_path, "r", encoding="utf-8") as f:
                    cal_data = yaml.safe_load(f) or []
                today = datetime.now().strftime("%Y-%m-%d")
                for item in cal_data:
                    d = item.get("date", "")
                    if d >= today and not item.get("done"):
                        calendar_items.append({
                            "date": d, "topic": item.get("topic", ""),
                            "type": item.get("type", ""), "priority": item.get("priority", "normal"),
                        })
            # 类型覆盖
            type_coverage = {}
            for r in generated:
                type_coverage[r["content_type"]] = {"count": r["cnt"], "sample_topics": (r["topics"] or "").split("||")[:5]}
            # 选题缺口：日历中未生成的类型统计
            cal_types = {}
            for ci in calendar_items:
                t = ci.get("type", "unknown")
                cal_types[t] = cal_types.get(t, 0) + 1
            gaps = []
            for ct, cal_cnt in cal_types.items():
                gen_cnt = type_coverage.get(ct, {}).get("count", 0)
                if cal_cnt > gen_cnt:
                    gaps.append({"type": ct, "in_calendar": cal_cnt, "generated": gen_cnt, "gap": cal_cnt - gen_cnt})
            return {
                "type_coverage": type_coverage,
                "total_generated": len(all_topics),
                "calendar_pending": len(calendar_items),
                "gaps": gaps,
                "calendar_items": calendar_items[:20],
            }
        except Exception as e:
            logger.warning("[coverage] %s", e)
            return {"type_coverage": {}, "total_generated": 0, "calendar_pending": 0, "gaps": [], "calendar_items": []}
        finally:
            conn.close()

    @app.get("/api/stats/trends")
    async def stats_trends(days: int = 60):
        import sqlite3
        db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "memory", "conversations.db")
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            # 每日评分均值 + 数量
            daily = conn.execute("""
                SELECT date(created_at) as day,
                       ROUND(AVG(score), 1) as avg_score,
                       COUNT(*) as cnt,
                       SUM(tokens) as tokens
                FROM stats WHERE status='approved'
                  AND created_at >= date('now', ? || ' days')
                GROUP BY day ORDER BY day
            """, (f"-{days}",)).fetchall()
            # 按内容类型的评分趋势
            by_type = conn.execute("""
                SELECT content_type,
                       ROUND(AVG(score), 1) as avg_score,
                       COUNT(*) as cnt,
                       MAX(score) as best,
                       MIN(score) as worst
                FROM stats WHERE status='approved'
                  AND created_at >= date('now', ? || ' days')
                GROUP BY content_type
            """, (f"-{days}",)).fetchall()
            # 覆盖率：有内容的日期数 / 总工作日
            coverage = conn.execute("""
                SELECT COUNT(DISTINCT date(created_at)) as active_days,
                       (SELECT COUNT(*) FROM stats WHERE status='approved'
                        AND created_at >= date('now', ? || ' days')) as total
                FROM stats WHERE status='approved'
                  AND created_at >= date('now', ? || ' days')
            """, (f"-{days}", f"-{days}")).fetchone()
            # 评分分布
            distribution = conn.execute("""
                SELECT CASE
                    WHEN score >= 90 THEN '90-100'
                    WHEN score >= 80 THEN '80-89'
                    WHEN score >= 70 THEN '70-79'
                    ELSE '<70'
                END as bucket, COUNT(*) as cnt
                FROM stats WHERE status='approved'
                  AND created_at >= date('now', ? || ' days')
                GROUP BY bucket ORDER BY bucket
            """, (f"-{days}",)).fetchall()
            return {
                "daily": [dict(r) for r in daily],
                "by_type": [dict(r) for r in by_type],
                "coverage": {
                    "active_days": coverage["active_days"] if coverage else 0,
                    "total_articles": coverage["total"] if coverage else 0,
                },
                "distribution": [dict(r) for r in distribution],
            }
        except Exception as e:
            logger.warning("[trends] %s", e)
            return {"daily": [], "by_type": [], "coverage": {}, "distribution": []}
        finally:
            conn.close()
    # 会话（支持过滤）
    # ============================================================
    @app.get("/api/sessions")
    async def slist(content_type: str = Query(None), date_from: str = Query(None),
                    date_to: str = Query(None), q: str = Query(None)):
        return {"sessions": get_sessions(content_type=content_type, date_from=date_from, date_to=date_to, q=q)}

    @app.get("/api/sessions/{sid}")
    async def sget(sid: str):
        return {"messages": get_messages(sid)}

    @app.delete("/api/sessions/{sid}")
    async def sdel(sid: str):
        return {"ok": delete_session(sid)}

    # ============================================================
    # 生成
    # ============================================================

    @app.get("/api/export")
    async def export_approved(format: str = "txt"):
        import sqlite3
        import os as _os
        db_path = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "memory", "conversations.db")
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT s.title, m.body FROM sessions s JOIN messages m ON s.id=m.session_id AND m.role='agent' JOIN stats st ON s.title=st.topic AND s.created_at=st.created_at WHERE st.status='approved' ORDER BY s.created_at DESC LIMIT 100").fetchall()
        conn.close()
        if format == "txt":
            nl = chr(10)
            output = ""
            for r in rows:
                output += "=" * 60 + nl + (r["title"] or "") + nl + "=" * 60 + nl + nl
                output += (r["body"] or "") + nl + nl + nl
            from fastapi.responses import PlainTextResponse
            return PlainTextResponse(output)
        items = [{"title": r["title"], "body": r["body"][:500]} for r in rows]
        return {"count": len(items), "items": items}

    def _run_web_job(tid, topic, kw, model, ak, ab, od, fast):
        import threading
        stop_ev = threading.Event()
        with web_lock:
            if tid in web_tasks:
                web_tasks[tid]["_stop_event"] = stop_ev
        def p(msg):
            with web_lock:
                if tid in web_tasks:
                    web_tasks[tid]["stage"] = msg
                    web_tasks[tid]["log"] = web_tasks[tid].get("log", "") + msg + chr(10)
        try:
            r = run_pipeline(topic, kw, model, ak, ab, od, on_progress=p, fast=fast, stop_event=stop_ev, acquire_timeout=60)
            with web_lock:
                web_tasks[tid].update({"status": "done", "result": r})
        except InterruptedError:
            with web_lock:
                web_tasks[tid].update({"status": "stopped", "stage": "stopped by user"})
        except Exception as e:
            with web_lock:
                web_tasks[tid].update({"status": "error", "error": str(e)})

    @app.post("/api/generate")
    async def generate(topic: str = Form(...), keywords: str = Form(""), model: str = Form("deepseek-v4-flash"),
                       fast: str = Form("0")):
        tid = uuid.uuid4().hex[:12]
        kw = [k.strip() for k in keywords.split(",") if k.strip()] if keywords else []
        is_fast = fast == "1"
        with web_lock:
            web_tasks[tid] = {
                "id": tid, "topic": topic, "status": "pending",
                "stage": "已提交", "log": "", "created": datetime.now().isoformat(),
                "_stop_event": None,
            }
        threading.Thread(target=_run_web_job, args=(tid, topic, kw, model, api_key, api_base, output_dir, is_fast), daemon=True).start()
        return {"task_id": tid}

    @app.get("/api/task/{tid}")
    async def task(tid: str):
        with web_lock:
            t = web_tasks.get(tid, {}).copy()
        if not t:
            return JSONResponse({"error": "不存在"}, 404)
        r = {"task_id": tid, "status": t["status"], "stage": t.get("stage", ""), "log": t.get("log", "")}
        if t["status"] == "done":
            d = t["result"]
            r["result"] = {
                "title": d["final_title"], "body": d["final_body"],
                "score": d["evaluation"]["overall_score"],
                "scrape": d.get("scrape_status", ""),
                "elapsed": d["elapsed_seconds"],
                "content_type": d.get("content_type", ""),
            }
        if t["status"] == "error":
            r["error"] = t.get("error", "")
        return r

    @app.post("/api/chat")
    async def chat(topic: str = Form(...), keywords: str = Form(""), model: str = Form("deepseek-v4-flash"),
                   session_id: str = Form(""), feedback: str = Form(""), fast: str = Form("0")):
        kw = [k.strip() for k in keywords.split(",") if k.strip()] if keywords else [topic]
        if feedback:
            if "换类型" in feedback or "换角度" in feedback:
                kw = [f"内容类型:{feedback}"]
            elif "扩写" in feedback or "太短" in feedback:
                kw = kw + ["扩写", "详细"]
            else:
                # 自定义反馈文本：追加到关键词作为生成方向
                kw = [feedback] + kw
        import threading as _th; _sev = _th.Event(); r = run_pipeline(topic, kw, model, api_key, api_base, output_dir, fast=(fast == "1"), stop_event=_sev)
        from agents.classifier import detect_content_type
        ct = detect_content_type(topic, kw)
        return {
            "title": r["final_title"], "body": r["final_body"],
            "score": r["evaluation"]["overall_score"],
            "scrape": r.get("scrape_status", ""),
            "elapsed": r["elapsed_seconds"],
            "rag": "", "content_type": ct,
            "image_url": r.get("image_url", ""),
            "versions": r.get("versions", []),
            "meta_description": r.get("meta_description", ""),
            "seo_keywords": r.get("seo_keywords", []),
            "seo_titles": r.get("seo_titles", []),
            "social_summary": r.get("social_summary", ""),
            "email_version": r.get("email_version", ""),
        }
    
    @app.post("/api/chat/stream")
    async def chat_stream(topic: str = Form(...), keywords: str = Form(""), model: str = Form("deepseek-v4-flash"),
                          fast: str = Form("0"), feedback: str = Form("")):
        kw = [k.strip() for k in keywords.split(",") if k.strip()] if keywords else [topic]
        if feedback:
            if "换类型" in feedback or "换角度" in feedback:
                kw = [f"内容类型:{feedback}"]
            elif "扩写" in feedback or "太短" in feedback:
                kw = kw + ["扩写", "详细"]
            else:
                kw = [feedback] + kw
        is_fast = fast == "1"
        import threading
        tid = uuid.uuid4().hex[:12]
        stop_ev = threading.Event()
        with web_lock:
            web_tasks[tid] = {"id": tid, "status": "pending", "stage": "已提交", "_stop_event": stop_ev}
        import time as _time
        def gen():
            chunks = []
            pipeline_done = threading.Event()
            def cb(msg):
                chunks.append(msg)
            # Heartbeat: send keepalive every 10s to prevent connection timeout
            def heartbeat():
                while not pipeline_done.is_set():
                    pipeline_done.wait(10)
                    if not pipeline_done.is_set():
                        chunks.append(None)  # marker for heartbeat
            hb_thread = threading.Thread(target=heartbeat, daemon=True)
            hb_thread.start()
            try:
                r = run_pipeline(topic, kw, model, api_key, api_base, output_dir, on_progress=cb, fast=is_fast, stop_event=stop_ev, acquire_timeout=60)
            finally:
                pipeline_done.set()
            try:
                for c in chunks:
                    if c is None:
                        yield "data: " + json.dumps({"heartbeat": True}, ensure_ascii=False) + "\n\n"
                    else:
                        yield "data: " + json.dumps({"stage": c}, ensure_ascii=False) + "\n\n"
                if r.get("stopped"):
                    yield "data: " + json.dumps({"stopped": True, "stage": "已取消"}, ensure_ascii=False) + "\n\n"
                else:
                    yield "data: " + json.dumps({"done": True, "title": r["final_title"], "body": r["final_body"], "score": r["evaluation"]["overall_score"], "scrape": r.get("scrape_status", ""), "elapsed": r["elapsed_seconds"], "content_type": r.get("content_type", ""), "image_url": r.get("image_url", ""), "versions": r.get("versions", []), "meta_description": r.get("meta_description",""), "seo_keywords": r.get("seo_keywords",[]), "seo_titles": r.get("seo_titles",[]), "social_summary": r.get("social_summary",""), "email_version": r.get("email_version","")}, ensure_ascii=False) + "\n\n"
            except InterruptedError:
                yield "data: " + json.dumps({"stopped": True, "stage": "已取消"}, ensure_ascii=False) + "\n\n"
            finally:
                with web_lock:
                    if tid in web_tasks:
                        web_tasks[tid]["status"] = "done"
        return StreamingResponse(gen(), media_type="text/event-stream")

    @app.post("/api/stop")
    async def stop():
        with web_lock:
            for tid, t in web_tasks.items():
                if t.get("status") == "pending":
                    ev = t.get("_stop_event")
                    if ev:
                        ev.set()
                        t["status"] = "stopped"
                        t["stage"] = "stopped by user"
        return {"ok": True}

    # ============================================================
    # 定时
    # ============================================================
    @app.post("/api/schedule")
    async def sched(topic: str = Form(...), keywords: str = Form(""), model: str = Form("deepseek-v4-flash"),
                    fire_at: str = Form("")):
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.date import DateTrigger
        kw = [k.strip() for k in keywords.split(",") if k.strip()] if keywords else []
        if web_sched[0] is None:
            web_sched[0] = BackgroundScheduler(timezone=cfg.scheduler_timezone)
            web_sched[0].start()
        jid = f"web_{uuid.uuid4().hex[:8]}"
        def job():
            from infra.notify import notify_task_result
            try:
                r = run_pipeline(topic, kw, cfg.model_name or 'deepseek-v4-flash', api_key, api_base, output_dir)
                notify_task_result(topic, r["evaluation"]["overall_score"], r["elapsed_seconds"], True)
            except Exception as e:
                logger.error("[Sched] fail: %s", e)
                notify_task_result(topic, 0, str(e)[:50], False)
        web_sched[0].add_job(job, DateTrigger(run_date=fire_at, timezone=cfg.scheduler_timezone), id=jid, replace_existing=True)
        save_schedule(jid, topic, kw, model, "once", fire_at)
        return {"ok": True, "job_id": jid}

    @app.post("/api/schedule/cron")
    async def scron(topic: str = Form(...), keywords: str = Form(""), model: str = Form("deepseek-v4-flash"),
                    cron: str = Form("0 9 * * *")):
        from apscheduler.triggers.cron import CronTrigger
        kw = [k.strip() for k in keywords.split(",") if k.strip()] if keywords else []
        if web_sched[0] is None:
            web_sched[0] = BackgroundScheduler(timezone=cfg.scheduler_timezone)
            web_sched[0].start()
        jid = f"wc_{uuid.uuid4().hex[:8]}"
        def job():
            from infra.notify import notify_task_result
            try:
                r = run_pipeline(topic, kw, cfg.model_name or 'deepseek-v4-flash', api_key, api_base, output_dir)
                notify_task_result(topic, r["evaluation"]["overall_score"], r["elapsed_seconds"], True)
            except Exception as e:
                logger.error("[Cron] fail: %s", e)
                notify_task_result(topic, 0, str(e)[:50], False)
        web_sched[0].add_job(job, CronTrigger.from_crontab(cron, timezone=cfg.scheduler_timezone), id=jid, replace_existing=True)
        save_schedule(jid, topic, kw, model, "cron", cron)
        return {"ok": True, "job_id": jid}

    @app.get("/api/schedule/list")
    async def sjobs():
        jobs = []
        if web_sched[0]:
            for j in web_sched[0].get_jobs():
                jobs.append({"id": j.id, "next": str(j.next_run_time)[:19] if j.next_run_time else ""})
        return {"jobs": jobs}

    @app.post("/api/schedule/cancel")
    async def scancel(job_id: str = Form("")):
        if web_sched[0] and job_id:
            try: web_sched[0].remove_job(job_id)
            except: pass
        delete_schedule(job_id)
        return {"ok": True}

    # 恢复定时
    try:
        saved = get_schedules()
        if saved:
            from apscheduler.schedulers.background import BackgroundScheduler
            from apscheduler.triggers.date import DateTrigger
            from apscheduler.triggers.cron import CronTrigger
            if web_sched[0] is None:
                web_sched[0] = BackgroundScheduler(timezone=cfg.scheduler_timezone)
                web_sched[0].start()
            for r in saved:
                kw = [k.strip() for k in r["keywords"].split(",") if k.strip()]
                def mkjob(t, kw2, m, ak2, ab2):
                    def j(): run_pipeline(t, kw2, m, ak2, ab2, output_dir)
                    return j
                trigger = (
                    DateTrigger(run_date=r["trigger_value"], timezone=cfg.scheduler_timezone)
                    if r["trigger_type"] == "once"
                    else CronTrigger.from_crontab(r["trigger_value"], timezone=cfg.scheduler_timezone)
                )
                web_sched[0].add_job(mkjob(r["topic"], kw, r["model"], api_key, api_base), trigger, id=r["id"], replace_existing=True)
            logger.info("[Sched] 已恢复 %d 个定时任务", len(saved))
    except Exception as e:
        logger.warning("[Sched] 恢复失败: %s", e)

    @app.get("/api/review/{session_id}/body")
    async def review_body(session_id: str):
        msgs = get_messages(session_id)
        agent_msg = next((m for m in msgs if m["role"] == "agent"), None)
        if not agent_msg:
            return JSONResponse({"error": "not found"}, 404)
        return {"body": agent_msg.get("body", ""), "title": agent_msg.get("content", "")}

    # ============================================================
    # 知识库管理
    # ============================================================
    def _kb_dir():
        return os.path.join(DIR, "knowledge_base")

    @app.get("/api/knowledge")
    async def kb_list():
        """列出知识库文件，按目录分组"""
        import os as _os
        base = _kb_dir()
        if not _os.path.isdir(base):
            return {"categories": [], "files": []}
        categories = []
        files = []
        for root, dirs, fnames in _os.walk(base):
            rel = _os.path.relpath(root, base)
            if rel == ".":
                rel = ""
            for d in dirs:
                cat_path = _os.path.join(rel, d) if rel else d
                # count files in this category
                cat_files = [f for f in _os.listdir(_os.path.join(root, d)) if f.endswith(".md")]
                if cat_files:
                    categories.append({"name": cat_path, "file_count": len(cat_files)})
            for fn in fnames:
                if fn.endswith(".md"):
                    full = _os.path.join(root, fn)
                    try:
                        stat = _os.stat(full)
                        with open(full, "r", encoding="utf-8") as f:
                            first_line = f.readline().strip().lstrip("#").strip()
                    except Exception:
                        first_line = fn
                        stat = type('obj', (object,), {'st_size': 0, 'st_mtime': 0})()
                    files.append({
                        "category": rel,
                        "filename": fn,
                        "path": _os.path.join(rel, fn) if rel else fn,
                        "title": first_line[:60] or fn,
                        "size": stat.st_size,
                        "updated": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    })
        # Sort by category then filename
        files.sort(key=lambda x: (x["category"], x["filename"]))
        # Deduplicate categories
        seen = set()
        unique_cats = []
        for c in categories:
            if c["name"] not in seen:
                seen.add(c["name"])
                unique_cats.append(c)
        return {"categories": unique_cats, "files": files}

    @app.get("/api/knowledge/{path:path}")
    async def kb_read(path: str):
        full = os.path.join(_kb_dir(), path)
        full = os.path.normpath(full)
        if not full.startswith(os.path.normpath(_kb_dir())):
            return JSONResponse({"error": "路径非法"}, 403)
        if not os.path.isfile(full):
            return JSONResponse({"error": "文件不存在"}, 404)
        try:
            with open(full, "r", encoding="utf-8") as f:
                content = f.read()
            return {"path": path, "content": content, "size": len(content)}
        except Exception as e:
            return JSONResponse({"error": str(e)}, 500)

    @app.post("/api/knowledge")
    async def kb_save(path: str = Form(...), content: str = Form(...)):
        full = os.path.join(_kb_dir(), path)
        full = os.path.normpath(full)
        if not full.startswith(os.path.normpath(_kb_dir())):
            return JSONResponse({"error": "路径非法"}, 403)
        if not full.endswith(".md"):
            return JSONResponse({"error": "仅支持 .md 文件"}, 400)
        try:
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w", encoding="utf-8") as f:
                f.write(content)
            kb_reload()
            logger.info("[KB] saved %s (%d chars)", path, len(content))
            return {"ok": True, "path": path}
        except Exception as e:
            return JSONResponse({"error": str(e)}, 500)

    @app.delete("/api/knowledge")
    async def kb_delete(path: str = Form(...)):
        full = os.path.join(_kb_dir(), path)
        full = os.path.normpath(full)
        if not full.startswith(os.path.normpath(_kb_dir())):
            return JSONResponse({"error": "路径非法"}, 403)
        if not os.path.isfile(full):
            return JSONResponse({"error": "文件不存在"}, 404)
        try:
            os.remove(full)
            # Remove empty parent dirs
            parent = os.path.dirname(full)
            while parent != _kb_dir():
                try:
                    if not os.listdir(parent):
                        os.rmdir(parent)
                        parent = os.path.dirname(parent)
                    else:
                        break
                except Exception:
                    break
            kb_reload()
            logger.info("[KB] deleted %s", path)
            return {"ok": True}
        except Exception as e:
            return JSONResponse({"error": str(e)}, 500)

    return app


