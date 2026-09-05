"""图片 Provider 基类。"""
import asyncio
import aiohttp
import base64
import json
import ipaddress
import mimetypes
import os
import re
import socket
import threading
from abc import ABC, abstractmethod
from typing import Any, Dict, Iterable, Optional, List, Tuple
from urllib.parse import parse_qsl, urljoin, urlparse, urlunparse
from astrbot.api import logger
from ..models import ProviderConfig

_KEY_ROTATION_LOCK = threading.Lock()
_KEY_ROTATION_INDEX: Dict[str, int] = {}

MAX_REFERENCE_IMAGES = 14
MAX_REFERENCE_IMAGE_BYTES = 20 * 1024 * 1024
MAX_REFERENCE_TOTAL_BYTES = 64 * 1024 * 1024
MAX_PROVIDER_RESPONSE_BYTES = 64 * 1024 * 1024

RESERVED_PROVIDER_PARAMETER_KEYS = frozenset(
    {
        "prompt",
        "model",
        "n",
        "stream",
        "messages",
        "input",
        "tools",
        "contents",
        "image",
        "images",
        "image_url",
        "user_ref",
        "user_refs",
        "persona_ref",
        "persona_refs",
    }
)


def normalize_base_url(base_url: str) -> str:
    value = str(base_url or "").strip()
    if not value:
        return ""
    parsed = urlparse(value)
    return urlunparse(parsed._replace(path=parsed.path.rstrip("/")))


def _replace_url_path(value: str, path: str) -> str:
    parsed = urlparse(value)
    return urlunparse(parsed._replace(path=path))


def _append_url_path(value: str, suffix: str) -> str:
    parsed = urlparse(value)
    path = parsed.path.rstrip("/") + "/" + suffix.lstrip("/")
    return urlunparse(parsed._replace(path=path))


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
    lowered = urlparse(base_url).path.rstrip("/").lower()
    return any(lowered.endswith(suffix) for suffix in endpoint_suffixes)


def _replace_endpoint_path(base_url: str, endpoint_suffix: str, replacement_suffix: str) -> str:
    parsed = urlparse(base_url)
    path = parsed.path.rstrip("/")
    if path.lower().endswith(endpoint_suffix):
        return urlunparse(parsed._replace(path=path[: -len(endpoint_suffix)] + replacement_suffix))
    return base_url


def strip_known_endpoint_path(base_url: str) -> str:
    base_url = normalize_base_url(base_url)
    parsed = urlparse(base_url)
    path = parsed.path.rstrip("/")
    for suffix in (
        "/chat/completions",
        "/responses",
        "/images/generations",
        "/images/edits",
        "/videos/generations",
    ):
        if path.lower().endswith(suffix):
            return urlunparse(parsed._replace(path=path[: -len(suffix)]))
    return base_url


def response_base_url(base_url: str) -> str:
    api_root = strip_known_endpoint_path(base_url)
    parsed = urlparse(api_root)
    path = parsed.path.rstrip("/")
    if path.lower().endswith("/v1"):
        return urlunparse(parsed._replace(path=path[:-3]))
    return api_root


def resolve_response_url(value: str, base_url: str) -> str:
    image_ref = str(value or "").strip()
    parsed_ref = urlparse(image_ref)
    if parsed_ref.scheme.lower() in {"http", "https"} or image_ref.lower().startswith("data:"):
        return image_ref
    response_root = response_base_url(base_url)
    parsed_root = urlparse(response_root)
    response_dir = urlunparse(parsed_root._replace(path=parsed_root.path.rstrip("/") + "/"))
    return urljoin(response_dir, image_ref)


def build_chat_completions_endpoint(base_url: str) -> str:
    base_url = normalize_base_url(base_url)
    if not base_url:
        return ""
    if _has_endpoint_path(base_url, ["/chat/completions"]):
        return base_url
    base_url = _replace_endpoint_path(base_url, "/responses", "/chat/completions")
    if _has_endpoint_path(base_url, ["/chat/completions"]):
        return base_url
    path = urlparse(base_url).path.rstrip("/").lower()
    suffix = "chat/completions" if path.endswith("/v1") else "v1/chat/completions"
    return _append_url_path(base_url, suffix)


