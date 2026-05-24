# ============================================================
# cli/chat.py — CLI 对话模式（支持 --fast）
# ============================================================
import logging, sys

from config import get_config
from pipeline import run_pipeline

logger = logging.getLogger("cli")


def run_chat(model=None, fast=False):
    cfg = get_config()
    api_key = cfg.api_key
    api_base = cfg.api_base
    output_dir = cfg.output_dir
    cmodel = model or cfg.model_name

    if not api_key:
        print("错误: 未配置 OPENAI_API_KEY")
        sys.exit(1)

    mode_tag = " (快速)" if fast else ""
    print(f"\n  对话模式{mode_tag}。主题/关键词/模型可输入，/quit 退出\n", flush=True)
    ctopic = ""
    ckw = []

    while True:
        try:
            ti = input("  主题: ").strip()
            if ti in ("/quit", "/exit"):
                break

            if ctopic and any(s in ti for s in ["扩写", "太短", "换角度", "换类型"]):
                if "换类型" in ti:
                    ckw = [f"内容类型:{ti}"]
                elif "扩写" in ti:
                    ckw = ckw + ["扩写", "详细"]
                print("  [反馈] 重新生成...", flush=True)
            else:
                ctopic = ti
                kwi = input("  关键词: ").strip()
                ckw = [k.strip() for k in kwi.split(",") if k.strip()] if kwi else [ctopic]
                mi = input(f"  模型 [{cmodel}]: ").strip()
                if mi:
                    cmodel = mi
                print(f"  [开始] {ctopic}", flush=True)

            r = run_pipeline(ctopic, ckw, cmodel, api_key, api_base, output_dir, fast=fast)
            print(
                f"  标题: {r['final_title']}\n"
                f"  字数: {len(r['final_body'])}  评分: {r['evaluation']['overall_score']}/100\n"
                f"  反馈: 扩写/换角度/太短 /quit\n",
                flush=True,
            )
        except (EOFError, KeyboardInterrupt):
            break

    print("\n  结束\n")
