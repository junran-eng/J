# ============================================================
# infra/scraper.py — 智能网页抓取（配置驱动 + 代码兜底）
# ============================================================
import logging, os, re, ssl, sys, urllib.request, urllib.error, urllib.parse

logger = logging.getLogger("infra.scraper")

TIMEOUT = 15
MAX_TEXT_LEN = 10000
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

try:
    from bs4 import BeautifulSoup
    _has_bs4 = True
except ImportError:
    _has_bs4 = False


try:
    from playwright.sync_api import sync_playwright
    _has_playwright = True
except (ImportError, Exception):
    _has_playwright = False

_PLAYWRIGHT_TIMEOUT = int(os.getenv("SCRAPER_PLAYWRIGHT_TIMEOUT", "20"))


# ---- 内置默认源（配置读取失败时兜底） ----
_DEFAULT_SOURCES = [
    {"name": "吉康官网", "urls": [
        {"type": "search", "url": "https://www.gdjikang.com/?s={query}"},
        {"type": "news", "url": "https://www.gdjikang.com/news"},
        {"type": "home", "url": "https://www.gdjikang.com"}]},
    {"name": "广东环保协会", "urls": [
        {"type": "search", "url": "http://www.gdepi.com/?s={query}"},
        {"type": "news", "url": "http://www.gdepi.com/index.php?c=article&a=list&catid=2"},
        {"type": "home", "url": "http://www.gdepi.com"}]},
    {"name": "热泵专委会", "urls": [
        {"type": "search", "url": "https://www.chpa.org.cn/?s={query}"},
        {"type": "news", "url": "https://www.chpa.org.cn/news"},
        {"type": "home", "url": "https://www.chpa.org.cn"}]},
    {"name": "工信部", "urls": [
        {"type": "search", "url": "https://sousuo.www.gov.cn/s?q={query}+site:miit.gov.cn"},
        {"type": "search", "url": "https://www.miit.gov.cn/search/index.html?searchword={query}"},
        {"type": "news", "url": "https://www.miit.gov.cn/xwdt/index.html"},
        {"type": "home", "url": "https://www.miit.gov.cn"}]},
    {"name": "环保产业协会", "urls": [
        {"type": "search", "url": "http://www.caepi.org.cn/?s={query}"},
        {"type": "search", "url": "http://www.caepi.org.cn/search.jspx?q={query}"},
        {"type": "news", "url": "http://www.caepi.org.cn/epaspc/web/news_list.asp"},
        {"type": "home", "url": "http://www.caepi.org.cn"}]},
    {"name": "生态环境部", "urls": [
        {"type": "search", "url": "https://sousuo.mee.gov.cn/s?q={query}"},
        {"type": "search", "url": "https://www.mee.gov.cn/searchnew/?searchword={query}"},
        {"type": "news", "url": "https://www.mee.gov.cn/ywdt/"},
        {"type": "home", "url": "https://www.mee.gov.cn"}]},
    {"name": "国家能源局", "urls": [
        {"type": "search", "url": "https://sousuo.nea.gov.cn/s?q={query}"},
        {"type": "search", "url": "https://www.nea.gov.cn/search/index.html?q={query}"},
        {"type": "news", "url": "https://www.nea.gov.cn/xwzx/index.htm"},
        {"type": "home", "url": "https://www.nea.gov.cn"}]},
]


def _load_sources_from_config():
    """从 config.yaml 读取爬虫源配置，失败则返回内置默认值"""
    try:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        cfg_path = os.path.join(base, "jikang-marketing-skill", "assets", "config.yaml")
        if not os.path.exists(cfg_path):
            return _DEFAULT_SOURCES

        import yaml
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)

        scraping = cfg.get("scraping", {}) if cfg else {}
        sources = scraping.get("sources", []) if scraping else []
        if sources:
            logger.info("[scraper] loaded %d sources from config.yaml", len(sources))
            return sources
    except Exception as e:
        logger.debug("[scraper] config.yaml read failed, using defaults: %s", e)

    return _DEFAULT_SOURCES


def _fetch_url_playwright(url, timeout=_PLAYWRIGHT_TIMEOUT):
    """Fallback: render page with headless Chromium, then extract text"""
    if not _has_playwright:
        raise RuntimeError('playwright not installed')
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(url, timeout=timeout * 1000, wait_until='domcontentloaded')
            html = page.content()
            return html.encode('utf-8')
        finally:
            browser.close()


def _fetch_url(url, timeout=TIMEOUT):
    ctx = ssl.create_default_context()
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            return resp.read()
    except (ssl.SSLError, ssl.SSLCertVerificationError) as e:
        logger.debug("[scrape] SSL error for %s, retrying with verify disabled: %s", url, str(e)[:80])
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            return resp.read()


def _extract_text(html_bytes):
    try:
        raw = html_bytes.decode("utf-8", errors="replace")
    except Exception:
        return ""
    if _has_bs4:
        soup = BeautifulSoup(raw, "lxml")
        for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
            tag.decompose()
        text = soup.get_text(separator="\n")
        lines = [ln.strip() for ln in text.splitlines() if len(ln.strip()) > 10]
        return "\n".join(lines)[:MAX_TEXT_LEN]
    else:
        text = re.sub(r'<script[^>]*>.*?</script>', '', raw, flags=re.DOTALL)
        text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
        text = re.sub(r'<[^>]+>', '\n', text)
        text = re.sub(r'&[a-z]+;', ' ', text)
        lines = [ln.strip() for ln in text.splitlines() if len(ln.strip()) > 10]
        return "\n".join(lines)[:MAX_TEXT_LEN]


def scrape_web(topic, keywords, timeout=TIMEOUT):
    sources = _load_sources_from_config()
    q = urllib.parse.quote(" ".join([topic] + keywords[:2]))
    result = {}

    for src in sources:
        name = src.get("name", "unknown")
        text = ""
        raw_len = 0
        used_type = ""

        for entry in src.get("urls", []):
            url_tpl = entry.get("url", "")
            url_type = entry.get("type", "unknown")
            try:
                url = url_tpl.format(query=q)
            except KeyError:
                url = url_tpl

            try:
                raw = _fetch_url(url, timeout)
                text = _extract_text(raw)
                raw_len = len(raw)
                used_type = url_type
                if len(text) > 300:
                    break
            except Exception as e:
                logger.debug("[scrape] %s %s urllib fail: %s", name, url_type, str(e)[:80])
                if _has_playwright:
                    try:
                        logger.debug("[scrape] %s %s trying Playwright...", name, url_type)
                        raw = _fetch_url_playwright(url, _PLAYWRIGHT_TIMEOUT)
                        text = _extract_text(raw)
                        raw_len = len(raw)
                        used_type = url_type + '(pw)'
                        if len(text) > 300:
                            break
                    except Exception as e2:
                        logger.debug("[scrape] %s %s playwright fail: %s", name, url_type, str(e2)[:80])
                continue

        if len(text) > 300:
            result[name] = ("成功", f"[{name}] {raw_len}字节 via {used_type}")
            logger.info("[scrape] ok %-10s %6d bytes via %s", name, raw_len, used_type)
        else:
            result[name] = ("失败", "所有URL均无有效内容")
            logger.warning("[scrape] fail %s: all URLs exhausted", name)

    return result
