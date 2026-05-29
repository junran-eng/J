# ============================================================
# infra/image_gen.py — 图片生成抽象（Provider 模式）
# ============================================================
import json, logging, os, urllib.request
from datetime import datetime
from abc import ABC, abstractmethod

logger = logging.getLogger("infra.image_gen")


class ImageProvider(ABC):
    @abstractmethod
    def generate(self, prompt):
        """返回图片 URL 或 None"""
        ...

    def download(self, url, output_dir):
        """下载到本地，返回路径或 None"""
        try:
            fn = os.path.join(output_dir, f"封面_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
            with urllib.request.urlopen(url, timeout=60) as src:
                with open(fn, "wb") as dst:
                    dst.write(src.read())
            return fn
        except Exception as e:
            logger.warning("[IMAGE] download failed: %s", e)
            return None


class DalleProvider(ImageProvider):
    def __init__(self, api_key, model="dall-e-3", size="1024x1024"):
        self.api_key = api_key
        self.model = model
        self.size = size

    def generate(self, prompt):
        body = json.dumps({
            "model": self.model, "prompt": prompt, "n": 1, "size": self.size
        }).encode("utf-8")
        req = urllib.request.Request(
            "https://api.openai.com/v1/images/generations", data=body,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json; charset=utf-8"}
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))["data"][0]["url"]


class PlaceholderProvider(ImageProvider):
    """占位 provider：不生成图片，返回 None"""
    def generate(self, prompt):
        logger.info("[IMAGE] placeholder: skipping generation for prompt='%.60s...'", prompt)
        return None


# ---- 全局工厂 ----
import threading as _threading
_provider_cache = None
_provider_lock = _threading.Lock()


def get_provider(api_key, force=None):
    """获取图片 provider，优先 DALL-E，无 key 则占位"""
    global _provider_cache
    with _provider_lock:
        if _provider_cache is not None and force is None:
            return _provider_cache

        if force == "dalle" or (api_key and api_key.startswith("sk-")):
            _provider_cache = DalleProvider(api_key)
        else:
            _provider_cache = PlaceholderProvider()

        return _provider_cache
