"""通用工具函数。"""

import asyncio
import base64
import functools
import mimetypes
import os
import time
import uuid
from typing import Callable, Any, AsyncGenerator, Tuple

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent
from .constants import MessageEmoji


def split_data_url(data_url: str) -> Tuple[bytes, str]:
    """Decode a data URL and return raw bytes plus the media type."""
    header, base64_str = str(data_url or "").split(",", 1)
    content_type = ""
    if header.startswith("data:"):
        content_type = header[5:].split(";", 1)[0].strip()
    return base64.b64decode(base64_str, validate=False), content_type


def guess_image_content_type(source: str, content_type: str = "", fallback: str = "image/png") -> str:
    media_type = str(content_type or "").strip().split(";", 1)[0].strip()
    if media_type.startswith("image/"):
        return media_type
    source = str(source or "")
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


def guess_image_extension(source: str, content_type: str = "", fallback: str = "png") -> str:
    media_type = str(content_type or "").strip().split(";", 1)[0].strip()
    if not media_type:
        media_type = guess_image_content_type(source)
    extension = mimetypes.guess_extension(media_type, strict=False) if media_type else ""
    if extension:
        return extension.lstrip(".")
    lowered = str(source or "").lower()
    if lowered.startswith("data:"):
        header = lowered.split(",", 1)[0]
        if "jpeg" in header or "jpg" in header:
            return "jpg"
        if "webp" in header:
            return "webp"
        if "gif" in header:
            return "gif"
        if "avif" in header:
            return "avif"
        if "tiff" in header or "tif" in header:
            return "tiff"
    for candidate in ("jpg", "jpeg", "png", "webp", "gif", "avif", "bmp", "tiff"):
        if lowered.endswith(f".{candidate}"):
            return candidate
    return fallback


def save_image_bytes(
    image_bytes: bytes,
    directory: str,
    source: str,
    prefix: str = "ref",
    index: int = 0,
    content_type: str = "",
) -> str:
    os.makedirs(directory, exist_ok=True)
    ext = guess_image_extension(source, content_type)
    filename = f"{prefix}_{int(time.time() * 1000)}_{index}_{uuid.uuid4().hex[:8]}.{ext}"
    filepath = os.path.abspath(os.path.join(directory, filename))
    with open(filepath, "wb") as file:
        file.write(image_bytes)
    return filepath

def handle_errors(func: Callable) -> Callable:
    """统一错误处理装饰器"""
    @functools.wraps(func)
    async def wrapper(self, event: AstrMessageEvent, *args, **kwargs) -> AsyncGenerator[Any, None]:
        try:
            async for result in func(self, event, *args, **kwargs):
                yield result
        except asyncio.TimeoutError:
            logger.error(f"[{func.__name__}] 操作超时", exc_info=True)
            custom_builder = getattr(self, "_build_command_error_message", None)
            if callable(custom_builder):
                custom_message = custom_builder(func.__name__, asyncio.TimeoutError(), error_kind="timeout")
                if custom_message:
                    yield event.plain_result(custom_message)
                    return
            yield event.plain_result(f"{MessageEmoji.ERROR} 操作超时，请稍后重试")
        except ValueError as e:
            logger.warning(f"[{func.__name__}] 参数错误: {e}")
            yield event.plain_result(f"{MessageEmoji.ERROR} 参数错误: {str(e)}")
        except Exception as e:
            error_type = type(e).__name__
            logger.error(f"[{func.__name__}] 执行失败 [{error_type}]: {e}", exc_info=True)
            custom_builder = getattr(self, "_build_command_error_message", None)
            if callable(custom_builder):
                custom_message = custom_builder(func.__name__, e, error_kind="exception")
                if custom_message:
                    yield event.plain_result(custom_message)
                    return
            yield event.plain_result(f"{MessageEmoji.ERROR} 操作失败，请联系管理员")
    return wrapper
