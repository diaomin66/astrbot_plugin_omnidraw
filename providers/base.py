"""图片 Provider 基类。"""
import aiohttp
import asyncio
import base64
import json
import mimetypes
import os
import re
import threading
from abc import ABC, abstractmethod
from typing import Any, Dict, Iterable, List
from urllib.parse import parse_qsl, urljoin, urlparse, urlunparse
from ..models import ProviderConfig

_KEY_ROTATION_LOCK = threading.Lock()
_KEY_ROTATION_INDEX: Dict[str, int] = {}

# 参考图下载默认超时（秒）与浏览器 UA（对抗防盗链）。
REF_DOWNLOAD_TIMEOUT = 20.0
REF_DOWNLOAD_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}


def _read_file_bytes(path: str) -> bytes:
    with open(path, "rb") as image_file:
        return image_file.read()


def _encode_base64(data: bytes) -> str:
    return base64.b64encode(data).decode("utf-8")


def normalize_base_url(base_url: str) -> str:
    return str(base_url or "").rstrip("/")


def is_complete_endpoint_url(base_url: str) -> bool:
    """Return True only for full URLs that point at a concrete request path."""
    parsed = urlparse(normalize_base_url(base_url))
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    path = parsed.path.rstrip("/")
    if not path:
        return False
    segments = [segment for segment in path.split("/") if segment]
    if not segments:
        return False
    version_like = re.compile(r"^v\d+(?:beta\d*)?$", re.IGNORECASE)
    if len(segments) == 1 and version_like.fullmatch(segments[0]):
        return False
    if segments[-1].lower() == "api" or version_like.fullmatch(segments[-1]):
        return False
    return True


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


def response_base_url(base_url: str) -> str:
    api_root = strip_known_endpoint_path(base_url)
    return api_root[:-3] if api_root.endswith("/v1") else api_root


def resolve_response_url(value: str, base_url: str) -> str:
    image_ref = str(value or "").strip()
    if image_ref.startswith("http") or image_ref.startswith("data:"):
        return image_ref
    return urljoin(response_base_url(base_url).rstrip("/") + "/", image_ref.lstrip("/"))


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


SENSITIVE_LOG_KEY_MARKERS = ("key", "token", "secret", "authorization", "password")
IMAGE_LOG_KEY_MARKERS = ("image", "b64", "base64", "binary_data")
PROMPT_LOG_KEY_MARKERS = ("prompt", "input_text")
TEXT_PROMPT_LOG_KEYS = {"text", "input"}
DATA_IMAGE_URL_RE = re.compile(r"data:image/[A-Za-z0-9.+-]+;base64,[A-Za-z0-9+/=]+", re.IGNORECASE)
BEARER_TOKEN_RE = re.compile(r"(?i)(Bearer\s+)[A-Za-z0-9._~+/=-]{8,}")
SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(api[\s_-]*key|access[\s_-]*token|client[\s_-]*secret|token|secret|authorization|password)\b"
    r"\s*[:=]\s*['\"]?[^'\"\s,;}]+"
)
PROMPT_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(prompt|negative[\s_-]*prompt|input[\s_-]*text)\b\s*[:=]\s*['\"]?[^'\"\n\r;}]+"
)
OPENAI_STYLE_KEY_RE = re.compile(r"\bsk-[A-Za-z0-9][A-Za-z0-9_-]{7,}\b")


