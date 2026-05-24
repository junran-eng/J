# ============================================================
# config.py — 全局配置中心
# ============================================================
import os
from dataclasses import dataclass

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


@dataclass
class Config:
    model_name: str = os.getenv("LLM_MODEL", "")
    api_key: str = os.getenv("OPENAI_API_KEY", os.getenv("DEEPSEEK_API_KEY", ""))
    api_base: str = os.getenv("OPENAI_API_BASE", os.getenv("DEEPSEEK_API_BASE", "https://api.openai.com/v1"))
    output_dir: str = os.getenv("OUTPUT_DIR", "./outputs")
    web_port: int = int(os.getenv("WEB_PORT", "8080"))
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    output_max_files: int = int(os.getenv("OUTPUT_MAX_FILES", "30"))
    scheduler_timezone: str = os.getenv("SCHEDULER_TIMEZONE", "Asia/Shanghai")

    critic_pass_threshold: int = 80
    max_revision_rounds: int = 3
    perf_boost_weight: float = float(os.getenv("PERF_BOOST_WEIGHT", "0.15"))
    min_content_length: int = 500


_config: Config | None = None


def get_config() -> Config:
    global _config
    if _config is None:
        _config = Config()
    return _config

def validate_config():
    """?????????? {ok, issues}"""
    cfg = get_config()
    issues = []
    if not cfg.model_name:
        issues.append("LLM_MODEL ?????? .env ???????? deepseek-v4-flash?")
    if not cfg.api_key:
        issues.append("OPENAI_API_KEY ?????? .env ??? API Key?")
    if not cfg.api_base:
        issues.append("OPENAI_API_BASE ???")
    return {"ok": len(issues) == 0, "issues": issues, "model": cfg.model_name or "(???)", "api_base": cfg.api_base}

