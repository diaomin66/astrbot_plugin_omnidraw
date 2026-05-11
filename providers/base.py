"""图片 Provider 基类。"""
import aiohttp
import base64
import mimetypes
import os
import threading
from abc import ABC, abstractmethod
from typing import Any, Dict, Iterable, Optional, List
from astrbot.api import logger
from ..models import ProviderConfig

_KEY_ROTATION_LOCK = threading.Lock()
_KEY_ROTATION_INDEX: Dict[str, int] = {}


def normalize_base_url(base_url: str) -> str:
    return str(base_url or "").rstrip("/")


def _has_endpoint_path(base_url: str, endpoint_suffixes: Iterable[str]) -> bool:
    lowered = base_url.lower()
    return any(lowered.endswith(suffix) for suffix in endpoint_suffixes)


def _replace_endpoint_path(base_url: str, endpoint_suffix: str, replacement_suffix: str) -> str:
    if base_url.lower().endswith(endpoint_suffix):
        return base_url[: -len(endpoint_suffix)] + replacement_suffix
    return base_url


def strip_known_endpoint_path(base_url: str) -> str:
    base_url = normalize_base_url(base_url)
    for suffix in (
        "/chat/completions",
        "/responses",
        "/images/generations",
        "/images/edits",
        "/videos/generations",
    ):
        if base_url.lower().endswith(suffix):
            return base_url[: -len(suffix)]
    return base_url


def build_chat_completions_endpoint(base_url: str) -> str:
    base_url = normalize_base_url(base_url)
    if not base_url:
        return ""
    if _has_endpoint_path(base_url, ["/chat/completions"]):
        return base_url
    base_url = _replace_endpoint_path(base_url, "/responses", "/chat/completions")
    if _has_endpoint_path(base_url, ["/chat/completions"]):
        return base_url
    return f"{base_url}/chat/completions" if base_url.endswith("/v1") else f"{base_url}/v1/chat/completions"


def build_image_generations_endpoint(base_url: str) -> str:
    base_url = normalize_base_url(base_url)
    if not base_url:
        return ""
    if _has_endpoint_path(base_url, ["/images/generations"]):
        return base_url
    base_url = _replace_endpoint_path(base_url, "/images/edits", "/images/generations")
    if _has_endpoint_path(base_url, ["/images/generations"]):
        return base_url
    return f"{base_url}/images/generations"


def build_image_edits_endpoint(base_url: str) -> str:
    base_url = normalize_base_url(base_url)
    if not base_url:
        return ""
    if _has_endpoint_path(base_url, ["/images/generations", "/images/edits"]):
        return base_url
    return f"{base_url}/images/edits"


def build_video_generations_endpoint(base_url: str) -> str:
    base_url = normalize_base_url(base_url)
    if not base_url:
        return ""
    if _has_endpoint_path(base_url, ["/videos/generations"]):
        return base_url
    return f"{base_url}/videos/generations"


def next_api_key(provider_id: str, api_keys: List[str]) -> str:
    keys = [str(key).strip() for key in api_keys if str(key).strip()]
    if not provider_id or not keys:
        return ""
    with _KEY_ROTATION_LOCK:
        idx = _KEY_ROTATION_INDEX.get(provider_id, 0)
        key = keys[idx % len(keys)]
        _KEY_ROTATION_INDEX[provider_id] = (idx + 1) % len(keys)
        return key


def guess_image_content_type(image_path_or_url: str, content_type: str = "", fallback: str = "image/png") -> str:
    media_type = str(content_type or "").strip().split(";", 1)[0].strip()
    if media_type.startswith("image/"):
        return media_type
    source = str(image_path_or_url or "")
    lowered = source.lower()
    if lowered.startswith("data:"):
        header = source.split(",", 1)[0]
        media_type = header[5:].split(";", 1)[0].strip()
        if media_type.startswith("image/"):
            return media_type
    if lowered.endswith(".jpg") or lowered.endswith(".jpeg"):
        return "image/jpeg"
    if lowered.endswith(".webp"):
        return "image/webp"
    if lowered.endswith(".gif"):
        return "image/gif"
    if lowered.endswith(".avif"):
        return "image/avif"
    if lowered.endswith(".bmp"):
        return "image/bmp"
    if lowered.endswith(".tif") or lowered.endswith(".tiff"):
        return "image/tiff"
    guessed = mimetypes.guess_type(source)[0] or ""
    return guessed if guessed.startswith("image/") else fallback


class BaseProvider(ABC):
    def __init__(self, config: ProviderConfig, session: aiohttp.ClientSession):
        self.config = config
        self.session = session
        self._api_keys = [str(key).strip() for key in self.config.api_keys if str(key).strip()]

    def get_current_key(self) -> str:
        return next_api_key(self.config.id, self._api_keys)

    def encode_local_image_to_base64(self, image_path: str) -> Optional[str]:
        """将本地图片文件转为 API 兼容的 Base64 字符串"""
        if not image_path or not os.path.exists(image_path):
            return None

        logger.info(f"[{self.config.id}] 正在将本地参考图转为 Base64: {image_path}")
        try:
            with open(image_path, "rb") as image_file:
                encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
                mime_type = guess_image_content_type(image_path)
                return f"data:{mime_type};base64,{encoded_string}"
        except Exception as e:
            logger.error(f"❌ 读取本地图片失败: {e}")
            return None

    def get_reference_images(self, **kwargs: Any) -> List[str]:
        refs: List[str] = []
        for key in ("user_refs", "persona_refs"):
            value = kwargs.get(key)
            if isinstance(value, (list, tuple)):
                refs.extend(str(item) for item in value if item)

        for key in ("user_ref", "persona_ref"):
            value = kwargs.get(key)
            if value:
                refs.append(str(value))

        seen = set()
        return [ref for ref in refs if not (ref in seen or seen.add(ref))]

    @abstractmethod
    async def generate_image(self, prompt: str, **kwargs: Any) -> str:
        pass