def extract_error_message(payload: Any) -> str:
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            return summarize_text_for_log(payload, max_string_length=240)

    if not isinstance(payload, dict):
        if isinstance(payload, (list, tuple)):
            return summarize_payload_json_for_log(payload, max_string_length=240)
        return summarize_text_for_log(str(payload), max_string_length=240)

    error = payload.get("error")
    if isinstance(error, dict):
        for key in ("message", "msg", "detail", "error_msg", "code"):
            value = error.get(key)
            if value:
                if isinstance(value, (dict, list, tuple)):
                    return summarize_payload_json_for_log(value, max_string_length=240)
                return summarize_text_for_log(str(value), max_string_length=240)
        return summarize_payload_json_for_log(error, max_string_length=240)
    if error:
        return summarize_text_for_log(str(error), max_string_length=240)

    for key in ("message", "msg", "detail", "error_msg"):
        if payload.get(key):
            value = payload[key]
            if isinstance(value, (dict, list, tuple)):
                return summarize_payload_json_for_log(value, max_string_length=240)
            return summarize_text_for_log(str(value), max_string_length=240)

    return summarize_payload_json_for_log(payload, max_string_length=240)


def _looks_like_base64_blob(text: str) -> bool:
    compact = re.sub(r"\s+", "", text)
    if len(compact) < 120 or len(compact) % 4:
        return False
    if not re.fullmatch(r"[A-Za-z0-9+/]+={0,2}", compact):
        return False
    try:
        base64.b64decode(compact, validate=True)
        return True
    except Exception:
        return False


def _image_data_url_summary(value: str) -> str:
    header = value.split(",", 1)[0]
    return f"<image_data_url header={header} chars={len(value)}>"


def _is_prompt_log_key(key_hint: str) -> bool:
    key = key_hint.lower()
    return key in TEXT_PROMPT_LOG_KEYS or any(marker in key for marker in PROMPT_LOG_KEY_MARKERS)


def _redact_text_fragments_for_log(text: str) -> str:
    text = DATA_IMAGE_URL_RE.sub(lambda match: _image_data_url_summary(match.group(0)), text)
    text = BEARER_TOKEN_RE.sub(r"\1<redacted>", text)
    text = SECRET_ASSIGNMENT_RE.sub(lambda match: f"{match.group(1)}=<redacted>", text)
    text = PROMPT_ASSIGNMENT_RE.sub(lambda match: f"{match.group(1)}=<redacted>", text)
    return OPENAI_STYLE_KEY_RE.sub("<redacted>", text)


def summarize_url_for_log(value: str) -> str:
    parsed = urlparse(str(value or ""))
    if not parsed.scheme or not parsed.netloc:
        return summarize_text_for_log(str(value), key_hint="url")
    host = parsed.hostname or ""
    if parsed.port:
        host = f"{host}:{parsed.port}"
    query = ""
    if parsed.query:
        pairs = parse_qsl(parsed.query, keep_blank_values=True)
        query = "&".join(f"{key}=<redacted>" for key, _ in pairs) if pairs else "<redacted_query>"
    fragment = "<redacted>" if parsed.fragment else ""
    return urlunparse((parsed.scheme, host, parsed.path, "", query, fragment))


def summarize_text_for_log(value: str, max_string_length: int = 160, key_hint: str = "") -> str:
    text = str(value or "")
    stripped = text.strip()
    lowered = stripped.lower()
    key_lowered = key_hint.lower()
    if lowered.startswith("data:image"):
        return _image_data_url_summary(stripped)
    if _is_prompt_log_key(key_lowered):
        label = "prompt" if "prompt" in key_lowered else key_lowered or "text"
        return f"<{label} chars={len(text)}>"
    if _looks_like_base64_blob(stripped):
        return f"<image_base64 chars={len(stripped)}>"
    redacted_text = _redact_text_fragments_for_log(text)
    if len(redacted_text) <= max_string_length:
        return redacted_text
    return f"{redacted_text[:max_string_length]}...<truncated chars={len(redacted_text)}>"