def build_image_generations_endpoint(base_url: str) -> str:
    base_url = normalize_base_url(base_url)
    if not base_url:
        return ""
    if _has_endpoint_path(base_url, ["/images/generations"]):
        return base_url
    base_url = _replace_endpoint_path(base_url, "/images/edits", "/images/generations")
    if _has_endpoint_path(base_url, ["/images/generations"]):
        return base_url
    return _append_url_path(base_url, "images/generations")


def build_image_edits_endpoint(base_url: str) -> str:
    base_url = normalize_base_url(base_url)
    if not base_url:
        return ""
    if _has_endpoint_path(base_url, ["/images/generations", "/images/edits"]):
        return base_url
    return _append_url_path(base_url, "images/edits")


def build_video_generations_endpoint(base_url: str) -> str:
    base_url = normalize_base_url(base_url)
    if not base_url:
        return ""
    if _has_endpoint_path(base_url, ["/videos/generations"]):
        return base_url
    return _append_url_path(base_url, "videos/generations")


def next_api_key(provider_id: str, api_keys: List[str], scope: str = "") -> str:
    keys = [str(key).strip() for key in api_keys if str(key).strip()]
    if not provider_id or not keys:
        return ""
    scope_text = str(scope or "").strip()
    rotation_scope = f"{provider_id}:{scope_text}" if scope_text else provider_id
    with _KEY_ROTATION_LOCK:
        idx = _KEY_ROTATION_INDEX.get(rotation_scope, 0)
        key = keys[idx % len(keys)]
        _KEY_ROTATION_INDEX[rotation_scope] = (idx + 1) % len(keys)
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


def _validated_image_content_type(source: str, advertised_content_type: str = "") -> str:
    advertised = str(advertised_content_type or "").split(";", 1)[0].strip().lower()
    if advertised:
        if not advertised.startswith("image/") or advertised == "image/svg+xml":
            raise RuntimeError(f"参考图响应类型不是受支持的图片: {advertised}")
        return advertised

    guessed = guess_image_content_type(source, fallback="").lower()
    if not guessed or guessed == "image/svg+xml":
        raise RuntimeError("无法确认参考图为受支持的图片类型")
    return guessed


def _image_kind(payload: bytes) -> str:
    if payload.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if payload.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if payload.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if len(payload) >= 12 and payload.startswith(b"RIFF") and payload[8:12] == b"WEBP":
        return "webp"
    if payload.startswith(b"BM"):
        return "bmp"
    if payload.startswith((b"II*\x00", b"MM\x00*")):
        return "tiff"
    if len(payload) >= 12 and payload[4:8] == b"ftyp" and payload[8:12] in {b"avif", b"avis"}:
        return "avif"
    return ""


def _image_kind_matches_mime(kind: str, mime_type: str) -> bool:
    expected = {
        "image/png": "png",
        "image/x-png": "png",
        "image/jpeg": "jpeg",
        "image/jpg": "jpeg",
        "image/pjpeg": "jpeg",
        "image/gif": "gif",
        "image/webp": "webp",
        "image/bmp": "bmp",
        "image/x-ms-bmp": "bmp",
        "image/tiff": "tiff",
        "image/x-tiff": "tiff",
        "image/avif": "avif",
    }.get(str(mime_type or "").split(";", 1)[0].strip().lower())
    return bool(kind and expected and kind == expected)


def _validate_image_payload(payload: bytes, mime_type: str, source: str) -> bytes:
    if not payload:
        raise RuntimeError("参考图内容为空")
    kind = _image_kind(payload[:32])
    if not kind:
        raise RuntimeError(f"参考图内容不是支持的图片格式: {source}")
    if not _image_kind_matches_mime(kind, mime_type):
        raise RuntimeError(f"参考图内容与声明类型不匹配: {source}")
    return payload


def _validate_remote_reference_url(value: str) -> None:
    parsed = urlparse(str(value or "").strip())
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise RuntimeError("参考图 URL 仅支持 http/https")
    if parsed.username or parsed.password:
        raise RuntimeError("参考图 URL 不允许包含用户凭据")
    try:
        addresses = socket.getaddrinfo(
            parsed.hostname,
            parsed.port or (443 if parsed.scheme.lower() == "https" else 80),
            type=socket.SOCK_STREAM,
        )
    except OSError as exc:
        raise RuntimeError(f"参考图域名解析失败: {exc}") from exc
    resolved = {item[4][0] for item in addresses if item and item[4]}
    if not resolved:
        raise RuntimeError("参考图域名没有可用地址")
    for address in resolved:
        try:
            if not ipaddress.ip_address(address).is_global:
                raise RuntimeError("参考图 URL 不允许访问本机、私网或链路本地地址")
        except ValueError as exc:
            raise RuntimeError("参考图域名解析结果无效") from exc


