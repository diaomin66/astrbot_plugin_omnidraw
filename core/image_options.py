"""Request-scoped GIF options; static-image requests keep their existing semantics."""

import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse

from ..constants import APIType


GIF_MODELS = ("gpt-image-2.6-sunburst", "gpt-image-2.6-flare")
GIF_DEFAULT_FRAME_COUNT = 9
GIF_DEFAULT_FRAME_DURATION_MS = 200
GIF_MIN_FRAME_COUNT = 2
GIF_MAX_FRAME_COUNT = 16
GIF_MIN_FRAME_DURATION_MS = 20
GIF_MAX_FRAME_DURATION_MS = 2000

_GIF_MODEL_RE = re.compile(r"gpt-image-2\.6-(?:sunburst|flare)(?:-\d{4}-\d{2}-\d{2})?", re.IGNORECASE)


def is_gif_request(options: Mapping[str, Any]) -> bool:
    return str(options.get("output_format") or "").strip().lower() == "gif"


def provider_supports_gif(config: Any) -> bool:
    if not _GIF_MODEL_RE.fullmatch(str(getattr(config, "model", "") or "").strip()):
        return False
    api_type = getattr(config, "api_type", "")
    if api_type == APIType.OPENAI_IMAGE:
        return True
    if api_type == APIType.CUSTOM_ENDPOINT:
        path = urlparse(str(getattr(config, "base_url", "") or "")).path.rstrip("/").lower()
        return path.endswith(("/images/generations", "/images/edits"))
    return False


def _bounded_integer(value: Any, name: str, default: int, minimum: int, maximum: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError(f"GIF 参数 {name} 必须是 {minimum} 至 {maximum} 的整数。")
    if isinstance(value, str) and not re.fullmatch(r"[0-9]+", value.strip()):
        raise ValueError(f"GIF 参数 {name} 必须是 {minimum} 至 {maximum} 的整数。")
    try:
        number = int(value)
    except (ValueError, OverflowError) as exc:
        raise ValueError(f"GIF 参数 {name} 必须是 {minimum} 至 {maximum} 的整数。") from exc
    if not minimum <= number <= maximum:
        raise ValueError(f"GIF 参数 {name} 必须是 {minimum} 至 {maximum} 的整数。")
    return number


def normalize_gif_options(options: Mapping[str, Any]) -> dict[str, Any]:
    """Validate only explicit GIF requests, without mutating caller-owned options."""
    normalized = dict(options)
    if not is_gif_request(normalized):
        return normalized

    normalized["output_format"] = "gif"
    normalized["frame_count"] = _bounded_integer(
        normalized.get("frame_count"), "frame_count", GIF_DEFAULT_FRAME_COUNT,
        GIF_MIN_FRAME_COUNT, GIF_MAX_FRAME_COUNT,
    )
    normalized["frame_duration_ms"] = _bounded_integer(
        normalized.get("frame_duration_ms"), "frame_duration_ms", GIF_DEFAULT_FRAME_DURATION_MS,
        GIF_MIN_FRAME_DURATION_MS, GIF_MAX_FRAME_DURATION_MS,
    )

    for key in ("stream", "partial_images"):
        value = normalized.pop(key, None)
        if value is not None and str(value).strip().lower() not in {"", "false", "0"}:
            raise ValueError(f"GIF 不支持 {key}，请移除此参数。")
    for key in ("mask", "output_compression"):
        if normalized.pop(key, None) is not None:
            raise ValueError(f"GIF 不支持 {key}，请移除此参数。")

    if str(normalized.pop("aspect_ratio", "") or "").strip():
        raise ValueError("GIF 请使用 --size auto 或 --size 宽x高，不支持 aspect_ratio 参数。")
    resolution = normalized.pop("resolution", "")
    size = str(normalized.get("size") or resolution or "auto").strip().lower()
    if size != "auto":
        match = re.fullmatch(r"([0-9]{1,6})x([0-9]{1,6})", size)
        if not match or any(int(edge) <= 0 or int(edge) % 16 for edge in match.groups()):
            raise ValueError("GIF size 必须是 auto 或宽高均为正整数且为 16 倍数的尺寸，例如 512x512。")
        size = f"{int(match.group(1))}x{int(match.group(2))}"
    normalized["size"] = size

    complexity = normalized.get("complexity")
    if complexity is not None:
        complexity = str(complexity).strip().lower()
        if complexity not in {"low", "medium", "high"}:
            raise ValueError("GIF complexity 必须是 low、medium 或 high。")
        normalized["complexity"] = complexity
    return normalized