def summarize_payload_for_log(payload: Any, max_string_length: int = 160, key_hint: str = "") -> Any:
    """Build a compact, secret-safe payload summary for logs."""
    if isinstance(payload, dict):
        summary: Dict[str, Any] = {}
        for key, value in payload.items():
            key_text = str(key)
            if any(marker in key_text.lower() for marker in SENSITIVE_LOG_KEY_MARKERS):
                summary[key_text] = "<redacted>"
            else:
                summary[key_text] = summarize_payload_for_log(value, max_string_length, key_text)
        return summary
    if isinstance(payload, list):
        return [summarize_payload_for_log(item, max_string_length, key_hint) for item in payload]
    if isinstance(payload, tuple):
        return [summarize_payload_for_log(item, max_string_length, key_hint) for item in payload]
    if not isinstance(payload, str):
        return payload
    return summarize_text_for_log(payload, max_string_length, key_hint)


def summarize_payload_json_for_log(payload: Any, max_string_length: int = 160) -> str:
    return json.dumps(
        summarize_payload_for_log(payload, max_string_length=max_string_length),
        ensure_ascii=False,
        default=str,
    )


def summarize_response_text_for_log(value: str, max_string_length: int = 500) -> str:
    try:
        return summarize_payload_json_for_log(json.loads(value), max_string_length=max_string_length)
    except Exception:
        return summarize_text_for_log(value, max_string_length=max_string_length)


def extract_image_url_from_response(payload: Any, base_url: str) -> str:
    """Extract an image URL or data URL from common image/chat/responses shapes."""

    def likely_base64(value: str) -> bool:
        text = value.strip()
        if len(text) < 80:
            return False
        if not re.fullmatch(r"[A-Za-z0-9+/=\s]+", text):
            return False
        try:
            base64.b64decode(text, validate=False)
            return True
        except Exception:
            return False

    def from_text(text: str) -> str:
        text = str(text or "").strip()
        if not text:
            return ""
        if text.startswith("data:image"):
            return text
        if text.startswith("{") or text.startswith("["):
            try:
                nested = json.loads(text)
            except Exception:
                nested = None
            if nested is not None:
                nested_image = walk(nested)
                if nested_image:
                    return nested_image
        markdown_match = re.search(r"!\[[^\]]*\]\((data:image[^)]+|https?://[^)\s]+)\)", text)
        if markdown_match:
            return resolve_response_url(markdown_match.group(1), base_url)
        url_match = re.search(r"(https?://[^\s\]\)\"']+)", text)
        if url_match:
            return resolve_response_url(url_match.group(1), base_url)
        return ""

    def coerce_image_value(value: Any, assume_base64: bool = False) -> str:
        if isinstance(value, str):
            text = value.strip()
            extracted = from_text(text)
            if extracted:
                return extracted
            if assume_base64 and likely_base64(text):
                return "data:image/png;base64," + re.sub(r"\s+", "", text)
            return ""
        return walk(value)

    def from_inline_data(value: Any) -> str:
        if not isinstance(value, dict):
            return ""
        if "mimeType" not in value and "mime_type" not in value:
            return ""
        data_value = value.get("data")
        if not isinstance(data_value, str):
            return ""
        data = data_value.strip()
        if not data:
            return ""
        mime_type = str(value.get("mimeType") or value.get("mime_type") or "image/png").strip() or "image/png"
        if not mime_type.split(";", 1)[0].lower().startswith("image/"):
            return ""
        compact_data = re.sub(r"\s+", "", data)
        try:
            base64.b64decode(compact_data, validate=True)
        except Exception:
            return ""
        return f"data:{mime_type};base64,{compact_data}"

    def from_gemini_candidates(value: Any) -> str:
        if not isinstance(value, dict):
            return ""
        candidates = value.get("candidates")
        if not isinstance(candidates, list):
            return ""
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            content = candidate.get("content") or {}
            parts = content.get("parts") if isinstance(content, dict) else None
            if not isinstance(parts, list):
                continue
            last_inline_image = ""
            for part in parts:
                if not isinstance(part, dict):
                    continue
                for key in ("inlineData", "inline_data"):
                    image = from_inline_data(part.get(key))
                    if image:
                        last_inline_image = image
            if last_inline_image:
                return last_inline_image
        return ""

    def walk(value: Any) -> str:
        if isinstance(value, str):
            return from_text(value)
        if isinstance(value, list):
            for item in value:
                image = walk(item)
                if image:
                    return image
            return ""
        if not isinstance(value, dict):
            return ""

        gemini_image = from_gemini_candidates(value)
        if gemini_image:
            return gemini_image

        for key in ("inlineData", "inline_data"):
            image = from_inline_data(value.get(key))
            if image:
                return image

        if value.get("type") == "image_generation_call" and value.get("result"):
            image = coerce_image_value(value.get("result"), assume_base64=True)
            if image:
                return image

        for key in ("b64_json", "base64", "image_base64", "image_data", "binary_data_base64"):
            if key in value:
                image = coerce_image_value(value.get(key), assume_base64=True)
                if image:
                    return image

        if "image" in value:
            image_value = value.get("image")
            image = coerce_image_value(image_value, assume_base64=True)
            if image:
                return image
            if isinstance(image_value, str):
                text = image_value.strip()
                if re.search(r"\.(?:png|jpe?g|webp|gif|bmp|avif)(?:[?#].*)?$", text, re.IGNORECASE):
                    return resolve_response_url(text, base_url)

        for key in ("url", "image_url", "uri"):
            if key in value:
                nested = value.get(key)
                if isinstance(nested, dict) and "url" in nested:
                    nested = nested.get("url")
                if isinstance(nested, str) and nested.strip():
                    image = from_text(nested)
                    return image or resolve_response_url(nested, base_url)
                image = coerce_image_value(nested)
                if image:
                    return image

        for key in (
            "data",
            "images",
            "image",
            "output",
            "output_text",
            "result",
            "results",
            "choices",
            "message",
            "content",
            "text",
            "candidates",
            "parts",
            "inlineData",
            "inline_data",
            "artifacts",
            "generations",
        ):
            if key in value:
                image = walk(value.get(key))
                if image:
                    return image

        return ""

    return walk(payload)


