# ============================================================
# infra/llm.py - LLM 调用基础设施
# ============================================================
import json, logging, os, re, time, urllib.request, urllib.error

logger = logging.getLogger("infra.llm")

MAX_RETRIES = 3
# Model pricing (yuan per million tokens)
MODEL_PRICING = {
    "deepseek-v4-flash": 1.0,
    "deepseek-v4-pro": 4.0,
    "deepseek-chat": 2.0,
    "deepseek-reasoner": 4.0,
    "gpt-4o": 36.0,
    "gpt-4o-mini": 2.0,
}


def estimate_cost(model_name, tokens):
    """Estimate cost in yuan. Falls back to 2.0/million for unknown models."""
    price = MODEL_PRICING.get(model_name, 2.0)
    return round(tokens / 1_000_000 * price, 2)

RETRY_BACKOFF = 2.0


def _chat_url(api_base):
    full = os.getenv("OPENAI_FULL_CHAT_URL", "")
    if full:
        return full
    path = os.getenv("OPENAI_CHAT_PATH", "/v1/chat/completions")
    return f"{api_base.rstrip('/')}{path}"


def _embed_url(api_base):
    path = os.getenv("OPENAI_EMBED_PATH", "/v1/embeddings")
    return f"{api_base.rstrip('/')}{path}"


def call_llm(system, user, model, api_key, api_base, temperature=0.5, max_tokens=4096, timeout=300):
    url = _chat_url(api_base)
    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            body = json.dumps({
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user}
                ],
                "temperature": temperature,
                "max_tokens": max_tokens
            }).encode("utf-8")
            req = urllib.request.Request(
                url, data=body,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json; charset=utf-8"}
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code == 404:
                break
            if attempt < MAX_RETRIES:
                delay = RETRY_BACKOFF ** attempt
                logger.warning("[LLM] HTTP %d on attempt %d/%d, retrying in %.1fs", e.code, attempt, MAX_RETRIES, delay)
                time.sleep(delay)
        except Exception as e:
            last_err = e
            if attempt < MAX_RETRIES:
                delay = RETRY_BACKOFF ** attempt
                logger.warning("[LLM] attempt %d/%d failed, retrying in %.1fs: %s", attempt, MAX_RETRIES, delay, e)
                time.sleep(delay)

    raise RuntimeError(
        f"[LLM] {MAX_RETRIES} attempts all failed.\n"
        f"  Full URL: {url}\n"
        f"  Model: {model}\n"
        f"  Last error: {last_err}\n"
        f"  \n"
        f"  检查：OPENAI_API_BASE={api_base}, OPENAI_CHAT_PATH={os.getenv('OPENAI_CHAT_PATH', '/v1/chat/completions')}"
    ) from last_err


def call_embedding(text, api_key, api_base, model="text-embedding-3-small", timeout=30):
    url = _embed_url(api_base)
    try:
        body = json.dumps({"model": model, "input": text}).encode("utf-8")
        req = urllib.request.Request(
            url, data=body,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json; charset=utf-8"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))["data"][0]["embedding"]
    except Exception as e:
        logger.warning("[EMBED] failed: %s", e)
        return None


def extract_json(text):
    if not text:
        return {}
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass
    m = re.search(r'`(?:json)?\s*\n?(.*?)\n?`', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            pass
    m = re.search(r'\{.*\}', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass
    logger.warning("[JSON] failed to extract from: %.100s...", text)
    return {}


def clean_text(text):
    if not text:
        return ""
    return re.sub(r'\n{3,}', '\n\n', text.replace("\r\n", "\n").replace("\r", "\n").strip())
