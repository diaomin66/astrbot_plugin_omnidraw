"""
AstrBot 万象画卷插件。

负责命令入口、LLM 工具、配置页面 API、图片缓存与后台视频任务生命周期。
"""
import asyncio
import base64
import binascii
import copy
import hashlib
import json
import mimetypes
import os
import random
import re
import threading
import time
import uuid
from urllib.parse import parse_qs, urlparse
from typing import Any, AsyncGenerator, Dict, Iterable, List, Optional, Tuple

import aiohttp
from quart import jsonify, request, send_file

try:
    from astrbot.api.star import Context, Star, register
    from astrbot.api.event import AstrMessageEvent, filter
    from astrbot.api.message_components import Image, Plain, At
    from astrbot.api import llm_tool, logger
except ImportError:
    from astrbot.api.star import Context, Star, register
    from astrbot.api.event import AstrMessageEvent, filter
    from astrbot.api.event.components import Image, Plain, At
    from astrbot.api import llm_tool
    from astrbot.api.utils import logger

try:
    from astrbot.api.event import EventMessageType
except ImportError:
    from astrbot.api.event.filter import EventMessageType

try:
    from astrbot.core.utils.astrbot_path import get_astrbot_data_path
except Exception:
    def get_astrbot_data_path() -> str:
        return os.path.join(os.getcwd(), "data")

from .constants import (
    DEFAULT_BATCH_LIMIT,
    DEFAULT_DRAW_ERROR_MESSAGE,
    DEFAULT_DRAW_PENDING_MESSAGE,
    DEFAULT_SELFIE_ERROR_MESSAGE,
    DEFAULT_SELFIE_PENDING_MESSAGE,
    MAX_IMAGE_BYTES,
    MessageEmoji,
)
from .core.chain_manager import ChainManager, ChainRunResult
from .core.parser import CommandParser
from .core.persona_manager import PersonaManager
from .core.prompt_optimizer import PromptOptimizer
from .core.video_manager import VideoManager
from .models import PLUGIN_AUTHOR, PLUGIN_NAME, PLUGIN_VERSION, PluginConfig
from .utils import handle_errors, save_image_bytes, split_data_url

PAGE_PREVIEW_IMAGE_BYTES = 80 * 1024 * 1024
NATIVE_ACTIVE_PERSONA_FILE_PREFIX = "files/persona_config/persona_ref_image/"
CACHE_DIR_NAMES = ("temp_images", "user_refs")
PLUGIN_RESULT_ERROR_MAX_LENGTH = 240
CACHE_IMAGE_EXTENSIONS = frozenset({
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".gif",
    ".bmp",
    ".avif",
    ".heic",
    ".heif",
    ".tif",
    ".tiff",
    ".jfif",
})
DEFAULT_CACHE_CLEANUP_INTERVAL_HOURS = 24
DEFAULT_MAX_CACHE_SIZE_MB = 512
CONFIG_KEYS = {
    "permission_config",
    "persona_config",
    "optimizer_config",
    "router_config",
    "presets",
    "providers",
    "video_providers",
    "usage_config",
    "cache_config",
    "reply_config",
    "verbose_report",
    "show_generation_time",
    "show_request_model",
}