class BaseProvider(ABC):
    def __init__(self, config: ProviderConfig, session: aiohttp.ClientSession):
        self.config = config
        self.session = session
        self._api_keys = [str(key).strip() for key in self.config.api_keys if str(key).strip()]

    def get_current_key(self) -> str:
        return next_api_key(self.config.id, self._api_keys)

    async def fetch_reference_bytes(self, source: str, *, timeout: float = REF_DOWNLOAD_TIMEOUT) -> bytes:
        """从 data URL、网络 URL 或本地路径读取参考图字节，网络下载带超时，本地读取放到线程池避免阻塞事件循环。"""
        source = str(source or "")
        if source.startswith("data:image"):
            try:
                return base64.b64decode(source.split(",", 1)[1], validate=False)
            except Exception as exc:
                raise RuntimeError(f"Base64 参考图解析失败: {exc}")
        if source.startswith("http"):
            timeout_obj = aiohttp.ClientTimeout(total=timeout)
            async with self.session.get(source, headers=REF_DOWNLOAD_HEADERS, timeout=timeout_obj) as response:
                if response.status != 200:
                    raise RuntimeError(f"参考图下载失败，服务器返回状态码: {response.status}")
                return await response.read()
        if not os.path.exists(source):
            raise RuntimeError(f"本地参考图不存在: {source}")
        return await asyncio.to_thread(_read_file_bytes, source)

    async def fetch_reference_data_url(self, source: str, *, timeout: float = REF_DOWNLOAD_TIMEOUT) -> str:
        """将参考图统一转换为 data URL；已是 data URL 时直接返回，避免重复解码再编码。"""
        source = str(source or "")
        if source.startswith("data:image"):
            return source
        image_bytes = await self.fetch_reference_bytes(source, timeout=timeout)
        mime_type = guess_image_content_type(source)
        encoded = await asyncio.to_thread(_encode_base64, image_bytes)
        return f"data:{mime_type};base64,{encoded}"

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
