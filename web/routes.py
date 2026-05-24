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
            return {"items": []}
        with open(cal_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or []
        from datetime import datetime, timedelta
        today = datetime.now().strftime("%Y-%m-%d")
        cutoff = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
        items = []
        for item in data:
            d = item.get("date", "")
            if today <= d <= cutoff:
                items.append({
                    "date": d, "topic": item.get("topic",""),
                    "type": item.get("type",""), "keywords": item.get("keywords",[]),
                    "priority": item.get("priority","normal"),
                    "done": item.get("done", False),
                })
        items.sort(key=lambda x: x["date"])
        return {"items": items}

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
                      keywords: str = Form("")):
        kw = [k.strip() for k in keywords.split(",") if k.strip()]
        data = _cal_read()
        data.append({"date": date, "topic": topic, "type": type,
                     "keywords": kw, "priority": priority, "done": False})
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
    async def review_approve(session_id: str = Form(...)):
        ok = approve_result(session_id)
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
        def job():
            try:
                run_pipeline(topic, kw, cfg.model_name or 'deepseek-v4-flash', api_key, api_base, output_dir)
            except Exception as e:
                logger.error("[Regen] fail: %s", e)
        threading.Thread(target=job, daemon=True).start()
        return {"ok": True, "task_id": tid}

    @app.post("/api/review/reject")
    async def review_reject(session_id: str = Form(...), reason: str = Form("")):
        ok = reject_result(session_id, reason)
        return {"ok": ok}

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

    @app.get("/api/performance/stats")
    async def perf_stats():
        return {"by_type": get_performance_stats()}

    # ============================================================
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
    def _run_web_job(tid, topic, kw, model, ak, ab, od, fast):
        def p(msg):
            with web_lock:
                if tid in web_tasks:
                    web_tasks[tid]["stage"] = msg
                    web_tasks[tid]["log"] = web_tasks[tid].get("log", "") + msg + "\n"
        try:
            r = run_pipeline(topic, kw, model, ak, ab, od, on_progress=p, fast=fast)
            with web_lock:
                web_tasks[tid].update({"status": "done", "result": r})
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
        r = run_pipeline(topic, kw, model, api_key, api_base, output_dir, fast=(fast == "1"))
        from agents.classifier import detect_content_type
        ct = detect_content_type(topic, kw)
        return {
            "title": r["final_title"], "body": r["final_body"],
            "score": r["evaluation"]["overall_score"],
            "scrape": r.get("scrape_status", ""),
            "elapsed": r["elapsed_seconds"],
            "rag": "", "content_type": ct,
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
        def gen():
            chunks = []
            def cb(msg):
                chunks.append(msg)
            r = run_pipeline(topic, kw, model, api_key, api_base, output_dir, on_progress=cb, fast=is_fast)
            for c in chunks:
                yield f"data: {json.dumps({'stage': c})}\n\n"
            yield f"data: {json.dumps({'done': True, 'title': r['final_title'], 'body': r['final_body'], 'score': r['evaluation']['overall_score'], 'scrape': r.get('scrape_status', ''), 'elapsed': r['elapsed_seconds'], 'content_type': r.get('content_type', '')})}\n\n"
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

    return app
    @app.get("/api/review/{session_id}/body")
    async def review_body(session_id: str):
        msgs = get_messages(session_id)
        agent_msg = next((m for m in msgs if m["role"] == "agent"), None)
        if not agent_msg:
            return JSONResponse({"error": "not found"}, 404)
        return {"body": agent_msg.get("body", ""), "title": agent_msg.get("content", "")}