async def read_response_bytes_limited(response: Any, max_bytes: int = MAX_PROVIDER_RESPONSE_BYTES) -> bytes:
    headers = getattr(response, "headers", None) or {}
    content_length = headers.get("Content-Length") or headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > max_bytes:
                raise RuntimeError(f"响应体超过 {max_bytes} 字节上限")
        except ValueError:
            pass

    chunks = []
    total = 0
    content = getattr(response, "content", None)
    iter_chunked = getattr(content, "iter_chunked", None)
    if callable(iter_chunked):
        async for chunk in iter_chunked(64 * 1024):
            total += len(chunk)
            if total > max_bytes:
                raise RuntimeError(f"响应体超过 {max_bytes} 字节上限")
            chunks.append(chunk)
        return b"".join(chunks)

    read = getattr(response, "read", None)
    if callable(read):
        payload = await read()
        if len(payload) > max_bytes:
            raise RuntimeError(f"响应体超过 {max_bytes} 字节上限")
        return payload

    text = await response.text()
    payload = text.encode("utf-8")
    if len(payload) > max_bytes:
        raise RuntimeError(f"响应体超过 {max_bytes} 字节上限")
    return payload


async def read_response_text_limited(response: Any, max_bytes: int = MAX_PROVIDER_RESPONSE_BYTES) -> str:
    payload = await read_response_bytes_limited(response, max_bytes=max_bytes)
    encoding = getattr(response, "charset", None) or "utf-8"
    try:
        return payload.decode(encoding)
    except (LookupError, UnicodeDecodeError):
        return payload.decode("utf-8", errors="replace")


