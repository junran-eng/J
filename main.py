# ======================================================================
# main.py — AI 智能推广工作流 v5.0
# ======================================================================
import argparse, io, logging, logging.handlers, os, sys

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "run.log")
_fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
_fh = logging.handlers.RotatingFileHandler(LOG_FILE, encoding="utf-8", maxBytes=10*1024*1024, backupCount=3); _fh.setFormatter(_fmt)
_sh = logging.StreamHandler(io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")); _sh.setFormatter(_fmt)
_root = logging.getLogger(); _root.setLevel(logging.INFO); _root.handlers.clear(); _root.addHandler(_fh); _root.addHandler(_sh)
log = logging.getLogger("main")
print(f"\n>>> 日志: {LOG_FILE}", flush=True)
log.info("========== 启动 ==========")

env_path = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(env_path):
    with open(env_path, "r", encoding="utf-8-sig") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            line = line.replace(" ", "").replace("==", "=")
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            v = v.strip().strip('"').strip("'")
            if k.isascii() and k.isupper():
                os.environ.setdefault(k, v)


# ---- 启动时 SQLite 维护 ----
from infra.sqlite_utils import vacuum
from infra.memory import get_db_path as mem_db_path
from infra.rag import get_db_path as rag_db_path
vacuum(mem_db_path())
vacuum(rag_db_path())
from config import get_config
from infra.knowledge_base import load_knowledge_base

load_knowledge_base()


def load_calendar():
    import yaml
    SKILL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "jikang-marketing-skill")
    cal_path = os.path.join(SKILL_DIR, "assets", "content_calendar.yaml")
    if not os.path.exists(cal_path): return []
    try:
        with open(cal_path, "r", encoding="utf-8") as f: data = yaml.safe_load(f)
    except: return []
    from datetime import datetime
    today = datetime.now().strftime("%Y-%m-%d")
    tasks = []
    for item in data or []:
        if item.get("date") == today and not item.get("done"):
            tasks.append({"topic":item.get("topic",""),"type":item.get("type","tech"),
                          "keywords":item.get("keywords",[]),"priority":item.get("priority","normal")})
    return sorted(tasks, key=lambda x: 0 if x["priority"]=="high" else 1)


def main():
    cfg = get_config()
    parser = argparse.ArgumentParser(description="AI 智能推广工作流 v5.0")
    parser.add_argument("--web", action="store_true")
    parser.add_argument("--port", type=int, default=cfg.web_port)
    parser.add_argument("--chat", action="store_true")
    parser.add_argument("--auto", action="store_true", help="自动执行内容日历今日任务")
    parser.add_argument("--fast", action="store_true", help="快速模式：单版本生成，省 2/3 LLM 调用")
    parser.add_argument("--classify-llm", action="store_true", help="使用 LLM 精确分类内容类型")
    parser.add_argument("--schedule", action="store_true")
    parser.add_argument("--model", type=str, default=cfg.model_name or None)
    parser.add_argument("--topic","-t",type=str,default="")
    parser.add_argument("--keywords","-k",type=str,default="")
    parser.add_argument("--output-dir","-o",type=str,default=cfg.output_dir)
    parser.add_argument("--cron",type=str,default=None)
    parser.add_argument("--interval",type=int,default=None)
    parser.add_argument("--at",type=str,default=None)
    args = parser.parse_args()

    if args.web:
        import uvicorn
        from web.routes import create_app
        app = create_app()
        print(f"\n  Web: http://localhost:{args.port}\n", flush=True)
        ulog = logging.getLogger("uvicorn"); ulog.handlers.clear(); ulog.addHandler(_fh); ulog.addHandler(_sh); ulog.setLevel(logging.WARNING)
        uvicorn.run(app, host="0.0.0.0", port=args.port, log_config=None)
        sys.exit(0)

    if args.auto:
        if not cfg.model_name and not args.model:
            print("错误: 未配置模型名。请在 .env 中设置 LLM_MODEL 或使用 --model 参数")
            sys.exit(1)
        model = args.model or cfg.model_name
        from pipeline import run_pipeline
        api_key = cfg.api_key; api_base = cfg.api_base
        if not api_key: print("错误: 未配置 OPENAI_API_KEY"); sys.exit(1)
        tasks = load_calendar()
        if not tasks:
            from datetime import datetime
            print(f"  今日({datetime.now().strftime('%Y-%m-%d')})无日历任务\n", flush=True); sys.exit(0)
        print(f"  今日日历任务: {len(tasks)}个\n", flush=True)
        for i, t in enumerate(tasks, 1):
            print(f"  [{i}/{len(tasks)}] {t['topic'][:40]}... (优先级:{t['priority']})", flush=True)
            r = run_pipeline(t["topic"], t.get("keywords",[]), model, api_key, api_base, args.output_dir, fast=args.fast)
            print(f"  评分: {r['evaluation']['overall_score']}/100")
            if r.get("image_url"): print(f"  封面图: {r['image_url']}")
            print()
        print("  全部完成\n", flush=True); sys.exit(0)

    if args.chat:
        from cli.chat import run_chat
        run_chat(model=args.model, fast=args.fast)
        sys.exit(0)

    if not args.topic: parser.error("需要 --topic")


    if not cfg.model_name and not args.model:
        print("错误: 未配置模型名。请在 .env 中设置 LLM_MODEL 或使用 --model 参数")
        sys.exit(1)
    
    from pipeline import run_pipeline
    model = args.model or cfg.model_name
    api_key = cfg.api_key; api_base = cfg.api_base
    if not api_key: print("错误: 未配置 OPENAI_API_KEY"); sys.exit(1)
    kw = [k.strip() for k in args.keywords.split(",") if k.strip()] if args.keywords else []

    # LLM 分类（可选，结果传入 pipeline）
    forced_ct = None
    if args.classify_llm:
        from agents.classifier import classify_with_llm
        from infra.llm import call_llm
        def llm_fn(s, u): return call_llm(s, u, args.model, api_key, api_base)
        forced_ct = classify_with_llm(args.topic, kw, llm_fn)
        print(f"  [LLM分类] {forced_ct}", flush=True)

    if args.schedule:
        from scheduler.scheduler import run_schedule
        run_schedule(args.topic, kw, args.model, cron=args.cron, interval=args.interval, at=args.at)
    else:
        print(f"\n  单次: {args.topic} {'(快速)' if args.fast else ''}\n", flush=True)
        r = run_pipeline(args.topic, kw, args.model, api_key, api_base, args.output_dir, fast=args.fast, content_type=forced_ct)
        print(f"  标题: {r['final_title']}\n  字数: {len(r['final_body'])}  评分: {r['evaluation']['overall_score']}/100\n  抓取: {r.get('scrape_status','')}  耗时: {r['elapsed_seconds']}s\n")


if __name__ == "__main__":
    main()








