# ============================================================
# scheduler/scheduler.py — 定时调度
# ============================================================
import logging, sys, threading

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.date import DateTrigger

from config import get_config
from pipeline import run_pipeline

logger = logging.getLogger("scheduler")


def run_schedule(topic, keywords, model, cron=None, interval=None, at=None):
    cfg = get_config()
    api_key = cfg.api_key
    api_base = cfg.api_base
    output_dir = cfg.output_dir

    def job():
        from infra.notify import notify_task_result
        try:
            r = run_pipeline(topic, keywords, model, api_key, api_base, output_dir)
            notify_task_result(topic, r["evaluation"]["overall_score"], r["elapsed_seconds"], True)
        except Exception as e:
            logger.error("[定时] 失败: %s", e)
            notify_task_result(topic, 0, str(e)[:50], False)

    sched = BackgroundScheduler(timezone=cfg.scheduler_timezone)

    if at:
        trigger = DateTrigger(run_date=at, timezone=cfg.scheduler_timezone)
        desc = f"指定: {at}"
    elif cron:
        trigger = CronTrigger.from_crontab(cron, timezone=cfg.scheduler_timezone)
        desc = f"cron: {cron}"
    else:
        trigger = IntervalTrigger(minutes=interval or 60)
        desc = f"每{interval}分钟"

    sched.add_job(job, trigger=trigger, id="auto", replace_existing=True)
    sched.start()
    print(f"\n  定时: {desc}\n  Ctrl+C 停止\n", flush=True)

    ev = threading.Event()
    try:
        ev.wait()
    except KeyboardInterrupt:
        pass
    finally:
        print("\n  已停止")
        sched.shutdown(wait=False)