def filter_provider_api_kwargs(kwargs: Dict[str, Any], provider_id: str = "") -> Dict[str, Any]:
    filtered: Dict[str, Any] = {}
    blocked = []
    for key, value in kwargs.items():
        key_text = str(key)
        lowered = key_text.casefold()
        if lowered in RESERVED_PROVIDER_PARAMETER_KEYS or re.fullmatch(r"image_?\d+", lowered):
            blocked.append(key_text)
            continue
        filtered[key] = value
    if blocked:
        prefix = f"[{provider_id}] " if provider_id else ""
        logger.warning(prefix + "已忽略禁止透传的 Provider 保留参数: " + ", ".join(sorted(blocked)))
    return filtered


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
            candidate = url_match.group(1).rstrip(".,;:!?，。；：！？>")
            parsed = urlparse(candidate)
            path = parsed.path.lower()
            query = parsed.query.lower()
            if (
                text == candidate
                or re.search(r"\.(?:png|jpe?g|webp|gif|bmp|avif|tiff?)(?:$|/)", path)
                or "format=image" in query
            ):
                return resolve_response_url(candidate, base_url)
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
        scope = f"image:{self.config.api_type}:{normalize_base_url(self.config.base_url)}"
        return next_api_key(self.config.id, self._api_keys, scope=scope)

    def filter_api_kwargs(self, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        return filter_provider_api_kwargs(kwargs, self.config.id)

    async def read_reference_image(self, image_path_or_url: str) -> Tuple[bytes, str]:
        source = str(image_path_or_url or "").strip()
        if not source:
            raise RuntimeError("参考图地址为空")

        if source.lower().startswith("data:"):
            header, separator, encoded = source.partition(",")
            media_type = header[5:].split(";", 1)[0].strip().lower()
            if not separator or ";base64" not in header.lower():
                raise RuntimeError("参考图 Data URL 必须使用 Base64 编码")
            mime_type = _validated_image_content_type(source, media_type)
            compact = re.sub(r"\s+", "", encoded)
            if len(compact) > ((MAX_REFERENCE_IMAGE_BYTES + 2) // 3) * 4 + 4:
                raise RuntimeError(f"单张参考图超过 {MAX_REFERENCE_IMAGE_BYTES} 字节上限")
            try:
                payload = base64.b64decode(compact, validate=True)
            except Exception as exc:
                raise RuntimeError(f"Base64 参考图解析失败: {exc}")
            if len(payload) > MAX_REFERENCE_IMAGE_BYTES:
                raise RuntimeError(f"单张参考图超过 {MAX_REFERENCE_IMAGE_BYTES} 字节上限")
            return _validate_image_payload(payload, mime_type, "data URL"), mime_type

        parsed = urlparse(source)
        if parsed.scheme.lower() in {"http", "https"}:
            logger.info(f"[{self.config.id}] 正在下载网络参考图并转码...")
            headers = {"User-Agent": "Mozilla/5.0"}
            current_url = source
            for redirect_count in range(4):
                await asyncio.to_thread(_validate_remote_reference_url, current_url)
                async with self.session.get(
                    current_url,
                    headers=headers,
                    allow_redirects=False,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as response:
                    if 300 <= response.status < 400:
                        location = str(response.headers.get("Location", "") or "").strip()
                        if not location or redirect_count >= 3:
                            raise RuntimeError("参考图重定向次数过多或缺少目标地址")
                        current_url = urljoin(current_url, location)
                        continue
                    if response.status != 200:
                        raise RuntimeError(f"参考图下载失败，服务器返回状态码: {response.status}")
                    response_headers = getattr(response, "headers", None) or {}
                    mime_type = _validated_image_content_type(
                        current_url,
                        response_headers.get("Content-Type", ""),
                    )
                    payload = await read_response_bytes_limited(response, max_bytes=MAX_REFERENCE_IMAGE_BYTES)
                    return _validate_image_payload(payload, mime_type, current_url), mime_type
            raise RuntimeError("参考图重定向次数过多")

        if not os.path.exists(source):
            raise RuntimeError(f"本地参考图不存在: {source}")
        if not os.path.isfile(source):
            raise RuntimeError(f"本地参考图不是普通文件: {source}")
        if os.path.islink(source):
            raise RuntimeError(f"本地参考图不允许使用符号链接: {source}")
        file_size = os.path.getsize(source)
        if file_size > MAX_REFERENCE_IMAGE_BYTES:
            raise RuntimeError(f"单张参考图超过 {MAX_REFERENCE_IMAGE_BYTES} 字节上限")
        mime_type = _validated_image_content_type(source)
        with open(source, "rb") as image_file:
            payload = image_file.read(MAX_REFERENCE_IMAGE_BYTES + 1)
        if len(payload) > MAX_REFERENCE_IMAGE_BYTES:
            raise RuntimeError(f"单张参考图超过 {MAX_REFERENCE_IMAGE_BYTES} 字节上限")
        return _validate_image_payload(payload, mime_type, source), mime_type

    async def load_reference_images(
        self,
        refs: List[str],
        max_images: int = MAX_REFERENCE_IMAGES,
    ) -> List[Tuple[bytes, str]]:
        if len(refs) > max_images:
            raise ValueError(f"单次请求最多支持 {max_images} 张参考图。")

        loaded = []
        total_bytes = 0
        for index, ref in enumerate(refs, start=1):
            try:
                payload, mime_type = await self.read_reference_image(ref)
            except Exception as exc:
                raise RuntimeError(f"读取第 {index} 张参考图数据失败: {exc}")
            total_bytes += len(payload)
            if total_bytes > MAX_REFERENCE_TOTAL_BYTES:
                raise RuntimeError(f"参考图总大小超过 {MAX_REFERENCE_TOTAL_BYTES} 字节上限")
            loaded.append((payload, mime_type))
        return loaded

    def encode_local_image_to_base64(self, image_path: str) -> Optional[str]:
        """将本地图片文件转为 API 兼容的 Base64 字符串"""
        if not image_path or not os.path.isfile(image_path):
            return None

        logger.info(f"[{self.config.id}] 正在将本地参考图转为 Base64: {image_path}")
        try:
            if os.path.getsize(image_path) > MAX_REFERENCE_IMAGE_BYTES:
                raise RuntimeError(f"单张参考图超过 {MAX_REFERENCE_IMAGE_BYTES} 字节上限")
            if os.path.islink(image_path):
                raise RuntimeError("本地参考图不允许使用符号链接")
            mime_type = _validated_image_content_type(image_path)
            with open(image_path, "rb") as image_file:
                payload = image_file.read(MAX_REFERENCE_IMAGE_BYTES + 1)
                if len(payload) > MAX_REFERENCE_IMAGE_BYTES:
                    raise RuntimeError(f"单张参考图超过 {MAX_REFERENCE_IMAGE_BYTES} 字节上限")
                _validate_image_payload(payload, mime_type, image_path)
                encoded_string = base64.b64encode(payload).decode('utf-8')
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