@register(PLUGIN_NAME, PLUGIN_AUTHOR, f"万象画卷 v{PLUGIN_VERSION}", PLUGIN_VERSION)
class OmniDrawPlugin(Star):
    def __init__(self, context: Context, config: Optional[dict] = None):
        super().__init__(context)

        self.data_dir = self._resolve_data_dir()
        os.makedirs(self.data_dir, exist_ok=True)
        self.config_path = os.path.join(self.data_dir, "omnidraw_persist_config.json")
        self.usage_stats_path = os.path.join(self.data_dir, "omnidraw_usage_stats.json")
        self._usage_stats = self._load_usage_stats()
        self._background_tasks = set()
        self._config_lock = threading.RLock()
        self._usage_lock = threading.RLock()
        self._cache_cleanup_task: Optional[asyncio.Task] = None
        self._page_image_tokens: Dict[str, str] = {}
        self._native_config = config if hasattr(config, "save_config") else None
        self._native_config_path = str(getattr(config, "config_path", "") or "")
        self._native_config_mtime = self._get_mtime(self._native_config_path)
        self._native_config_signature = self._file_signature(self._native_config_path)
        self._persist_config_mtime = self._get_mtime(self.config_path)

        self.cmd_parser = CommandParser()
        self._apply_runtime_config(self._load_initial_config(config or {}))
        self._persist_config()
        self._safe_update_context_config()

        self.context.register_web_api(
            f"/{PLUGIN_NAME}/get_config",
            self.get_config_handler,
            ["GET"],
            "获取万象画卷配置",
        )
        self.context.register_web_api(
            f"/{PLUGIN_NAME}/save_config",
            self.save_config_handler,
            ["POST"],
            "保存万象画卷配置",
        )
        self.context.register_web_api(
            f"/{PLUGIN_NAME}/get_usage_stats",
            self.get_usage_stats_handler,
            ["GET"],
            "获取万象画卷当日生图统计",
        )
        self.context.register_web_api(
            f"/{PLUGIN_NAME}/get_cache_stats",
            self.get_cache_stats_handler,
            ["GET"],
            "获取万象画卷图片缓存统计",
        )
        self.context.register_web_api(
            f"/{PLUGIN_NAME}/clear_cache",
            self.clear_cache_handler,
            ["POST"],
            "清理万象画卷图片缓存",
        )
        self.context.register_web_api(
            f"/{PLUGIN_NAME}/get_image",
            self.get_image_handler,
            ["GET"],
            "获取万象画卷本地参考图预览",
        )
        self.context.register_web_api(
            f"/{PLUGIN_NAME}/generate_image_for_plugin",
            self.generate_image_for_plugin_handler,
            ["POST"],
            "为其他插件生成图片并返回结果",
        )

    def _resolve_data_dir(self) -> str:
        base_data_dir = str(get_astrbot_data_path())
        return os.path.join(base_data_dir, "plugin_data", PLUGIN_NAME)

    def _get_mtime(self, path: str) -> float:
        if not path:
            return 0.0
        try:
            return os.path.getmtime(path)
        except OSError:
            return 0.0

    def _file_signature(self, path: str) -> str:
        if not path:
            return ""
        try:
            with open(path, "rb") as file:
                return hashlib.sha256(file.read()).hexdigest()
        except OSError:
            return ""

    def _load_json_file(self, path: str) -> Dict[str, Any]:
        if not path or not os.path.exists(path):
            return {}
        try:
            with open(path, "r", encoding="utf-8-sig") as file:
                data = json.load(file)
            return data if isinstance(data, dict) else {}
        except Exception as exc:
            logger.error(f"[OmniDraw] 读取配置失败: {path} {exc}", exc_info=True)
            return {}

    def _today_key(self) -> str:
        return time.strftime("%Y-%m-%d", time.localtime())

    def _to_nonnegative_int(self, value: Any, default: int = 0) -> int:
        try:
            parsed = int(float(str(value).strip()))
        except Exception:
            parsed = default
        return max(0, parsed)

    def _load_usage_stats(self) -> Dict[str, Any]:
        return self._normalize_usage_stats(self._load_json_file(self.usage_stats_path))

    def _normalize_usage_stats(self, stats: Dict[str, Any]) -> Dict[str, Any]:
        today = self._today_key()
        if not isinstance(stats, dict) or stats.get("date") != today:
            return {"date": today, "total": 0, "users": {}}

        users = stats.get("users")
        if not isinstance(users, dict):
            users = {}

        normalized_users = {}
        for raw_user_id, raw_record in users.items():
            user_id = str(raw_user_id or "").strip()
            if not user_id:
                continue
            record = raw_record if isinstance(raw_record, dict) else {"count": raw_record}
            count = self._to_nonnegative_int(record.get("count", 0))
            bonus = self._to_nonnegative_int(record.get("bonus", 0))
            checkin_at = self._to_nonnegative_int(record.get("checkin_at", 0))
            normalized_record = {
                "user_id": user_id,
                "count": count,
                "bonus": bonus,
                "checkin_at": checkin_at,
                "last_at": self._to_nonnegative_int(record.get("last_at", 0)),
            }
            for key in ("display_name", "group_id", "access_level"):
                value = str(record.get(key, "")).strip()
                if value:
                    normalized_record[key] = value
            normalized_users[user_id] = normalized_record

        return {
            "date": today,
            "total": sum(record["count"] for record in normalized_users.values()),
            "users": normalized_users,
        }

    def _current_usage_stats(self) -> Dict[str, Any]:
        with self._usage_lock:
            self._usage_stats = self._normalize_usage_stats(self._usage_stats)
            return self._usage_stats

    def _persist_usage_stats(self) -> None:
        with self._usage_lock:
            os.makedirs(self.data_dir, exist_ok=True)
            tmp_path = f"{self.usage_stats_path}.{uuid.uuid4().hex}.tmp"
            try:
                with open(tmp_path, "w", encoding="utf-8") as file:
                    json.dump(self._current_usage_stats(), file, ensure_ascii=False, indent=4)
                os.replace(tmp_path, self.usage_stats_path)
            except Exception as exc:
                logger.error(f"[OmniDraw] 生图统计保存失败: {exc}", exc_info=True)
                try:
                    if os.path.exists(tmp_path):
                        os.remove(tmp_path)
                except OSError:
                    pass

    def _usage_stats_for_page(self) -> Dict[str, Any]:
        stats = self._current_usage_stats()
        users = sorted(
            stats.get("users", {}).values(),
            key=lambda item: (-self._to_nonnegative_int(item.get("count", 0)), str(item.get("user_id", ""))),
        )
        limit = self._daily_image_limit()
        return {
            "date": stats.get("date", self._today_key()),
            "total": stats.get("total", 0),
            "users": users,
            "quota": {
                "enabled": limit > 0,
                "daily_limit": limit,
                "checkin_enabled": bool(getattr(self.plugin_config, "enable_checkin", False)),
                "checkin_bonus_min": self._to_nonnegative_int(getattr(self.plugin_config, "checkin_bonus_min", 1), 1),
                "checkin_bonus_max": self._to_nonnegative_int(getattr(self.plugin_config, "checkin_bonus_max", 3), 3),
            },
        }

    def _clean_runtime_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(config, dict):
            return {}

        def strip_template_keys(value: Any) -> Any:
            if isinstance(value, dict):
                return {key: strip_template_keys(item) for key, item in value.items() if key != "__template_key"}
            if isinstance(value, list):
                return [strip_template_keys(item) for item in value]
            return copy.deepcopy(value)

        cleaned = {key: strip_template_keys(value) for key, value in config.items() if key in CONFIG_KEYS}
        self._sync_native_active_persona_upload(cleaned)
        return cleaned

    def _sync_native_active_persona_upload(self, config: Dict[str, Any]) -> None:
        persona_config = config.get("persona_config")
        if not isinstance(persona_config, dict):
            return

        upload_refs = self._as_config_list(
            persona_config.get("persona_ref_image") or persona_config.get("persona_ref_images")
        )
        if not any(self._is_native_file_ref(ref) for ref in upload_refs):
            return

        profiles = persona_config.get("profiles")
        if not isinstance(profiles, list) or not profiles:
            profiles = [{
                "id": persona_config.get("active_persona_id") or "default",
                "persona_name": persona_config.get("persona_name", "默认助理"),
                "persona_base_prompt": persona_config.get("persona_base_prompt", ""),
                "persona_ref_image": [],
            }]
            persona_config["profiles"] = profiles

        active_profile = self._find_active_persona_profile(persona_config, profiles)
        if active_profile is not None:
            active_profile["persona_ref_image"] = upload_refs

    def _as_config_list(self, value: Any) -> List[Any]:
        if isinstance(value, list):
            return [item for item in value if item]
        if isinstance(value, tuple):
            return [item for item in value if item]
        return [value] if value else []

    def _find_active_persona_profile(self, persona_config: Dict[str, Any], profiles: List[Any]) -> Optional[Dict[str, Any]]:
        active_id = str(persona_config.get("active_persona_id") or "").strip().lower()
        dict_profiles = [profile for profile in profiles if isinstance(profile, dict)]
        if not dict_profiles:
            return None
        if active_id:
            for profile in dict_profiles:
                if str(profile.get("id") or "").strip().lower() == active_id:
                    return profile
        return dict_profiles[0]

    def _is_native_file_ref(self, image_ref: Any) -> bool:
        return str(image_ref or "").replace("\\", "/").lstrip("/").startswith("files/")

    def _native_file_ref_for_config(self, image_ref: Any) -> str:
        if not image_ref:
            return ""
        normalized = str(image_ref).replace("\\", "/").lstrip("/")
        if normalized.startswith(NATIVE_ACTIVE_PERSONA_FILE_PREFIX):
            return normalized
        if not os.path.isabs(str(image_ref)):
            return ""

        plugin_data_dir = os.path.abspath(self.data_dir)
        abs_ref = os.path.abspath(str(image_ref))
        try:
            common = os.path.commonpath([plugin_data_dir, abs_ref])
        except ValueError:
            return ""
        if common != plugin_data_dir:
            return ""
        rel_ref = os.path.relpath(abs_ref, plugin_data_dir).replace("\\", "/")
        if rel_ref.startswith(NATIVE_ACTIVE_PERSONA_FILE_PREFIX):
            return rel_ref
        return ""

    def _native_active_persona_file_refs(self, persona_config: Dict[str, Any]) -> List[str]:
        profiles = persona_config.get("profiles")
        if not isinstance(profiles, list):
            return []
        active_profile = self._find_active_persona_profile(persona_config, profiles)
        if not active_profile:
            return []
        refs = []
        for ref in self._as_config_list(active_profile.get("persona_ref_image")):
            native_ref = self._native_file_ref_for_config(ref)
            if native_ref and native_ref not in refs:
                refs.append(native_ref)
        return refs

    def _config_for_native_page(self) -> Dict[str, Any]:
        native_config = copy.deepcopy(self.raw_config)

        def mark_template_items(items: Any, template_key: str) -> List[Any]:
            if not isinstance(items, list):
                return []
            marked = []
            for item in items:
                if isinstance(item, dict):
                    item = copy.deepcopy(item)
                    item["__template_key"] = str(item.get("__template_key") or template_key)
                marked.append(item)
            return marked

        native_config["providers"] = mark_template_items(native_config.get("providers", []), "image_provider")
        native_config["video_providers"] = mark_template_items(native_config.get("video_providers", []), "video_provider")

        persona_config = native_config.get("persona_config")
        if isinstance(persona_config, dict):
            persona_config["profiles"] = mark_template_items(persona_config.get("profiles", []), "persona")
            persona_config["persona_ref_image"] = self._native_active_persona_file_refs(persona_config)
        return native_config

    def _has_config_payload(self, config: Dict[str, Any]) -> bool:
        if not isinstance(config, dict):
            return False
        if config.get("providers") or config.get("video_providers") or config.get("presets"):
            return True
        if config.get("verbose_report"):
            return True

        permission_config = config.get("permission_config")
        if isinstance(permission_config, dict):
            for key in (
                "usable_users",
                "access_users",
                "use_whitelist",
                "allowed_users",
                "unlimited_users",
                "user_whitelist",
                "blocked_users",
                "user_blacklist",
                "unlimited_groups",
                "group_whitelist",
            ):
                if str(permission_config.get(key, "")).strip():
                    return True

        usage_config = config.get("usage_config")
        if isinstance(usage_config, dict):
            if bool(usage_config.get("enable_daily_limit")):
                return True
            if self._to_nonnegative_int(usage_config.get("daily_image_limit", 20), 20) != 20:
                return True
            if bool(usage_config.get("enable_checkin")):
                return True
            if self._to_nonnegative_int(usage_config.get("checkin_bonus_min", 1), 1) != 1:
                return True
            if self._to_nonnegative_int(usage_config.get("checkin_bonus_max", 3), 3) != 3:
                return True

        cache_config = config.get("cache_config")
        if isinstance(cache_config, dict):
            if bool(cache_config.get("enable_scheduled_cleanup")):
                return True
            if self._to_nonnegative_int(
                cache_config.get("scheduled_cleanup_interval_hours", DEFAULT_CACHE_CLEANUP_INTERVAL_HOURS),
                DEFAULT_CACHE_CLEANUP_INTERVAL_HOURS,
            ) != DEFAULT_CACHE_CLEANUP_INTERVAL_HOURS:
                return True
            if bool(cache_config.get("enable_size_limit_cleanup")):
                return True
            if self._to_nonnegative_int(
                cache_config.get("max_cache_size_mb", DEFAULT_MAX_CACHE_SIZE_MB),
                DEFAULT_MAX_CACHE_SIZE_MB,
            ) != DEFAULT_MAX_CACHE_SIZE_MB:
                return True

        reply_config = config.get("reply_config")
        if isinstance(reply_config, dict):
            reply_defaults = {
                "draw_pending_message": DEFAULT_DRAW_PENDING_MESSAGE,
                "selfie_pending_message": DEFAULT_SELFIE_PENDING_MESSAGE,
                "draw_error_message": DEFAULT_DRAW_ERROR_MESSAGE,
                "selfie_error_message": DEFAULT_SELFIE_ERROR_MESSAGE,
            }
            for key, default in reply_defaults.items():
                value = str(reply_config.get(key, "")).strip()
                if value and value != default:
                    return True

        router_config = config.get("router_config")
        if isinstance(router_config, dict):
            route_defaults = {
                "chain_text2img": "node_1",
                "chain_selfie": "node_1",
                "chain_video": "video_node_1",
            }
            for key, default in route_defaults.items():
                value = router_config.get(key)
                if value not in (None, "", default):
                    return True

        optimizer_config = config.get("optimizer_config")
        if isinstance(optimizer_config, dict):
            optimizer_defaults = {
                "enable_optimizer": True,
                "optimizer_style": "手机日常原生感",
                "chain_optimizer": "node_1",
                "optimizer_model": "gpt-4o-mini",
                "optimizer_timeout": 15,
                "max_batch_count": 0,
                "optimizer_custom_prompt": "",
            }
            for key, default in optimizer_defaults.items():
                value = optimizer_config.get(key)
                if value not in (None, "", default):
                    return True

        persona_config = config.get("persona_config")
        if isinstance(persona_config, dict):
            if persona_config.get("active_persona_id") not in (None, "", "default"):
                return True
            profiles = persona_config.get("profiles")
            if isinstance(profiles, list) and profiles:
                for index, profile in enumerate(profiles):
                    if not isinstance(profile, dict):
                        continue
                    default_name = "默认助理" if index == 0 else f"人设 {index + 1}"
                    if str(profile.get("id", "")).strip() not in ("", "default" if index == 0 else f"persona_{index + 1}"):
                        return True
                    if str(profile.get("persona_name", "")).strip() not in ("", default_name):
                        return True
                    if str(profile.get("persona_base_prompt", "")).strip():
                        return True
                    if profile.get("persona_ref_image"):
                        return True
            if str(persona_config.get("persona_name", "")).strip() not in ("", "默认助理"):
                return True
            if str(persona_config.get("persona_base_prompt", "")).strip():
                return True
            if persona_config.get("persona_ref_image") or persona_config.get("persona_ref_images"):
                return True
        return False

    def _load_initial_config(self, fallback_config: Dict[str, Any]) -> Dict[str, Any]:
        native_config = self._clean_runtime_config(dict(fallback_config)) if isinstance(fallback_config, dict) else {}
        native_has_payload = self._has_config_payload(native_config)
        persisted_config = self._clean_runtime_config(self._load_json_file(self.config_path))
        persisted_has_payload = self._has_config_payload(persisted_config)

        if native_has_payload:
            if not persisted_has_payload or self._native_config_mtime >= self._persist_config_mtime:
                return native_config
            return persisted_config
        if persisted_has_payload:
            return persisted_config
        if native_config:
            return native_config
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as file:
                    data = json.load(file)
                if isinstance(data, dict):
                    return self._clean_runtime_config(data)
                logger.warning("[OmniDraw] 本地配置不是 JSON 对象，已回退到 AstrBot 原生配置。")
            except Exception as exc:
                logger.error(f"[OmniDraw] 读取本地持久化配置失败: {exc}", exc_info=True)
        return native_config

    def _apply_runtime_config(self, raw_config: Dict[str, Any]) -> None:
        self.raw_config = self._clean_runtime_config(raw_config if isinstance(raw_config, dict) else {})
        self.plugin_config = PluginConfig.from_dict(self.raw_config, self.data_dir)
        self.persona_manager = PersonaManager(self.plugin_config)
        self.video_manager = VideoManager(self.plugin_config)
        self.prompt_optimizer = PromptOptimizer(self.plugin_config)
        self._restart_cache_cleanup_task()
        self._prune_cache_if_needed("config_reload")

    def _persist_config(self) -> None:
        with self._config_lock:
            os.makedirs(self.data_dir, exist_ok=True)
            tmp_path = f"{self.config_path}.{uuid.uuid4().hex}.tmp"
            with open(tmp_path, "w", encoding="utf-8") as file:
                json.dump(self.raw_config, file, ensure_ascii=False, indent=4)
            os.replace(tmp_path, self.config_path)
            self._persist_config_mtime = self._get_mtime(self.config_path)

    def _safe_update_context_config(self) -> None:
        if self._native_config is not None and hasattr(self._native_config, "save_config"):
            try:
                native_config = self._config_for_native_page()
                self._native_config.clear()
                self._native_config.update(native_config)
                self._native_config.save_config()
                self._native_config_mtime = self._get_mtime(self._native_config_path)
                self._native_config_signature = self._file_signature(self._native_config_path)
                return
            except Exception as exc:
                logger.warning(f"[OmniDraw] AstrBot 原生配置同步失败，已保留本地持久化配置: {exc}")

        if not hasattr(self.context, "update_config"):
            return
        try:
            self.context.update_config(self.raw_config)
        except Exception as exc:
            logger.warning(f"[OmniDraw] AstrBot 主配置同步失败，已保留本地持久化配置: {exc}")

    def _refresh_from_native_config_if_changed(self) -> None:
        if not self._native_config_path:
            return
        with self._config_lock:
            current_mtime = self._get_mtime(self._native_config_path)
            current_signature = self._file_signature(self._native_config_path)
            if current_signature and current_signature == self._native_config_signature:
                return
            native_config = self._clean_runtime_config(self._load_json_file(self._native_config_path))
            if not native_config:
                self._native_config_mtime = current_mtime
                self._native_config_signature = current_signature
                return
            self._apply_runtime_config(native_config)
            self._persist_config()
            self._native_config_mtime = current_mtime
            self._native_config_signature = current_signature
            if self._native_config is not None:
                self._native_config.clear()
                self._native_config.update(self._config_for_native_page())
            logger.info("[OmniDraw] 已从 AstrBot 原生配置热同步最新设置。")

    async def get_config_handler(self):
        self._refresh_from_native_config_if_changed()
        return jsonify(self._config_for_page())

    async def get_usage_stats_handler(self):
        self._refresh_from_native_config_if_changed()
        stats = await asyncio.to_thread(self._usage_stats_for_page)
        return jsonify({"success": True, "stats": stats})

    async def get_cache_stats_handler(self):
        self._refresh_from_native_config_if_changed()
        stats = await asyncio.to_thread(self._cache_stats_for_page)
        return jsonify({"success": True, "stats": stats})

    def _config_for_page(self) -> Dict[str, Any]:
        self._page_image_tokens.clear()
        page_config = copy.deepcopy(self.raw_config)
        persona_config = page_config.get("persona_config")
        if not isinstance(persona_config, dict):
            return page_config

        profiles = persona_config.get("profiles")
        if isinstance(profiles, list):
            for profile in profiles:
                if not isinstance(profile, dict):
                    continue
                raw_profile_images = profile.get("persona_ref_image", [])
                if not isinstance(raw_profile_images, list):
                    raw_profile_images = [raw_profile_images] if raw_profile_images else []
                profile["persona_ref_image"] = self._image_refs_for_page(raw_profile_images)

        raw_images = persona_config.get("persona_ref_image", [])
        if not isinstance(raw_images, list):
            raw_images = [raw_images] if raw_images else []
        persona_config["persona_ref_image"] = self._image_refs_for_page(raw_images)
        return page_config

    def _image_refs_for_page(self, image_refs: Iterable[Any]) -> List[str]:
        refs = []
        for image_ref in image_refs:
            if not image_ref:
                continue
            page_ref = self._image_ref_for_page(image_ref)
            if page_ref:
                refs.append(page_ref)
        return refs

    def _image_ref_for_page(self, image_ref: str) -> str:
        image_ref = str(image_ref)
        resolved_preview = self._resolve_page_image_ref(image_ref)
        if resolved_preview:
            image_ref = resolved_preview
        elif self._is_page_image_preview_ref(image_ref):
            return ""

        if image_ref.startswith(("http", "data:image")):
            return image_ref
        if not os.path.exists(image_ref):
            return image_ref
        try:
            if os.path.getsize(image_ref) > PAGE_PREVIEW_IMAGE_BYTES:
                return self._local_image_preview_url(image_ref)
            mime_type = mimetypes.guess_type(image_ref)[0] or "image/png"
            with open(image_ref, "rb") as file:
                encoded = base64.b64encode(file.read()).decode("utf-8")
            return f"data:{mime_type};base64,{encoded}"
        except OSError:
            return image_ref

    def _local_image_preview_url(self, image_ref: str) -> str:
        abs_path = os.path.abspath(image_ref)
        token = uuid.uuid5(uuid.NAMESPACE_URL, abs_path).hex
        self._page_image_tokens[token] = abs_path
        return f"/{PLUGIN_NAME}/get_image?token={token}"

    def _is_page_image_preview_ref(self, image_ref: str) -> bool:
        return f"{PLUGIN_NAME}/get_image" in str(image_ref)

    def _extract_page_image_token(self, image_ref: str) -> str:
        if not self._is_page_image_preview_ref(image_ref):
            return ""
        try:
            parsed = urlparse(str(image_ref))
            token = parse_qs(parsed.query).get("token", [""])[0]
        except Exception:
            token = ""
        return str(token).strip()

    def _resolve_page_image_ref(self, image_ref: str) -> str:
        token = self._extract_page_image_token(image_ref)
        if not token:
            return ""
        image_path = self._page_image_tokens.get(token, "")
        return image_path if image_path and os.path.exists(image_path) else ""

    def _normalize_saved_page_images(self, config: Dict[str, Any]) -> None:
        persona_config = config.get("persona_config")
        if not isinstance(persona_config, dict):
            return

        def normalize_refs(value: Any) -> List[str]:
            if isinstance(value, list):
                raw_refs = value
            elif value:
                raw_refs = [value]
            else:
                raw_refs = []

            refs = []
            for ref in raw_refs:
                ref_str = str(ref or "")
                if not ref_str:
                    continue
                if self._is_page_image_preview_ref(ref_str):
                    resolved = self._resolve_page_image_ref(ref_str)
                    if resolved:
                        refs.append(resolved)
                    continue
                refs.append(ref_str)
            return refs

        persona_config["persona_ref_image"] = normalize_refs(persona_config.get("persona_ref_image", []))
        profiles = persona_config.get("profiles", [])
        if isinstance(profiles, list):
            for profile in profiles:
                if isinstance(profile, dict):
                    profile["persona_ref_image"] = normalize_refs(profile.get("persona_ref_image", []))

    async def get_image_handler(self):
        token = str(request.args.get("token", "")).strip()
        image_path = self._page_image_tokens.get(token)
        if not image_path or not os.path.exists(image_path):
            return jsonify({"success": False, "message": "参考图预览已失效，请刷新配置页。"}), 404

        mime_type = mimetypes.guess_type(image_path)[0] or "image/png"
        return await send_file(image_path, mimetype=mime_type)

    async def generate_image_for_plugin_handler(self):
        payload = await request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"success": False, "message": "请求体必须是 JSON 对象。"}), 400

        try:
            result = await self.generate_images_for_plugin(
                prompt=str(payload.get("prompt", payload.get("action", "")) or ""),
                count=payload.get("count", 1),
                aspect_ratio=str(payload.get("aspect_ratio", "") or ""),
                size=str(payload.get("size", "") or ""),
                extra_params=str(payload.get("extra_params", "") or ""),
                refs=payload.get("refs", payload.get("user_refs", [])),
                mode="selfie" if "selfie" in payload and self._plugin_bool(payload.get("selfie"), default=False) else str(
                    payload.get("mode", payload.get("chain_type", payload.get("type", ""))) or ""
                ),
                event=None,
                record_usage=False,
            )
            status_code = 200 if result.get("success") else 500
            return jsonify(result), status_code
        except Exception as exc:
            logger.error(f"[OmniDraw] 插件生图 API 失败: {exc}", exc_info=True)
            return jsonify({
                "success": False,
                "message": f"画图失败 ({self._safe_plugin_error_message(exc)})。",
                "images": [],
            }), 500

    async def save_config_handler(self):
        new_config = await request.get_json(silent=True)
        if not isinstance(new_config, dict):
            return jsonify({"success": False, "message": "配置格式错误：请求体必须是 JSON 对象。"}), 400

        try:
            with self._config_lock:
                self._normalize_saved_page_images(new_config)
                self._apply_runtime_config(new_config)
                self._persist_config()
                self._safe_update_context_config()
        except Exception as exc:
            logger.error(f"[OmniDraw] 配置保存失败: {exc}", exc_info=True)
            return jsonify({"success": False, "message": f"配置保存失败: {exc}"}), 500

        logger.info(f"[OmniDraw] 配置已持久化并热重载: {self.config_path}")
        return jsonify({"success": True, "message": "配置已保存，热重载生效。"})

    async def clear_cache_handler(self):
        self._refresh_from_native_config_if_changed()
        result = await asyncio.to_thread(lambda: self._clear_cache_images(reason="webui"))
        stats = await asyncio.to_thread(self._cache_stats_for_page)
        return jsonify({"success": True, "message": "缓存已清理。", "cleanup": result, "stats": stats})

    def _create_background_task(self, coro: Any) -> asyncio.Task:
        task = asyncio.create_task(coro)
        self._background_tasks.add(task)

        def _cleanup(done_task: asyncio.Task) -> None:
            self._background_tasks.discard(done_task)
            if done_task.cancelled():
                return
            try:
                exc = done_task.exception()
            except asyncio.CancelledError:
                return
            if exc:
                logger.error(
                    f"[OmniDraw] 后台任务异常退出: {exc}",
                    exc_info=(type(exc), exc, exc.__traceback__),
                )

        task.add_done_callback(_cleanup)
        return task

    async def terminate(self):
        if not self._background_tasks:
            return
        tasks = list(self._background_tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._background_tasks.clear()
        self._cache_cleanup_task = None
        logger.info("[OmniDraw] 已取消所有后台视频任务。")

    def _cache_dir_paths(self) -> Dict[str, str]:
        return {name: os.path.abspath(os.path.join(self.data_dir, name)) for name in CACHE_DIR_NAMES}

    def _is_cache_image_file(self, file_path: str, root_path: str) -> bool:
        abs_file = os.path.abspath(file_path)
        abs_root = os.path.abspath(root_path)
        try:
            common = os.path.commonpath([abs_root, abs_file])
        except ValueError:
            return False
        if common != abs_root:
            return False
        return os.path.splitext(abs_file)[1].lower() in CACHE_IMAGE_EXTENSIONS

    def _iter_cache_image_files(self) -> List[Dict[str, Any]]:
        files = []
        for cache_name, root_path in self._cache_dir_paths().items():
            if not os.path.isdir(root_path):
                continue
            for current_root, _, filenames in os.walk(root_path):
                abs_current_root = os.path.abspath(current_root)
                try:
                    if os.path.commonpath([root_path, abs_current_root]) != root_path:
                        continue
                except ValueError:
                    continue
                for filename in filenames:
                    file_path = os.path.abspath(os.path.join(abs_current_root, filename))
                    if not self._is_cache_image_file(file_path, root_path):
                        continue
                    try:
                        stat = os.stat(file_path)
                    except OSError:
                        continue
                    if not os.path.isfile(file_path):
                        continue
                    files.append(
                        {
                            "cache_name": cache_name,
                            "path": file_path,
                            "bytes": max(0, int(stat.st_size)),
                            "mtime": float(stat.st_mtime),
                        }
                    )
        return files

    def _format_bytes(self, size: int) -> str:
        value = float(max(0, int(size or 0)))
        for unit in ("B", "KB", "MB", "GB"):
            if value < 1024 or unit == "GB":
                return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
            value /= 1024
        return f"{value:.1f} GB"

    def _cache_stats_for_page(self) -> Dict[str, Any]:
        dir_paths = self._cache_dir_paths()
        dir_stats = {
            name: {
                "path": path,
                "count": 0,
                "bytes": 0,
                "human_size": "0 B",
            }
            for name, path in dir_paths.items()
        }

        files = self._iter_cache_image_files()
        for item in files:
            stats = dir_stats.get(item["cache_name"])
            if not stats:
                continue
            stats["count"] += 1
            stats["bytes"] += item["bytes"]

        total_bytes = 0
        total_count = 0
        for stats in dir_stats.values():
            total_bytes += stats["bytes"]
            total_count += stats["count"]
            stats["human_size"] = self._format_bytes(stats["bytes"])

        return {
            "dirs": dir_stats,
            "total": {
                "count": total_count,
                "bytes": total_bytes,
                "human_size": self._format_bytes(total_bytes),
            },
            "targets": list(CACHE_DIR_NAMES),
            "image_extensions": sorted(CACHE_IMAGE_EXTENSIONS),
            "scanned_at": int(time.time()),
        }

    def _delete_cache_files(
        self,
        files: Iterable[Dict[str, Any]],
        reason: str = "manual",
        protected_paths: Optional[Iterable[str]] = None,
    ) -> Dict[str, Any]:
        dir_paths = self._cache_dir_paths()
        protected = {os.path.abspath(path) for path in (protected_paths or []) if path}
        result = {
            "reason": reason,
            "deleted_count": 0,
            "deleted_bytes": 0,
            "failed_count": 0,
            "skipped_count": 0,
            "human_deleted_size": "0 B",
            "dirs": {
                name: {"deleted_count": 0, "deleted_bytes": 0, "human_deleted_size": "0 B"}
                for name in CACHE_DIR_NAMES
            },
            "failed": [],
        }

        for item in files:
            cache_name = str(item.get("cache_name", ""))
            file_path = os.path.abspath(str(item.get("path", "")))
            root_path = dir_paths.get(cache_name)
            if not file_path or not root_path or file_path in protected:
                result["skipped_count"] += 1
                continue
            if not self._is_cache_image_file(file_path, root_path):
                result["skipped_count"] += 1
                continue
            try:
                file_size = os.path.getsize(file_path) if os.path.exists(file_path) else int(item.get("bytes", 0))
                os.remove(file_path)
                result["deleted_count"] += 1
                result["deleted_bytes"] += max(0, int(file_size))
                dir_result = result["dirs"].setdefault(
                    cache_name,
                    {"deleted_count": 0, "deleted_bytes": 0, "human_deleted_size": "0 B"},
                )
                dir_result["deleted_count"] += 1
                dir_result["deleted_bytes"] += max(0, int(file_size))
            except OSError as exc:
                result["failed_count"] += 1
                result["failed"].append({"path": file_path, "error": str(exc)})

        result["human_deleted_size"] = self._format_bytes(result["deleted_bytes"])
        for dir_result in result["dirs"].values():
            dir_result["human_deleted_size"] = self._format_bytes(dir_result["deleted_bytes"])
        return result

    def _clear_cache_images(self, reason: str = "manual") -> Dict[str, Any]:
        before = self._cache_stats_for_page()
        result = self._delete_cache_files(self._iter_cache_image_files(), reason=reason)
        result["before"] = before["total"]
        result["after"] = self._cache_stats_for_page()["total"]
        logger.info(
            f"[OmniDraw] 缓存清理完成({reason})：删除 {result['deleted_count']} 个图片文件，"
            f"释放 {result['human_deleted_size']}。"
        )
        return result

    def _cache_size_limit_bytes(self) -> int:
        configured_mb = self._to_nonnegative_int(
            getattr(self.plugin_config, "max_cache_size_mb", DEFAULT_MAX_CACHE_SIZE_MB),
            DEFAULT_MAX_CACHE_SIZE_MB,
        )
        return max(1, configured_mb) * 1024 * 1024

    def _prune_cache_if_needed(
        self,
        trigger: str = "auto",
        protected_paths: Optional[Iterable[str]] = None,
    ) -> Dict[str, Any]:
        if not getattr(self.plugin_config, "enable_size_limit_cleanup", False):
            return {"skipped": True, "reason": "size_limit_disabled"}

        files = self._iter_cache_image_files()
        total_bytes = sum(item["bytes"] for item in files)
        limit_bytes = self._cache_size_limit_bytes()
        if total_bytes <= limit_bytes:
            return {"skipped": True, "reason": "under_limit", "total_bytes": total_bytes, "limit_bytes": limit_bytes}

        protected = {os.path.abspath(path) for path in (protected_paths or []) if path}
        candidates = sorted(files, key=lambda item: (item.get("mtime", 0), item.get("path", "")))
        delete_files = []
        remaining_bytes = total_bytes
        for item in candidates:
            if remaining_bytes <= limit_bytes:
                break
            file_path = os.path.abspath(str(item.get("path", "")))
            if file_path in protected:
                continue
            delete_files.append(item)
            remaining_bytes -= item["bytes"]

        if not delete_files:
            return {
                "skipped": True,
                "reason": "only_protected_files_over_limit",
                "total_bytes": total_bytes,
                "limit_bytes": limit_bytes,
            }

        result = self._delete_cache_files(delete_files, reason=f"size_limit:{trigger}", protected_paths=protected)
        result["before"] = {"bytes": total_bytes, "human_size": self._format_bytes(total_bytes), "count": len(files)}
        result["after"] = self._cache_stats_for_page()["total"]
        logger.info(
            f"[OmniDraw] 缓存达到上限，自动清理 {result['deleted_count']} 个图片文件，"
            f"释放 {result['human_deleted_size']}。"
        )
        return result

    def _cache_cleanup_interval_seconds(self) -> int:
        configured_hours = self._to_nonnegative_int(
            getattr(self.plugin_config, "scheduled_cleanup_interval_hours", DEFAULT_CACHE_CLEANUP_INTERVAL_HOURS),
            DEFAULT_CACHE_CLEANUP_INTERVAL_HOURS,
        )
        return max(1, configured_hours) * 3600

    def _restart_cache_cleanup_task(self) -> None:
        current = getattr(self, "_cache_cleanup_task", None)
        try:
            current_task = asyncio.current_task()
        except RuntimeError:
            current_task = None
        if current and not current.done() and current is not current_task:
            current.cancel()
        self._cache_cleanup_task = None

        if not getattr(self.plugin_config, "enable_scheduled_cleanup", False):
            return

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            logger.warning("[OmniDraw] 当前没有运行中的事件循环，定时缓存清理将在下次配置热加载后启动。")
            return

        self._cache_cleanup_task = self._create_background_task(self._cache_cleanup_scheduler())
        logger.info(
            f"[OmniDraw] 已启用定时缓存清理，每 {self._cache_cleanup_interval_seconds() // 3600} 小时清理一次。"
        )

    async def _cache_cleanup_scheduler(self) -> None:
        try:
            while getattr(self.plugin_config, "enable_scheduled_cleanup", False):
                await asyncio.sleep(self._cache_cleanup_interval_seconds())
                if not getattr(self.plugin_config, "enable_scheduled_cleanup", False):
                    return
                self._clear_cache_images(reason="scheduled")
        except asyncio.CancelledError:
            raise

    def _extract_at_user_id(self, obj: Any) -> str:
        for attr in ("qq", "user_id", "target", "id", "uin"):
            value = getattr(obj, attr, None)
            if value:
                return str(value).strip()
        return ""

    def _build_qq_avatar_url(self, user_id: str) -> str:
        user_id = str(user_id or "").strip()
        if not user_id or user_id.lower() == "all" or not re.fullmatch(r"\d+", user_id):
            return ""
        return f"https://q1.qlogo.cn/g?b=qq&nk={user_id}&s=640"

    def _message_component_has_command(self, obj: Any, command: str) -> bool:
        if not command or type(obj).__name__ != "Plain":
            return False
        text = str(getattr(obj, "text", "") or "")
        pattern = rf"(^|\s)[/!！.]?{re.escape(command)}(?:\s|$)"
        return bool(re.search(pattern, text))

    def _get_event_images(
        self,
        event: AstrMessageEvent,
        include_at_avatars: bool = False,
        at_after_command: str = "",
    ) -> List[str]:
        images = []
        visited = set()
        allow_at_avatar = not bool(at_after_command)

        def _search(obj: Any) -> None:
            nonlocal allow_at_avatar
            if obj is None or id(obj) in visited:
                return
            visited.add(id(obj))
            obj_type = type(obj).__name__

            if obj_type == "Image":
                path = getattr(obj, "path", getattr(obj, "file", getattr(obj, "file_path", None)))
                url = getattr(obj, "url", None)
                ref = path if path and not str(path).startswith("http") else url
                if ref:
                    images.append(str(ref))
                return

            if include_at_avatars and allow_at_avatar and (obj_type == "At" or isinstance(obj, At)):
                avatar_url = self._build_qq_avatar_url(self._extract_at_user_id(obj))
                if avatar_url:
                    images.append(avatar_url)
                return

            if obj_type == "Plain":
                if self._message_component_has_command(obj, at_after_command):
                    allow_at_avatar = True
                text = getattr(obj, "text", "")
                if text and str(text).startswith("data:image"):
                    images.append(str(text))
                return

            if isinstance(obj, (list, tuple)):
                for item in obj:
                    _search(item)
                return

            attrs = []
            if hasattr(obj, "__dict__"):
                attrs.extend(vars(obj).keys())
            if hasattr(obj, "__slots__"):
                attrs.extend(obj.__slots__)
            blocked = {"context", "star", "bot", "provider", "session", "config", "plugin_config"}
            for key in set(attrs) - blocked:
                try:
                    _search(getattr(obj, key))
                except Exception:
                    continue

        _search(getattr(event, "message_obj", None))
        quote_obj = getattr(getattr(event, "message_obj", None), "quote", None)
        if quote_obj:
            _search(quote_obj)

        seen = set()
        return [item for item in images if not (item in seen or seen.add(item))]

    async def _read_response_limited(self, response: aiohttp.ClientResponse, limit: int = MAX_IMAGE_BYTES) -> bytes:
        chunks = []
        total = 0
        async for chunk in response.content.iter_chunked(64 * 1024):
            total += len(chunk)
            if total > limit:
                raise ValueError(f"图片超过大小限制 {limit // 1024 // 1024}MB")
            chunks.append(chunk)
        return b"".join(chunks)

    async def _process_and_save_images(self, raw_images: Iterable[str], session: Optional[aiohttp.ClientSession] = None) -> List[str]:
        processed_paths = []
        if not raw_images:
            return processed_paths

        save_dir = os.path.join(self.data_dir, "user_refs")
        os.makedirs(save_dir, exist_ok=True)
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

        session_obj = session
        session_owner = False
        try:
            for idx, img_ref in enumerate(raw_images):
                if not img_ref:
                    continue
                img_ref = str(img_ref)

                if img_ref.startswith("data:image"):
                    try:
                        decoded, content_type = split_data_url(img_ref)
                        if len(decoded) > MAX_IMAGE_BYTES:
                            raise ValueError("Base64 图片超过大小限制")
                        file_path = await asyncio.to_thread(
                            save_image_bytes,
                            decoded,
                            save_dir,
                            img_ref,
                            "ref",
                            idx,
                            content_type,
                        )
                        processed_paths.append(file_path)
                    except (IndexError, ValueError, binascii.Error, OSError) as exc:
                        logger.warning(f"[OmniDraw] Base64 参考图处理失败: {exc}")
                    continue

                if not img_ref.startswith("http"):
                    abs_path = os.path.abspath(img_ref)
                    if os.path.exists(abs_path):
                        try:
                            if os.path.getsize(abs_path) > MAX_IMAGE_BYTES:
                                raise ValueError(f"图片超过大小限制 {MAX_IMAGE_BYTES // 1024 // 1024}MB")
                        except OSError as exc:
                            logger.warning(f"[OmniDraw] 本地参考图无法读取: {abs_path} ({exc})")
                            continue
                        except ValueError as exc:
                            logger.warning(f"[OmniDraw] 本地参考图超过大小限制: {abs_path} ({exc})")
                            continue
                        processed_paths.append(abs_path)
                    else:
                        logger.warning(f"[OmniDraw] 本地参考图不存在: {abs_path}")
                    continue

                if session_obj is None:
                    session_obj = aiohttp.ClientSession()
                    session_owner = True

                for attempt in range(1, 4):
                    try:
                        async with session_obj.get(img_ref, headers=headers, timeout=15) as response:
                            if response.status != 200:
                                logger.warning(f"[OmniDraw] 下载参考图失败，状态码 {response.status}: {img_ref}")
                                continue
                            img_data = await self._read_response_limited(response)
                            file_path = await asyncio.to_thread(
                                save_image_bytes,
                                img_data,
                                save_dir,
                                img_ref,
                                "ref",
                                idx,
                                response.headers.get("Content-Type", ""),
                            )
                            processed_paths.append(file_path)
                            break
                    except Exception as exc:
                        if attempt == 3:
                            logger.warning(f"[OmniDraw] 参考图下载失败: {img_ref} ({exc})")
                        else:
                            await asyncio.sleep(1)

            await asyncio.to_thread(lambda: self._prune_cache_if_needed("user_refs", protected_paths=processed_paths))
        finally:
            if session_owner:
                await session_obj.close()
        return processed_paths

    def _normalize_count(self, count: Any) -> int:
        try:
            parsed_count = int(float(str(count).strip()))
        except Exception:
            parsed_count = 1
        limit = self.plugin_config.max_batch_count or DEFAULT_BATCH_LIMIT
        return min(max(1, parsed_count), max(1, limit))

    def _get_event_user_id(self, event: AstrMessageEvent) -> str:
        try:
            sender_id = event.get_sender_id()
            if sender_id:
                return str(sender_id)
        except Exception:
            pass

        message_obj = getattr(event, "message_obj", None)
        for attr in ("sender_id", "user_id", "member_id"):
            value = getattr(event, attr, None) or getattr(message_obj, attr, None)
            if value:
                return str(value)
        return "unknown"

    def _get_event_user_label(self, event: AstrMessageEvent) -> str:
        for method_name in ("get_sender_name", "get_sender_nickname"):
            method = getattr(event, method_name, None)
            if callable(method):
                try:
                    value = method()
                    if value:
                        return str(value)
                except Exception:
                    pass

        message_obj = getattr(event, "message_obj", None)
        sender = getattr(message_obj, "sender", None)
        for obj in (sender, message_obj, event):
            for attr in ("nickname", "card", "username", "name", "sender_name"):
                value = getattr(obj, attr, None)
                if value:
                    return str(value)
        return ""

    def _event_is_group_message(self, event: AstrMessageEvent) -> bool:
        method = getattr(event, "get_message_type", None)
        if callable(method):
            try:
                value = method()
                raw_value = getattr(value, "value", value)
                if "group" in str(raw_value).lower():
                    return True
            except Exception:
                pass

        message_obj = getattr(event, "message_obj", None)
        for obj in (message_obj, event):
            for attr in ("type", "message_type"):
                value = getattr(obj, attr, None)
                raw_value = getattr(value, "value", value)
                if "group" in str(raw_value).lower():
                    return True
        return False

    def _get_event_group_id(self, event: AstrMessageEvent) -> str:
        for method_name in ("get_group_id",):
            method = getattr(event, method_name, None)
            if callable(method):
                try:
                    value = method()
                    if value:
                        return str(value)
                except Exception:
                    pass

        message_obj = getattr(event, "message_obj", None)
        for obj in (message_obj, event):
            for attr in ("group_id", "group", "room_id", "channel_id"):
                value = getattr(obj, attr, None)
                if value:
                    return str(value)

        if self._event_is_group_message(event):
            for method_name in ("get_session_id",):
                method = getattr(event, method_name, None)
                if callable(method):
                    try:
                        value = str(method() or "").strip()
                        if value:
                            return value
                    except Exception:
                        pass
            for obj in (event, message_obj):
                value = str(getattr(obj, "session_id", "") or "").strip()
                if value:
                    return value

        for method_name in ("get_session_id",):
            method = getattr(event, method_name, None)
            if callable(method):
                try:
                    value = method()
                    group_id = self._extract_group_id_from_text(value)
                    if group_id:
                        return group_id
                except Exception:
                    pass

        for obj in (event, message_obj):
            for attr in ("unified_msg_origin", "session_id", "session", "origin"):
                group_id = self._extract_group_id_from_text(getattr(obj, attr, ""))
                if group_id:
                    return group_id
        return ""

    def _extract_group_id_from_text(self, value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        parts = text.split(":", 2)
        if len(parts) == 3 and "group" in parts[1].lower():
            return parts[2].strip()
        lowered = text.lower()
        if "group" not in lowered and "群" not in text:
            return ""
        labelled_match = re.search(r"(?:group_id|group|群)[=:_\-\s]+(\d+)", text, flags=re.I)
        if labelled_match:
            return labelled_match.group(1)
        matches = re.findall(r"\d+", text)
        return matches[0] if matches else ""

    def _config_id_set(self, value: Any) -> set:
        if isinstance(value, (list, tuple, set)):
            source = value
        else:
            source = re.split(r"[\s,]+", str(value or "").replace("\r", "\n"))
        return {str(item).strip() for item in source if str(item).strip()}

    def _access_status(self, event: AstrMessageEvent, refresh: bool = True) -> Dict[str, Any]:
        if refresh:
            self._refresh_from_native_config_if_changed()

        user_id = self._get_event_user_id(event)
        group_id = self._get_event_group_id(event)
        usable_users = self._config_id_set(getattr(self.plugin_config, "usable_users", []))
        blocked_users = self._config_id_set(getattr(self.plugin_config, "blocked_users", []))
        unlimited_users = self._config_id_set(getattr(self.plugin_config, "unlimited_users", []))
        if not unlimited_users:
            unlimited_users = self._config_id_set(getattr(self.plugin_config, "allowed_users", []))
        unlimited_groups = self._config_id_set(getattr(self.plugin_config, "unlimited_groups", []))

        status = {
            "user_id": user_id,
            "group_id": group_id,
            "allowed": True,
            "unlimited": False,
            "level": "limited",
            "reason": "",
        }
        if user_id in blocked_users:
            status.update({"allowed": False, "level": "blocked_user", "reason": "用户黑名单"})
            return status
        if usable_users and user_id not in usable_users:
            status.update({"allowed": False, "level": "not_usable_user", "reason": "可使用人员白名单"})
            return status
        if usable_users:
            status.update({"level": "usable_user", "reason": "可使用人员白名单"})
        if user_id in unlimited_users:
            status.update({"unlimited": True, "level": "unlimited_user", "reason": "用户白名单"})
            return status
        if group_id and group_id in unlimited_groups:
            status.update({"unlimited": True, "level": "unlimited_group", "reason": "群组白名单"})
            return status
        return status

    def _permission_denied_message(self, event: AstrMessageEvent) -> str:
        status = self._access_status(event)
        if status.get("allowed", True):
            return ""
        if status.get("level") == "not_usable_user":
            return f"{MessageEmoji.WARNING} 当前仅允许可使用人员白名单内用户使用万象画卷。"
        return f"{MessageEmoji.WARNING} 你已被加入用户黑名单，无法使用万象画卷。"

    def _daily_image_limit(self) -> int:
        if not getattr(self.plugin_config, "enable_daily_limit", False):
            return 0
        configured_limit = self._to_nonnegative_int(getattr(self.plugin_config, "daily_image_limit", 20), 20)
        return max(1, configured_limit)

    def _image_quota_state(self, event: AstrMessageEvent) -> Dict[str, Any]:
        status = self._access_status(event)
        limit = self._daily_image_limit()
        user_id = status.get("user_id") or self._get_event_user_id(event)
        record = self._current_usage_stats().get("users", {}).get(user_id, {})
        used = self._to_nonnegative_int(record.get("count", 0))
        bonus = self._to_nonnegative_int(record.get("bonus", 0))
        effective_limit = 0 if status.get("unlimited") or limit <= 0 else limit + bonus
        return {
            **status,
            "base_limit": limit,
            "bonus": bonus,
            "effective_limit": effective_limit,
            "used": used,
            "remaining": max(0, effective_limit - used) if effective_limit > 0 else 0,
            "checkin_at": self._to_nonnegative_int(record.get("checkin_at", 0)),
        }

    def _image_quota_error_message(self, event: AstrMessageEvent, requested_count: int = 1) -> str:
        quota = self._image_quota_state(event)
        if not quota.get("allowed", True):
            return self._permission_denied_message(event)
        if quota.get("unlimited") or quota.get("base_limit", 0) <= 0:
            return ""

        requested_count = max(1, self._to_nonnegative_int(requested_count, 1))
        used = quota.get("used", 0)
        base_limit = quota.get("base_limit", 0)
        bonus = quota.get("bonus", 0)
        effective_limit = quota.get("effective_limit", base_limit)
        remaining = max(0, effective_limit - used)
        if requested_count <= remaining:
            return ""

        limit_text = f"{effective_limit} 张"
        if bonus:
            limit_text = f"{effective_limit} 张（基础 {base_limit} + 签到 {bonus}）"
        return (
            f"{MessageEmoji.WARNING} 今日生图额度不足：你已使用 {used}/{limit_text}，"
            f"本次需要 {requested_count} 张，剩余 {remaining} 张。"
        )

    def _record_generated_images(self, event: AstrMessageEvent, count: int = 1) -> None:
        count = self._to_nonnegative_int(count)
        if count <= 0:
            return

        with self._usage_lock:
            stats = self._current_usage_stats()
            status = self._access_status(event, refresh=False)
            user_id = status.get("user_id") or self._get_event_user_id(event)
            users = stats.setdefault("users", {})
            record = users.setdefault(user_id, {"user_id": user_id, "count": 0, "last_at": 0, "bonus": 0, "checkin_at": 0})
            record["user_id"] = user_id
            record["count"] = self._to_nonnegative_int(record.get("count", 0)) + count
            record["bonus"] = self._to_nonnegative_int(record.get("bonus", 0))
            record["checkin_at"] = self._to_nonnegative_int(record.get("checkin_at", 0))
            record["last_at"] = int(time.time())
            record["access_level"] = str(status.get("level") or "limited")
            group_id = status.get("group_id") or self._get_event_group_id(event)
            if group_id:
                record["group_id"] = group_id
            display_name = self._get_event_user_label(event).strip()
            if display_name and display_name != user_id:
                record["display_name"] = display_name
            stats["total"] = sum(self._to_nonnegative_int(item.get("count", 0)) for item in users.values())
            self._persist_usage_stats()

    def _has_permission(self, event: AstrMessageEvent) -> bool:
        return bool(self._access_status(event).get("allowed", True))

    def _get_event_text(self, event: AstrMessageEvent) -> str:
        text = getattr(event, "message_str", "") or getattr(getattr(event, "message_obj", None), "message_str", "")
        if text:
            return str(text).strip()

        message = getattr(getattr(event, "message_obj", None), "message", []) or []
        plain_text = "".join(getattr(comp, "text", "") for comp in message if isinstance(comp, Plain)).strip()
        if plain_text:
            return plain_text
        return str(getattr(event, "message_obj", "") or "").strip()

    def _extract_command_message(self, event: AstrMessageEvent, command: str, fallback: str = "") -> str:
        text = self._get_event_text(event)
        if not text:
            return fallback.strip()
        pattern = rf"^\s*[/!！.]?{re.escape(command)}(?:\s+(.*))?$"
        match = re.match(pattern, text, flags=re.S)
        return (match.group(1) or "").strip() if match else fallback.strip()

    def _create_image_component(self, image_url: str) -> Image:
        if image_url.startswith("data:image"):
            image_bytes, content_type = split_data_url(image_url)
            save_dir = os.path.join(self.data_dir, "temp_images")
            file_path = save_image_bytes(image_bytes, save_dir, image_url, "img", 0, content_type)
            self._prune_cache_if_needed("temp_images", protected_paths=[file_path])
            return Image.fromFileSystem(file_path)
        if image_url.startswith("http"):
            return Image.fromURL(image_url)
        return Image.fromFileSystem(os.path.abspath(image_url))

    def _format_generation_elapsed(self, elapsed_seconds: Optional[float]) -> str:
        try:
            seconds = max(0.0, float(elapsed_seconds))
        except (TypeError, ValueError):
            seconds = 0.0
        return f"{seconds:.1f}s"

    def _generation_metadata_lines(
        self,
        elapsed_seconds: Optional[float] = None,
        model: str = "",
    ) -> List[str]:
        lines = []
        if getattr(self.plugin_config, "show_generation_time", False) and elapsed_seconds is not None:
            lines.append(f"⏱️ 生图耗时：{self._format_generation_elapsed(elapsed_seconds)}")
        if getattr(self.plugin_config, "show_request_model", False) and str(model or "").strip():
            lines.append(f"🤖 请求模型：{str(model).strip()}")
        return lines

    def _get_image_result_url(self, result: Any) -> str:
        if isinstance(result, ChainRunResult):
            return result.image_url
        return result if isinstance(result, str) else ""

    def _build_image_success_components(
        self,
        result: Any,
        elapsed_seconds: Optional[float] = None,
        include_metadata: bool = True,
    ) -> List[Any]:
        image_url = self._get_image_result_url(result)
        components: List[Any] = []
        if include_metadata and isinstance(result, ChainRunResult):
            display_elapsed = elapsed_seconds if elapsed_seconds is not None else result.elapsed_seconds
            lines = self._generation_metadata_lines(display_elapsed, result.model)
            if lines:
                components.append(Plain("\n".join(lines) + "\n"))
        components.append(self._create_image_component(image_url))
        return components

    def _get_active_provider(self, chain_type: str = "text2img"):
        chain = self.plugin_config.chains.get(chain_type, [])
        if chain_type == "video":
            for provider_id in chain:
                provider = self.plugin_config.get_video_provider(provider_id)
                if provider:
                    return provider
            return self.plugin_config.video_providers[0] if self.plugin_config.video_providers else None

        for provider_id in chain:
            provider = self.plugin_config.get_provider(provider_id)
            if provider:
                return provider
        return self.plugin_config.providers[0] if self.plugin_config.providers else None

    def _set_chain_config(self, chain_key: str, provider_id: str) -> None:
        self.plugin_config.chains[chain_key] = [provider_id]
        if chain_key == "optimizer":
            self.raw_config.setdefault("optimizer_config", {})["chain_optimizer"] = provider_id
        else:
            config_key = "chain_text2img" if chain_key == "text2img" else f"chain_{chain_key}"
            self.raw_config.setdefault("router_config", {})[config_key] = provider_id

    def _set_provider_model(self, chain_key: str, provider_id: str, selected_model: str) -> None:
        provider_key = "video_providers" if chain_key == "video" else "providers"
        for provider in self.raw_config.get(provider_key, []):
            if isinstance(provider, dict) and str(provider.get("id", provider.get("节点ID", ""))) == provider_id:
                provider["model"] = selected_model
                if selected_model not in provider.get("available_models", []):
                    provider.setdefault("available_models", []).insert(0, selected_model)
                return

    def _find_persona_profile(self, selector: str) -> Optional[Any]:
        selector = str(selector or "").strip()
        if not selector:
            return None

        try:
            index = int(selector)
            if 1 <= index <= len(self.plugin_config.personas):
                return self.plugin_config.personas[index - 1]
            if index == 0 and self.plugin_config.personas:
                return self.plugin_config.personas[0]
        except ValueError:
            pass

        selector_lower = selector.lower()
        for persona in self.plugin_config.personas:
            if persona.id.lower() == selector_lower or persona.name.lower() == selector_lower:
                return persona
        for persona in self.plugin_config.personas:
            if selector_lower in persona.name.lower():
                return persona
        return None

    def _set_active_persona(self, persona_id: str) -> None:
        persona_conf = self.raw_config.setdefault("persona_config", {})
        persona_conf["active_persona_id"] = persona_id
        self._apply_runtime_config(self.raw_config)

    def _parse_extra_params(self, extra_params: str) -> Dict[str, Any]:
        if not extra_params:
            return {}
        _, parsed = self.cmd_parser.parse(extra_params)
        return parsed

    def _format_reply_message(self, template: str, default: str, **values: Any) -> str:
        raw_template = str(template or "").strip() or default

        class _SafeValues(dict):
            def __missing__(self, key: str) -> str:
                return "{" + key + "}"

        safe_values = _SafeValues({key: str(value) for key, value in values.items()})
        try:
            formatted = raw_template.format_map(safe_values)
        except Exception:
            formatted = raw_template
        return formatted.strip() or default

    def _format_pending_message(self, template: str, default: str, **values: Any) -> str:
        return self._format_reply_message(template, default, **values)

    def _preset_items(self) -> List[tuple]:
        presets = getattr(self.plugin_config, "presets", {}) or {}
        return [
            (str(name).strip(), str(prompt or "").strip())
            for name, prompt in presets.items()
            if str(name).strip()
        ]

    def _normalize_preset_selector(self, selector: str) -> str:
        selector = str(selector or "").strip()
        if len(selector) >= 2:
            bracket_pairs = {"[": "]", "【": "】", "「": "」", "《": "》"}
            closing = bracket_pairs.get(selector[0])
            if closing and selector.endswith(closing):
                return selector[1:-1].strip()
        return selector

    def _find_preset_name(self, selector: str) -> str:
        selector = self._normalize_preset_selector(selector)
        if not selector:
            return ""
        if selector in (getattr(self.plugin_config, "presets", {}) or {}):
            return selector

        selector_lower = selector.lower()
        for name, _ in self._preset_items():
            if name.lower() == selector_lower:
                return name
        return ""

    def _build_preset_list_message(self) -> str:
        preset_names = [name for name, _ in self._preset_items()]
        if not preset_names:
            return f"{MessageEmoji.INFO} 当前没有配置极速宏预设。"

        lines = ["✨ 预设列表"]
        lines.extend(f"{index}. {name}" for index, name in enumerate(preset_names, start=1))
        return "\n".join(lines)

    def _build_preset_detail_message(self, selector: str) -> str:
        preset_name = self._find_preset_name(selector)
        if not preset_name:
            return f"{MessageEmoji.WARNING} 找不到预设: {selector}\n可发送 /查看预设 查看所有预设名。"

        preset_prompt = (getattr(self.plugin_config, "presets", {}) or {}).get(preset_name, "")
        return f"✨ 预设详情\n名称：{preset_name}\n提示词：{preset_prompt}"

    def _build_preset_view_message(self, selector: str = "") -> str:
        selector = str(selector or "").strip()
        if selector:
            return self._build_preset_detail_message(selector)
        return self._build_preset_list_message()

    def _build_fast_preset_list_message(self) -> str:
        return self._build_preset_list_message()

    def _extract_compact_command_payload(self, text: str, command: str) -> str:
        pattern = rf"^\s*[/!！.]{re.escape(command)}(?P<payload>\S.*)$"
        match = re.match(pattern, str(text or ""), flags=re.S)
        return (match.group("payload") or "").strip() if match else ""

    def _parse_preset_add_payload(self, payload: str) -> tuple:
        payload = str(payload or "").strip()
        if not payload:
            return "", ""
        parts = payload.split(maxsplit=1)
        if len(parts) < 2:
            return parts[0].strip(), ""
        return parts[0].strip(), parts[1].strip()

    def _validate_preset_name(self, preset_name: str) -> str:
        preset_name = str(preset_name or "").strip()
        if not preset_name:
            return "缺少预设名。"
        if any(char in preset_name for char in (":", "\r", "\n", "\t")):
            return "预设名不能包含冒号、换行或制表符。"
        if preset_name.startswith(("/", "!", "！", ".")):
            return "预设名不需要包含指令前缀。"
        return ""

    def _replace_presets(self, presets: Dict[str, str]) -> None:
        normalized = [f"{name}:{prompt}" for name, prompt in presets.items()]
        with self._config_lock:
            self.raw_config["presets"] = normalized
            self._apply_runtime_config(self.raw_config)
            self._persist_config()
            self._safe_update_context_config()

    def _upsert_preset(self, preset_name: str, preset_prompt: str) -> bool:
        presets = dict(self._preset_items())
        existed = preset_name in presets
        presets[preset_name] = preset_prompt
        self._replace_presets(presets)
        return existed

    def _delete_preset(self, selector: str) -> str:
        preset_name = self._find_preset_name(selector)
        if not preset_name:
            return ""
        presets = dict(self._preset_items())
        presets.pop(preset_name, None)
        self._replace_presets(presets)
        return preset_name

    def _build_command_error_message(self, func_name: str, exc: Exception, error_kind: str = "exception") -> Optional[str]:
        func_name = str(func_name or "")
        error_text = str(exc or "").strip() or (
            "操作超时，请稍后重试" if error_kind == "timeout" else "操作失败，请联系管理员"
        )
        error_type = type(exc).__name__ if exc is not None else ""

        if func_name in {"cmd_draw", "on_message_preset"}:
            command = "画" if func_name == "cmd_draw" else "宏指令"
            return self._format_reply_message(
                self.plugin_config.draw_error_message,
                DEFAULT_DRAW_ERROR_MESSAGE,
                command=command,
                error=error_text,
                error_type=error_type,
                persona_name=getattr(self.plugin_config, "persona_name", ""),
            )

        if func_name == "cmd_selfie":
            return self._format_reply_message(
                self.plugin_config.selfie_error_message,
                DEFAULT_SELFIE_ERROR_MESSAGE,
                command="自拍",
                error=error_text,
                error_type=error_type,
                persona_name=getattr(self.plugin_config, "persona_name", ""),
            )

        return None

    def _as_plugin_image_refs(self, refs: Any) -> List[str]:
        if refs is None:
            return []
        if isinstance(refs, str):
            refs_text = refs.strip()
            if not refs_text:
                return []
            if refs_text.startswith(("[", "{")):
                try:
                    return self._as_plugin_image_refs(json.loads(refs_text))
                except Exception:
                    pass
            if refs_text.startswith("data:image"):
                return [refs_text]
            refs_iterable = re.split(r"[\r\n]+", refs_text)
        elif isinstance(refs, (list, tuple, set)):
            refs_iterable = refs
        else:
            refs_iterable = [refs]

        normalized = []
        for ref in refs_iterable:
            if isinstance(ref, dict):
                ref = (
                    ref.get("image_url")
                    or ref.get("data_url")
                    or ref.get("url")
                    or ref.get("file_path")
                    or ref.get("path")
                    or ""
                )
            ref_text = str(ref or "").strip()
            if ref_text:
                normalized.append(ref_text)
        seen = set()
        return [ref for ref in normalized if not (ref in seen or seen.add(ref))]

    def _plugin_bool(self, value: Any, default: bool = True) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        text = str(value).strip().lower()
        if text in {"1", "true", "yes", "y", "on", "启用", "是"}:
            return True
        if text in {"0", "false", "no", "n", "off", "禁用", "否"}:
            return False
        return default

    def _plugin_generation_mode(self, mode: Any) -> str:
        mode_text = str(mode or "").strip().lower()
        if mode_text in {"selfie", "persona", "persona_selfie", "portrait", "自拍", "人设自拍"}:
            return "selfie"
        return "text2img"

    def _normalize_plugin_prompts(self, prompts: Any, fallback_prompt: str, count: int) -> List[str]:
        fallback_prompt = str(fallback_prompt or "").strip()
        prompt_list = [
            str(prompt or "").strip() or fallback_prompt
            for prompt in (prompts or [])
        ]
        target_count = max(1, int(count or 1))
        if len(prompt_list) < target_count:
            prompt_list.extend([fallback_prompt] * (target_count - len(prompt_list)))
        return prompt_list[:target_count]

    def _safe_plugin_error_message(self, exc: Any) -> str:
        text = str(exc or "").strip() or "未知错误"
        text = re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]{8,}", r"\1<redacted>", text)
        text = re.sub(r"\bsk-[A-Za-z0-9][A-Za-z0-9_-]{7,}\b", "<redacted>", text)
        text = re.sub(
            r"(?i)\b(api[\s_-]*key|access[\s_-]*token|token|secret|authorization|password)\b"
            r"\s*[:=]\s*['\"]?[^'\"\s,;})]+",
            lambda match: f"{match.group(1)}=<redacted>",
            text,
        )
        text = re.sub(r"data:image/[A-Za-z0-9.+-]+;base64,[A-Za-z0-9+/=]+", "<image_data_url>", text)
        if len(text) > PLUGIN_RESULT_ERROR_MAX_LENGTH:
            text = text[: PLUGIN_RESULT_ERROR_MAX_LENGTH - 3].rstrip() + "..."
        return text

    def _serialize_plugin_image_result(
        self,
        result: Any,
        index: int,
        prompt: str = "",
    ) -> Dict[str, Any]:
        image_url = self._get_image_result_url(result)
        source_type = "file"
        url = ""
        data_url = ""
        file_path = ""
        content_type = ""

        if image_url.startswith("data:image"):
            source_type = "data_url"
            data_url = image_url
            try:
                image_bytes, content_type = split_data_url(image_url)
                save_dir = os.path.join(self.data_dir, "temp_images")
                file_path = save_image_bytes(image_bytes, save_dir, image_url, "plugin", index, content_type)
                self._prune_cache_if_needed("temp_images", protected_paths=[file_path])
            except Exception as exc:
                logger.warning(f"[OmniDraw] 插件生图结果落盘失败: {exc}")
        elif image_url.startswith("http"):
            source_type = "url"
            url = image_url
            content_type = mimetypes.guess_type(image_url)[0] or ""
        else:
            file_path = os.path.abspath(image_url)
            content_type = mimetypes.guess_type(file_path)[0] or ""

        return {
            "index": index,
            "image_url": image_url,
            "source_type": source_type,
            "url": url,
            "file_path": file_path,
            "data_url": data_url,
            "content_type": content_type,
            "provider_id": getattr(result, "provider_id", ""),
            "model": getattr(result, "model", ""),
            "elapsed_seconds": getattr(result, "elapsed_seconds", None),
            "prompt": prompt,
        }

    async def _run_text2img_generation(
        self,
        event: Optional[AstrMessageEvent],
        prompt: str,
        count: int,
        aspect_ratio: str = "",
        size: str = "",
        extra_params: str = "",
        refs: Any = None,
    ) -> Dict[str, Any]:
        async with aiohttp.ClientSession() as session:
            optimized_actions = await self.prompt_optimizer.optimize(prompt, count, session=session)
            optimized_actions = self._normalize_plugin_prompts(optimized_actions, prompt, count)
            raw_refs = (
                self._as_plugin_image_refs(refs)
                if refs is not None
                else (self._get_event_images(event) if event is not None else [])
            )
            safe_refs = await self._process_and_save_images(raw_refs, session=session)

            kwargs = {"user_refs": safe_refs} if safe_refs else {}
            if aspect_ratio:
                kwargs["aspect_ratio"] = aspect_ratio
            if size:
                kwargs["size"] = size
            kwargs.update(self._parse_extra_params(extra_params))

            chain_manager = ChainManager(self.plugin_config, session)
            tasks = [
                chain_manager.run_chain_with_metadata("text2img", optimized_action, **kwargs)
                for optimized_action in optimized_actions
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        return {
            "prompts": optimized_actions,
            "results": results,
            "requested_count": count,
            "raw_refs": raw_refs,
            "safe_refs": safe_refs,
            "mode": "text2img",
            "chain": "text2img",
        }

    async def _run_selfie_generation(
        self,
        event: Optional[AstrMessageEvent],
        action: str,
        count: int,
        aspect_ratio: str = "",
        size: str = "",
        extra_params: str = "",
        refs: Any = None,
    ) -> Dict[str, Any]:
        async with aiohttp.ClientSession() as session:
            fallback_action = action or "看着镜头微笑"
            optimized_actions = await self.prompt_optimizer.optimize(fallback_action, count, session=session)
            optimized_actions = self._normalize_plugin_prompts(optimized_actions, fallback_action, count)
            raw_refs = (
                self._as_plugin_image_refs(refs)
                if refs is not None
                else (self._get_event_images(event) if event is not None else [])
            )
            target_refs = raw_refs if raw_refs else self.plugin_config.persona_ref_images
            safe_refs = await self._process_and_save_images(target_refs, session=session)
            extra_param_kwargs = self._parse_extra_params(extra_params)

            chain_to_use = "selfie" if self.plugin_config.chains.get("selfie") else "text2img"
            chain_manager = ChainManager(self.plugin_config, session)
            prompts = []
            tasks = []
            for optimized_action in optimized_actions:
                final_prompt, kwargs = self.persona_manager.build_persona_prompt(optimized_action)
                if safe_refs:
                    kwargs["user_refs"] = safe_refs
                    if not raw_refs:
                        kwargs.pop("persona_ref", None)
                if aspect_ratio:
                    kwargs["aspect_ratio"] = aspect_ratio
                if size:
                    kwargs["size"] = size
                kwargs.update(extra_param_kwargs)
                prompts.append(final_prompt)
                tasks.append(chain_manager.run_chain_with_metadata(chain_to_use, final_prompt, **kwargs))
            results = await asyncio.gather(*tasks, return_exceptions=True)

        return {
            "prompts": prompts,
            "results": results,
            "requested_count": count,
            "raw_refs": raw_refs,
            "safe_refs": safe_refs,
            "mode": "selfie",
            "chain": chain_to_use,
        }

    def _plugin_generation_response(self, generation: Dict[str, Any]) -> Tuple[Dict[str, Any], List[Any]]:
        images = []
        valid_results = []
        errors = []
        prompts = list(generation.get("prompts", []) or [])
        for index, result in enumerate(generation.get("results", []) or [], start=1):
            result_prompt = str(prompts[index - 1]) if index <= len(prompts) else ""
            if isinstance(result, Exception):
                errors.append(self._safe_plugin_error_message(result))
                continue
            if not self._get_image_result_url(result):
                errors.append(f"empty image result at index {index}")
                continue
            valid_results.append(result)
            images.append(self._serialize_plugin_image_result(result, index, result_prompt))

        if not images:
            message = "所有绘图节点请求失败。"
            if errors:
                message = f"{message} {'; '.join(errors)}"
            return {"success": False, "message": message, "images": [], "errors": errors}, []

        response = {
            "success": True,
            "message": f"已成功生成 {len(images)} 张图片。",
            "images": images,
            "count": len(images),
            "requested_count": generation.get("requested_count", len(images)),
            "ref_count": len(generation.get("raw_refs", [])),
            "processed_ref_count": len(generation.get("safe_refs", [])),
            "mode": generation.get("mode", "text2img"),
            "chain": generation.get("chain", generation.get("mode", "text2img")),
        }
        if errors:
            response["errors"] = errors
        return response, valid_results

    async def generate_images_for_plugin(
        self,
        prompt: str,
        count: int = 1,
        aspect_ratio: str = "",
        size: str = "",
        extra_params: str = "",
        refs: Any = None,
        mode: str = "",
        event: Optional[AstrMessageEvent] = None,
        record_usage: bool = False,
    ) -> Dict[str, Any]:
        """Generate image(s) for another plugin and return serializable image data.

        This method deliberately does not call event.send(). Existing chat commands
        and LLM tools keep their original "generate and send" behavior.
        """
        self._refresh_from_native_config_if_changed()
        prompt = str(prompt or "").strip()
        raw_refs = self._as_plugin_image_refs(refs)
        generation_mode = self._plugin_generation_mode(mode)
        if not prompt and not raw_refs and generation_mode != "selfie":
            return {"success": False, "message": "缺少 prompt 或 refs。", "images": []}

        count = self._normalize_count(count)
        if event is not None:
            permission_error = self._permission_denied_message(event)
            if permission_error:
                return {"success": False, "message": permission_error, "images": []}
            quota_error = self._image_quota_error_message(event, count)
            if quota_error:
                return {"success": False, "message": quota_error, "images": []}

        if generation_mode == "selfie":
            generation = await self._run_selfie_generation(
                event,
                prompt,
                count,
                aspect_ratio=aspect_ratio,
                size=size,
                extra_params=extra_params,
                refs=raw_refs,
            )
        else:
            generation = await self._run_text2img_generation(
                event,
                prompt or "根据参考图生成一张自然、清晰、符合原图语义的图片。",
                count,
                aspect_ratio=aspect_ratio,
                size=size,
                extra_params=extra_params,
                refs=raw_refs,
            )

        response, valid_results = self._plugin_generation_response(generation)
        if not response.get("success"):
            return response

        if event is not None and record_usage:
            self._record_generated_images(event, len(valid_results))
        return response

    async def _send_generated_images(
        self,
        event: AstrMessageEvent,
        results: Iterable[Any],
        elapsed_seconds: Optional[float] = None,
        include_metadata: bool = False,
    ) -> int:
        sent = 0
        for result in results:
            if not self._get_image_result_url(result):
                continue
            await event.send(event.chain_result(
                self._build_image_success_components(result, elapsed_seconds, include_metadata=include_metadata)
            ))
            sent += 1
            await asyncio.sleep(0.5)
        return sent

    @filter.command("万象帮助")
    @handle_errors
    async def cmd_help(self, event: AstrMessageEvent) -> AsyncGenerator[Any, None]:
        msg = (
            f"📖 万象画卷 v{PLUGIN_VERSION}\n"
            "/画 [提示词] [--参数 值]\n"
            "/自拍 [动作] [--参数 值]\n"
            "/视频 [提示词] [--参数 值]\n"
            "/人设\n"
            "/切换人设 [序号/ID/名称]\n"
            "/切换链路 [画图/自拍/视频/副脑] [节点ID]\n"
            "/切换模型 [画图/自拍/视频] [序号或名称]\n"
            "/签到\n"
            "/清理缓存\n"
            "/查看预设 [预设名]\n"
            "/添加预设 [预设名] [提示词]\n"
            "/删除预设 [预设名]\n"
            "/万象帮助\n\n"
        )
        if self.plugin_config.presets:
            msg += "✨ 预设:\n" + "\n".join([f"/{preset}" for preset in self.plugin_config.presets.keys()])
        yield event.plain_result(msg)

    @filter.command("查看预设")
    @handle_errors
    async def cmd_view_presets(
        self,
        event: AstrMessageEvent,
        p1: str = "",
        p2: str = "",
        p3: str = "",
        p4: str = "",
        p5: str = "",
    ) -> AsyncGenerator[Any, None]:
        fallback = " ".join(str(item) for item in [p1, p2, p3, p4, p5] if item).strip()
        selector = self._extract_command_message(event, "查看预设", fallback)
        yield event.plain_result(self._build_preset_view_message(selector))

    @filter.command("极速宏")
    @handle_errors
    async def cmd_fast_preset_list(self, event: AstrMessageEvent) -> AsyncGenerator[Any, None]:
        yield event.plain_result(self._build_fast_preset_list_message())

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("添加预设")
    @handle_errors
    async def cmd_add_preset(
        self,
        event: AstrMessageEvent,
        p1: str = "",
        p2: str = "",
        p3: str = "",
        p4: str = "",
        p5: str = "",
        p6: str = "",
        p7: str = "",
        p8: str = "",
        p9: str = "",
        p10: str = "",
    ) -> AsyncGenerator[Any, None]:
        fallback = " ".join(str(item) for item in [p1, p2, p3, p4, p5, p6, p7, p8, p9, p10] if item).strip()
        payload = self._extract_command_message(event, "添加预设", fallback)
        preset_name, preset_prompt = self._parse_preset_add_payload(payload)
        name_error = self._validate_preset_name(preset_name)
        if name_error:
            yield event.plain_result(f"{MessageEmoji.WARNING} {name_error}\n用法: /添加预设 [预设名] [提示词]")
            return
        if not preset_prompt:
            yield event.plain_result(f"{MessageEmoji.WARNING} 缺少提示词。\n用法: /添加预设 [预设名] [提示词]")
            return

        existed = self._upsert_preset(preset_name, preset_prompt)
        action = "已更新" if existed else "已添加"
        yield event.plain_result(f"{MessageEmoji.SUCCESS} {action}预设「{preset_name}」。")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("删除预设")
    @handle_errors
    async def cmd_delete_preset(
        self,
        event: AstrMessageEvent,
        p1: str = "",
        p2: str = "",
        p3: str = "",
        p4: str = "",
        p5: str = "",
    ) -> AsyncGenerator[Any, None]:
        fallback = " ".join(str(item) for item in [p1, p2, p3, p4, p5] if item).strip()
        selector = self._extract_command_message(event, "删除预设", fallback)
        if not selector:
            yield event.plain_result(f"{MessageEmoji.WARNING} 缺少预设名。\n用法: /删除预设 [预设名]")
            return

        deleted_name = self._delete_preset(selector)
        if not deleted_name:
            yield event.plain_result(f"{MessageEmoji.WARNING} 找不到预设: {selector}\n可发送 /查看预设 查看所有预设名。")
            return
        yield event.plain_result(f"{MessageEmoji.SUCCESS} 已删除预设「{deleted_name}」。")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("清理缓存")
    @handle_errors
    async def cmd_clear_cache(self, event: AstrMessageEvent) -> AsyncGenerator[Any, None]:
        result = await asyncio.to_thread(lambda: self._clear_cache_images(reason="command"))
        yield event.plain_result(
            f"{MessageEmoji.SUCCESS} 缓存清理完成：删除 {result['deleted_count']} 个图片文件，"
            f"释放 {result['human_deleted_size']}。\n"
            "范围：仅 temp_images 与 user_refs 内的图片文件。"
        )

    @filter.command("签到")
    @handle_errors
    async def cmd_checkin(self, event: AstrMessageEvent) -> AsyncGenerator[Any, None]:
        status = self._access_status(event)
        if not status.get("allowed", True):
            yield event.plain_result(self._permission_denied_message(event))
            return
        if status.get("unlimited"):
            yield event.plain_result(f"{MessageEmoji.INFO} 你已命中{status.get('reason') or '白名单'}，今日生图不受次数限制，无需签到。")
            return
        if self._daily_image_limit() <= 0:
            yield event.plain_result(f"{MessageEmoji.INFO} 当前未启用每日生图限制，无需签到。")
            return
        if not getattr(self.plugin_config, "enable_checkin", False):
            yield event.plain_result(f"{MessageEmoji.INFO} 当前未启用签到领额度。")
            return

        reply = ""
        with self._usage_lock:
            stats = self._current_usage_stats()
            users = stats.setdefault("users", {})
            user_id = status.get("user_id") or self._get_event_user_id(event)
            record = users.setdefault(user_id, {"user_id": user_id, "count": 0, "last_at": 0, "bonus": 0, "checkin_at": 0})
            used = self._to_nonnegative_int(record.get("count", 0))
            bonus = self._to_nonnegative_int(record.get("bonus", 0))
            checkin_at = self._to_nonnegative_int(record.get("checkin_at", 0))
            base_limit = self._daily_image_limit()
            if checkin_at > 0:
                reply = (
                    f"{MessageEmoji.INFO} 今日已经签到过啦：额外额度 +{bonus} 张，"
                    f"当前已使用 {used}/{base_limit + bonus} 张。"
                )
            else:
                bonus_min = self._to_nonnegative_int(getattr(self.plugin_config, "checkin_bonus_min", 1), 1)
                bonus_max = self._to_nonnegative_int(getattr(self.plugin_config, "checkin_bonus_max", 3), 3)
                if bonus_max < bonus_min:
                    bonus_max = bonus_min
                gained = random.randint(bonus_min, bonus_max) if bonus_max > bonus_min else bonus_min
                record["user_id"] = user_id
                record["count"] = used
                record["bonus"] = bonus + gained
                record["checkin_at"] = int(time.time())
                record["access_level"] = "limited"
                group_id = status.get("group_id") or self._get_event_group_id(event)
                if group_id:
                    record["group_id"] = group_id
                display_name = self._get_event_user_label(event).strip()
                if display_name and display_name != user_id:
                    record["display_name"] = display_name
                stats["total"] = sum(self._to_nonnegative_int(item.get("count", 0)) for item in users.values())
                self._persist_usage_stats()
                reply = (
                    f"{MessageEmoji.SUCCESS} 签到成功，今日额外生图额度 +{gained} 张。"
                    f"当前额度 {used}/{base_limit + bonus + gained} 张。"
                )
        yield event.plain_result(reply)

    @filter.command("人设")
    @handle_errors
    async def cmd_persona_list(self, event: AstrMessageEvent) -> AsyncGenerator[Any, None]:
        permission_error = self._permission_denied_message(event)
        if permission_error:
            yield event.plain_result(permission_error)
            return

        msg = "🎭 可用人设:\n"
        for index, persona in enumerate(self.plugin_config.personas, start=1):
            marker = "👉" if persona.id == self.plugin_config.active_persona_id else "  "
            msg += f"{marker} [{index}] {persona.name} ({persona.id}) · 参考图 {len(persona.ref_images)} 张\n"
        msg += "\n使用 /切换人设 [序号/ID/名称] 切换自拍人格与对应参考图组。"
        yield event.plain_result(msg)

    @filter.command("切换人设")
    @handle_errors
    async def cmd_switch_persona(
        self,
        event: AstrMessageEvent,
        p1: str = "",
        p2: str = "",
        p3: str = "",
        p4: str = "",
        p5: str = "",
    ) -> AsyncGenerator[Any, None]:
        permission_error = self._permission_denied_message(event)
        if permission_error:
            yield event.plain_result(permission_error)
            return

        fallback = " ".join(str(item) for item in [p1, p2, p3, p4, p5] if item).strip()
        selector = self._extract_command_message(event, "切换人设", fallback)
        if not selector:
            yield event.plain_result(f"{MessageEmoji.WARNING} 缺少人设。用法: /切换人设 [序号/ID/名称]\n可先发送 /人设 查看列表。")
            return

        persona = self._find_persona_profile(selector)
        if not persona:
            yield event.plain_result(f"{MessageEmoji.WARNING} 找不到人设: {selector}\n可先发送 /人设 查看列表。")
            return

        self._set_active_persona(persona.id)
        self._persist_config()
        self._safe_update_context_config()
        yield event.plain_result(
            f"{MessageEmoji.SUCCESS} 已切换至人设「{self.plugin_config.persona_name}」，"
            f"自拍将使用该人设的 {len(self.plugin_config.persona_ref_images)} 张参考图。"
        )

    @filter.command("切换链路")
    @handle_errors
    async def cmd_switch_chain(
        self,
        event: AstrMessageEvent,
        target: str = "",
        node_id: str = "",
    ) -> AsyncGenerator[Any, None]:
        permission_error = self._permission_denied_message(event)
        if permission_error:
            yield event.plain_result(permission_error)
            return

        target_map = {"画图": "text2img", "自拍": "selfie", "视频": "video", "副脑": "optimizer"}
        if target not in target_map:
            yield event.plain_result(f"{MessageEmoji.WARNING} 未知目标！支持: 画图/自拍/视频/副脑")
            return
        if not node_id:
            yield event.plain_result(f"{MessageEmoji.WARNING} 缺少节点 ID。用法: /切换链路 [目标] [节点ID]")
            return

        chain_key = target_map[target]
        provider = self.plugin_config.get_video_provider(node_id) if chain_key == "video" else self.plugin_config.get_provider(node_id)
        if not provider:
            yield event.plain_result(f"{MessageEmoji.WARNING} 找不到节点 ID: {node_id}")
            return

        self._set_chain_config(chain_key, node_id)
        self._persist_config()
        self._safe_update_context_config()
        yield event.plain_result(f"{MessageEmoji.SUCCESS} 已将 {target} 链路切换至节点: {node_id}")

    @filter.command("切换模型")
    @handle_errors
    async def cmd_switch_model(
        self,
        event: AstrMessageEvent,
        target: str = "",
        model_idx: str = "",
    ) -> AsyncGenerator[Any, None]:
        permission_error = self._permission_denied_message(event)
        if permission_error:
            yield event.plain_result(permission_error)
            return

        target_map = {"画图": "text2img", "自拍": "selfie", "视频": "video"}
        if target and target not in target_map and not model_idx:
            model_idx = target
            target = "画图"
        if not target:
            target = "画图"
        if target not in target_map:
            yield event.plain_result(f"{MessageEmoji.WARNING} 未知目标！支持: 画图/自拍/视频")
            return

        chain_key = target_map[target]
        provider = self._get_active_provider(chain_key)
        if not provider:
            yield event.plain_result(f"{MessageEmoji.WARNING} 当前 {target} 链路没有可用节点。")
            return

        models = provider.available_models
        if not models:
            yield event.plain_result(f"{MessageEmoji.WARNING} 当前节点 ({provider.id}) 未配置可选模型。")
            return

        if not model_idx:
            msg = f"🎛️ 节点 {provider.id} 的可用模型:\n"
            for index, model_name in enumerate(models):
                marker = "👉" if model_name == provider.model else "  "
                msg += f"{marker} [{index}] {model_name}\n"
            msg += f"\n回复 /切换模型 {target} [序号或名称] 进行选择"
            yield event.plain_result(msg)
            return

        selected_model = ""
        try:
            index = int(model_idx)
            if 0 <= index < len(models):
                selected_model = models[index]
        except ValueError:
            selected_model = next((model_name for model_name in models if model_name == model_idx), "")

        if not selected_model:
            yield event.plain_result(f"{MessageEmoji.WARNING} 模型序号或名称无效。")
            return

        provider.model = selected_model
        self._set_provider_model(chain_key, provider.id, selected_model)
        self._persist_config()
        self._safe_update_context_config()
        yield event.plain_result(f"{MessageEmoji.SUCCESS} 已将 {target} 节点 ({provider.id}) 默认模型切换为: {selected_model}")

    @filter.event_message_type(EventMessageType.ALL)
    async def on_message_preset(self, event: AstrMessageEvent) -> AsyncGenerator[Any, None]:
        text = self._get_event_text(event)

        compact_view_selector = self._extract_compact_command_payload(text, "查看预设")
        if compact_view_selector:
            yield event.plain_result(self._build_preset_view_message(compact_view_selector))
            return

        if not self.plugin_config.presets:
            return
        match = re.match(r"^\s*[/!！.]([^\s]+)", text)
        if not match:
            return
        cmd_name = match.group(1).strip()
        if cmd_name not in self.plugin_config.presets:
            return
        permission_error = self._permission_denied_message(event)
        if permission_error:
            yield event.plain_result(permission_error)
            return
        quota_error = self._image_quota_error_message(event, 1)
        if quota_error:
            yield event.plain_result(quota_error)
            return

        try:
            started_at = time.perf_counter()
            async with aiohttp.ClientSession() as session:
                raw_refs = self._get_event_images(event, include_at_avatars=True, at_after_command=cmd_name)
                preset_prompt = self.plugin_config.presets[cmd_name]
                safe_refs = await self._process_and_save_images(raw_refs, session=session)

                msg = self._format_pending_message(
                    self.plugin_config.draw_pending_message,
                    DEFAULT_DRAW_PENDING_MESSAGE,
                    command=cmd_name,
                    prompt=preset_prompt,
                    ref_count=len(safe_refs),
                    param_count=0,
                    persona_name=self.plugin_config.persona_name,
                )
                if self.plugin_config.verbose_report:
                    msg += f"\n📝 宏对应提示词: {preset_prompt}\n🖼️ 实际参考图：{len(safe_refs)} 张"
                yield event.plain_result(msg)

                chain_manager = ChainManager(self.plugin_config, session)
                result = await chain_manager.run_chain_with_metadata("text2img", preset_prompt, user_refs=safe_refs)
            self._record_generated_images(event, 1)
            yield event.chain_result(self._build_image_success_components(result, time.perf_counter() - started_at))
        except Exception as exc:
            yield event.plain_result(
                self._build_command_error_message("on_message_preset", exc) or f"💥 绘制失败: {exc}"
            )

    @filter.command("画")
    @handle_errors
    async def cmd_draw(
        self,
        event: AstrMessageEvent,
        p1: str = "",
        p2: str = "",
        p3: str = "",
        p4: str = "",
        p5: str = "",
        p6: str = "",
        p7: str = "",
        p8: str = "",
        p9: str = "",
        p10: str = "",
    ) -> AsyncGenerator[Any, None]:
        permission_error = self._permission_denied_message(event)
        if permission_error:
            yield event.plain_result(permission_error)
            return
        quota_error = self._image_quota_error_message(event, 1)
        if quota_error:
            yield event.plain_result(quota_error)
            return

        fallback = " ".join(str(item) for item in [p1, p2, p3, p4, p5, p6, p7, p8, p9, p10] if item).strip()
        message = self._extract_command_message(event, "画", fallback)
        raw_refs = self._get_event_images(event, include_at_avatars=True, at_after_command="画")
        if not message and not raw_refs:
            yield event.plain_result(f"{MessageEmoji.WARNING} 请输入提示词或附带参考图。")
            return

        started_at = time.perf_counter()
        async with aiohttp.ClientSession() as session:
            safe_refs = await self._process_and_save_images(raw_refs, session=session)
            prompt, kwargs = self.cmd_parser.parse(message)
            if not prompt and safe_refs:
                prompt = "根据参考图生成一张自然、清晰、符合原图语义的图片。"
            param_count = len(kwargs)
            if safe_refs:
                kwargs["user_refs"] = safe_refs

            msg = self._format_pending_message(
                self.plugin_config.draw_pending_message,
                DEFAULT_DRAW_PENDING_MESSAGE,
                command="画",
                prompt=prompt,
                ref_count=len(safe_refs),
                param_count=param_count,
                persona_name=self.plugin_config.persona_name,
            )
            if self.plugin_config.verbose_report:
                msg += f"\n📝 最终提示词: {prompt}\n⚙️ 附加参数：{param_count} 个\n🖼️ 实际参考图：{len(safe_refs)} 张"
            yield event.plain_result(msg)

            chain_manager = ChainManager(self.plugin_config, session)
            result = await chain_manager.run_chain_with_metadata("text2img", prompt, **kwargs)
        self._record_generated_images(event, 1)
        yield event.chain_result(self._build_image_success_components(result, time.perf_counter() - started_at))

    @filter.command("自拍")
    @handle_errors
    async def cmd_selfie(
        self,
        event: AstrMessageEvent,
        p1: str = "",
        p2: str = "",
        p3: str = "",
        p4: str = "",
        p5: str = "",
        p6: str = "",
        p7: str = "",
        p8: str = "",
        p9: str = "",
        p10: str = "",
    ) -> AsyncGenerator[Any, None]:
        permission_error = self._permission_denied_message(event)
        if permission_error:
            yield event.plain_result(permission_error)
            return
        quota_error = self._image_quota_error_message(event, 1)
        if quota_error:
            yield event.plain_result(quota_error)
            return

        fallback = " ".join(str(item) for item in [p1, p2, p3, p4, p5, p6, p7, p8, p9, p10] if item).strip()
        message = self._extract_command_message(event, "自拍", fallback)
        user_input, kwargs = self.cmd_parser.parse(message)
        user_input = user_input or "看着镜头微笑"

        started_at = time.perf_counter()
        async with aiohttp.ClientSession() as session:
            optimized_actions = await self.prompt_optimizer.optimize(user_input, count=1, session=session)
            final_prompt, extra_kwargs = self.persona_manager.build_persona_prompt(optimized_actions[0] if optimized_actions else user_input)
            extra_kwargs.update(kwargs)

            raw_refs = self._get_event_images(event)
            target_refs = raw_refs if raw_refs else self.plugin_config.persona_ref_images
            safe_refs = await self._process_and_save_images(target_refs, session=session)
            if safe_refs:
                extra_kwargs["user_refs"] = safe_refs
                if not raw_refs:
                    extra_kwargs.pop("persona_ref", None)

            msg = self._format_pending_message(
                self.plugin_config.selfie_pending_message,
                DEFAULT_SELFIE_PENDING_MESSAGE,
                command="自拍",
                prompt=final_prompt,
                user_input=user_input,
                ref_count=len(safe_refs),
                param_count=len(kwargs),
                persona_name=self.plugin_config.persona_name,
            )
            if self.plugin_config.verbose_report:
                msg += f"\n📝 构建提示词: {final_prompt}\n⚙️ 附加参数：{len(kwargs)} 个\n🖼️ 实际参考图：{len(safe_refs)} 张"
            yield event.plain_result(msg)

            chain_to_use = "selfie" if self.plugin_config.chains.get("selfie") else "text2img"
            chain_manager = ChainManager(self.plugin_config, session)
            result = await chain_manager.run_chain_with_metadata(chain_to_use, final_prompt, **extra_kwargs)
        self._record_generated_images(event, 1)
        yield event.chain_result(self._build_image_success_components(result, time.perf_counter() - started_at))

    @filter.command("视频")
    @handle_errors
    async def cmd_video(
        self,
        event: AstrMessageEvent,
        p1: str = "",
        p2: str = "",
        p3: str = "",
        p4: str = "",
        p5: str = "",
        p6: str = "",
        p7: str = "",
        p8: str = "",
        p9: str = "",
        p10: str = "",
    ) -> AsyncGenerator[Any, None]:
        permission_error = self._permission_denied_message(event)
        if permission_error:
            yield event.plain_result(permission_error)
            return

        fallback = " ".join(str(item) for item in [p1, p2, p3, p4, p5, p6, p7, p8, p9, p10] if item).strip()
        message = self._extract_command_message(event, "视频", fallback)
        raw_refs = self._get_event_images(event)
        if not message and not raw_refs:
            yield event.plain_result(f"{MessageEmoji.WARNING} 请输入视频提示词或附带参考图。")
            return

        safe_refs = []
        if raw_refs:
            needs_session = any(str(ref).startswith("http") for ref in raw_refs)
            if needs_session:
                async with aiohttp.ClientSession() as session:
                    safe_refs = await self._process_and_save_images(raw_refs, session=session)
            else:
                safe_refs = await self._process_and_save_images(raw_refs)
        prompt, kwargs = self.cmd_parser.parse(message)
        if not prompt and safe_refs:
            prompt = "根据参考图生成一段自然、流畅、清晰的视频。"

        msg = f"{MessageEmoji.INFO} 视频任务已提交后台渲染..."
        if self.plugin_config.verbose_report:
            msg += f"\n📝 渲染提示词: {prompt}\n⚙️ 附加参数：{len(kwargs)} 个\n🖼️ 参考图/首尾帧：{len(safe_refs)} 张"
        yield event.plain_result(msg)

        self._create_background_task(self.video_manager.background_task_runner(event, prompt, safe_refs, kwargs))

    @llm_tool(name="generate_selfie")
    async def tool_generate_selfie(
        self,
        event: AstrMessageEvent,
        action: str,
        count: int = 1,
        aspect_ratio: str = "",
        size: str = "",
        extra_params: str = "",
        return_result: bool = False,
        refs: str = "",
    ) -> str:
        """
        以此 AI 助理的固定人设拍摄自拍。
        Args:
            action (string): 动作、姿态、服装、场景或画面描述。
            count (int): 需要生成的图片数量。默认为 1。
            aspect_ratio (string): 宽高比例，例如 1:1、3:4、9:16、16:9。
            size (string): 分辨率或尺寸参数，例如 1024x1024。
            extra_params (string): 附加模型参数透传，格式为 --key value，可同时传多个。
            return_result (bool): 仅供其他插件显式调用时使用。为 true 时不自动下发图片，而是返回 JSON 图片结果。
            refs (string): 仅在 return_result 为 true 时使用。自拍参考图 URL、本地路径或 data URL；多个参考图可用换行分隔，也可传 JSON 数组字符串。
        """
        permission_error = self._permission_denied_message(event)
        if permission_error:
            return permission_error

        try:
            if self._plugin_bool(return_result, default=False):
                result = await self.generate_images_for_plugin(
                    prompt=action,
                    count=count,
                    aspect_ratio=aspect_ratio,
                    size=size,
                    extra_params=extra_params,
                    refs=refs or self._get_event_images(event),
                    mode="selfie",
                    event=event,
                    record_usage=True,
                )
                return json.dumps(result, ensure_ascii=False)
            count = self._normalize_count(count)
            quota_error = self._image_quota_error_message(event, count)
            if quota_error:
                return quota_error
            generation = await self._run_selfie_generation(
                event,
                action,
                count,
                aspect_ratio=aspect_ratio,
                size=size,
                extra_params=extra_params,
            )
            valid_results = [result for result in generation["results"] if self._get_image_result_url(result)]
            if not valid_results:
                raise RuntimeError("所有绘图节点请求失败")
            sent = await self._send_generated_images(event, valid_results)
            self._record_generated_images(event, sent)
            return f"系统提示：已成功生成并下发了 {sent} 张图。"
        except Exception as exc:
            logger.error(f"[OmniDraw] LLM 自拍工具失败: {exc}", exc_info=True)
            if self._plugin_bool(return_result, default=False):
                return json.dumps({
                    "success": False,
                    "message": f"画图失败 ({self._safe_plugin_error_message(exc)})。",
                    "images": [],
                    "mode": "selfie",
                }, ensure_ascii=False)
            return f"系统提示：画图失败 ({exc})。"

    @llm_tool(name="generate_image")
    async def tool_generate_image(
        self,
        event: AstrMessageEvent,
        prompt: str,
        count: int = 1,
        aspect_ratio: str = "",
        size: str = "",
        extra_params: str = "",
        return_result: bool = False,
        refs: str = "",
    ) -> str:
        """
        AI 画图工具。当用户提出明确的画面要求你画出来时调用此工具。
        Args:
            prompt (string): 图片提示词，描述主体、风格、场景、构图和细节。
            count (int): 图片数量。默认为 1。
            aspect_ratio (string): 宽高比例，例如 1:1、3:4、9:16、16:9。
            size (string): 分辨率或尺寸参数，例如 1024x1024。
            extra_params (string): 其他模型参数透传，格式为 --key value，可同时传多个。
            return_result (bool): 仅供其他插件显式调用时使用。为 true 时不自动下发图片，而是返回 JSON 图片结果。
            refs (string): 仅在 return_result 为 true 时使用。参考图 URL、本地路径或 data URL；多个参考图可用换行分隔，也可传 JSON 数组字符串。
        """
        permission_error = self._permission_denied_message(event)
        if permission_error:
            return permission_error

        try:
            if self._plugin_bool(return_result, default=False):
                result = await self.generate_images_for_plugin(
                    prompt=prompt,
                    count=count,
                    aspect_ratio=aspect_ratio,
                    size=size,
                    extra_params=extra_params,
                    refs=refs or self._get_event_images(event),
                    event=event,
                    record_usage=True,
                )
                return json.dumps(result, ensure_ascii=False)
            count = self._normalize_count(count)
            quota_error = self._image_quota_error_message(event, count)
            if quota_error:
                return quota_error
            generation = await self._run_text2img_generation(
                event,
                prompt,
                count,
                aspect_ratio=aspect_ratio,
                size=size,
                extra_params=extra_params,
            )
            valid_results = [result for result in generation["results"] if self._get_image_result_url(result)]
            if not valid_results:
                raise RuntimeError("所有绘图节点请求失败")
            sent = await self._send_generated_images(event, valid_results)
            self._record_generated_images(event, sent)
            return f"系统提示：已成功下发 {sent} 张图。"
        except Exception as exc:
            logger.error(f"[OmniDraw] LLM 画图工具失败: {exc}", exc_info=True)
            if self._plugin_bool(return_result, default=False):
                return json.dumps({
                    "success": False,
                    "message": f"画图失败 ({self._safe_plugin_error_message(exc)})。",
                    "images": [],
                    "mode": "text2img",
                }, ensure_ascii=False)
            return f"系统提示：画图失败 ({exc})。"

    @llm_tool(name="generate_video")
    async def tool_generate_video(
        self,
        event: AstrMessageEvent,
        prompt: str,
        count: int = 1,
        aspect_ratio: str = "",
        size: str = "",
        extra_params: str = "",
    ) -> str:
        """
        AI 视频生成工具。当用户要求生成一段视频时调用。
        Args:
            prompt (string): 视频提示词，描述画面、动作、镜头运动、时长感和风格。
            count (int): 视频数量。默认为 1。
            aspect_ratio (string): 宽高比例，例如 9:16、16:9、1:1。
            size (string): 分辨率或尺寸参数，例如 1280x720、1920x1080。
            extra_params (string): 附加参数，透传至底层视频引擎，格式为 --key value。
        """
        permission_error = self._permission_denied_message(event)
        if permission_error:
            return permission_error

        try:
            count = self._normalize_count(count)
            raw_refs = self._get_event_images(event)
            safe_refs = []
            if raw_refs:
                needs_session = any(str(ref).startswith("http") for ref in raw_refs)
                if needs_session:
                    async with aiohttp.ClientSession() as session:
                        safe_refs = await self._process_and_save_images(raw_refs, session=session)
                else:
                    safe_refs = await self._process_and_save_images(raw_refs)
            kwargs = self._parse_extra_params(extra_params)
            if aspect_ratio:
                kwargs["aspect_ratio"] = aspect_ratio
            if size:
                kwargs["size"] = size

            for _ in range(count):
                self._create_background_task(
                    self.video_manager.background_task_runner(
                        event,
                        prompt,
                        safe_refs,
                        kwargs,
                        include_metadata=False,
                    )
                )
            return f"系统提示：已在后台独立提交了 {count} 个视频渲染任务。请告诉用户正在渲染中。"
        except Exception as exc:
            logger.error(f"[OmniDraw] LLM 视频工具失败: {exc}", exc_info=True)
            return f"系统提示：失败 ({exc})。"
