"""
AstrBot 万象画卷插件 - 数据模型与配置归一化。
"""
import binascii
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from .constants import (
    APIType,
    DEFAULT_GEMINI_MODEL,
    DEFAULT_DRAW_ERROR_MESSAGE,
    DEFAULT_DRAW_PENDING_MESSAGE,
    DEFAULT_SELFIE_ERROR_MESSAGE,
    DEFAULT_SELFIE_PENDING_MESSAGE,
)
from .utils import save_image_bytes, split_data_url

PLUGIN_NAME = "astrbot_plugin_omnidraw"
PLUGIN_AUTHOR = "雪碧bir"
PLUGIN_VERSION = "3.3.19"
DEFAULT_CACHE_CLEANUP_INTERVAL_HOURS = 24
DEFAULT_MAX_CACHE_SIZE_MB = 512


@dataclass
class ProviderConfig:
    id: str
    api_type: str
    base_url: str
    api_keys: List[str]
    model: str
    timeout: float
    available_models: List[str] = field(default_factory=list)

    @property
    def has_api_key(self) -> bool:
        return any(key.strip() for key in self.api_keys)


@dataclass
class PersonaProfile:
    id: str
    name: str
    base_prompt: str
    ref_images: List[str] = field(default_factory=list)

    def to_config_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "persona_name": self.name,
            "persona_base_prompt": self.base_prompt,
            "persona_ref_image": list(self.ref_images),
        }


@dataclass
class PluginConfig:
    providers: List[ProviderConfig]
    video_providers: List[ProviderConfig]
    chains: Dict[str, List[str]]
    presets: Dict[str, str]
    enable_optimizer: bool
    optimizer_model: str
    optimizer_timeout: float
    max_batch_count: int
    persona_name: str
    persona_base_prompt: str
    persona_ref_image: str
    persona_ref_images: List[str]
    active_persona_id: str
    personas: List[PersonaProfile]
    usable_users: List[str]
    allowed_users: List[str]
    unlimited_users: List[str]
    blocked_users: List[str]
    unlimited_groups: List[str]
    enable_daily_limit: bool
    daily_image_limit: int
    enable_checkin: bool
    checkin_bonus_min: int
    checkin_bonus_max: int
    enable_scheduled_cleanup: bool
    scheduled_cleanup_interval_hours: int
    enable_size_limit_cleanup: bool
    max_cache_size_mb: int
    optimizer_style: str
    optimizer_custom_prompt: str
    draw_pending_message: str
    selfie_pending_message: str
    draw_error_message: str
    selfie_error_message: str
    verbose_report: bool
    show_generation_time: bool
    show_request_model: bool

    @classmethod
    def from_dict(cls, config_dict: Dict[str, Any], data_dir: str) -> "PluginConfig":
        if not isinstance(config_dict, dict):
            config_dict = {}

        providers = [_build_provider_config(p, is_video=False) for p in _as_list(config_dict.get("providers", []))]
        providers = [provider for provider in providers if provider.id]

        video_providers = [
            _build_provider_config(p, is_video=True) for p in _as_list(config_dict.get("video_providers", []))
        ]
        video_providers = [provider for provider in video_providers if provider.id]

        presets_dict = {}
        normalized_presets = []
        for preset in _as_list(config_dict.get("presets", [])):
            if isinstance(preset, dict):
                name = str(preset.get("name", "")).strip()
                prompt = str(preset.get("prompt", "")).strip()
            elif isinstance(preset, str) and ":" in preset:
                name, prompt = preset.split(":", 1)
                name = name.strip()
                prompt = prompt.strip()
            else:
                continue
            if name:
                presets_dict[name] = prompt
                normalized_presets.append(f"{name}:{prompt}")
        config_dict["presets"] = normalized_presets

        persona_conf = _ensure_dict(config_dict, "persona_config")
        opt_conf = _ensure_dict(config_dict, "optimizer_config")
        router_conf = _ensure_dict(config_dict, "router_config")
        perm_conf = _ensure_dict(config_dict, "permission_config")
        usage_conf = _ensure_dict(config_dict, "usage_config")
        cache_conf = _ensure_dict(config_dict, "cache_config")
        reply_conf = _ensure_dict(config_dict, "reply_config")

        for legacy_key in ("persona_name", "persona_base_prompt", "persona_ref_image", "persona_ref_images"):
            if legacy_key in config_dict and legacy_key not in persona_conf:
                persona_conf[legacy_key] = config_dict[legacy_key]

        personas, active_persona = _normalize_persona_profiles(persona_conf, data_dir)
        persona_conf["profiles"] = [profile.to_config_dict() for profile in personas]
        persona_conf["active_persona_id"] = active_persona.id
        persona_conf["persona_name"] = active_persona.name
        persona_conf["persona_base_prompt"] = active_persona.base_prompt
        persona_conf["persona_ref_image"] = list(active_persona.ref_images)

        chains = {
            "text2img": _parse_chain(router_conf.get("chain_text2img", "node_1")),
            "selfie": _parse_chain(router_conf.get("chain_selfie", "node_1")),
            "video": _parse_chain(router_conf.get("chain_video", "video_node_1")),
            "optimizer": _parse_chain(opt_conf.get("chain_optimizer", "node_1")),
        }

        optimizer_model = str(opt_conf.get("optimizer_model", "")).strip()
        if not optimizer_model and providers:
            optimizer_model = providers[0].model
        usable_users = _merge_unique_values(
            perm_conf.get("usable_users", ""),
            perm_conf.get("access_users", ""),
            perm_conf.get("use_whitelist", ""),
        )
        user_whitelist = _merge_unique_values(
            perm_conf.get("allowed_users", ""),
            perm_conf.get("unlimited_users", ""),
            perm_conf.get("user_whitelist", ""),
        )
        blocked_users = _merge_unique_values(
            perm_conf.get("blocked_users", ""),
            perm_conf.get("user_blacklist", ""),
        )
        unlimited_groups = _merge_unique_values(
            perm_conf.get("unlimited_groups", ""),
            perm_conf.get("group_whitelist", ""),
        )
        perm_conf["usable_users"] = "\n".join(usable_users)
        perm_conf["allowed_users"] = "\n".join(user_whitelist)
        perm_conf["blocked_users"] = "\n".join(blocked_users)
        perm_conf["unlimited_groups"] = "\n".join(unlimited_groups)

        enable_daily_limit = _to_bool(usage_conf.get("enable_daily_limit", False))
        daily_image_limit = _to_int(usage_conf.get("daily_image_limit", 20), 20, minimum=0)
        enable_checkin = _to_bool(usage_conf.get("enable_checkin", False))
        checkin_bonus_min = _to_int(usage_conf.get("checkin_bonus_min", 1), 1, minimum=0)
        checkin_bonus_max = _to_int(usage_conf.get("checkin_bonus_max", 3), 3, minimum=0)
        if checkin_bonus_max < checkin_bonus_min:
            checkin_bonus_max = checkin_bonus_min
        usage_conf["enable_daily_limit"] = enable_daily_limit
        usage_conf["daily_image_limit"] = daily_image_limit
        usage_conf["enable_checkin"] = enable_checkin
        usage_conf["checkin_bonus_min"] = checkin_bonus_min
        usage_conf["checkin_bonus_max"] = checkin_bonus_max

        enable_scheduled_cleanup = _to_bool(cache_conf.get("enable_scheduled_cleanup", False) or False)
        scheduled_cleanup_interval_hours = _to_int(
            cache_conf.get("scheduled_cleanup_interval_hours", DEFAULT_CACHE_CLEANUP_INTERVAL_HOURS),
            DEFAULT_CACHE_CLEANUP_INTERVAL_HOURS,
            minimum=1,
        )
        enable_size_limit_cleanup = _to_bool(cache_conf.get("enable_size_limit_cleanup", False) or False)
        max_cache_size_mb = _to_int(
            cache_conf.get("max_cache_size_mb", DEFAULT_MAX_CACHE_SIZE_MB),
            DEFAULT_MAX_CACHE_SIZE_MB,
            minimum=1,
        )
        cache_conf["enable_scheduled_cleanup"] = enable_scheduled_cleanup
        cache_conf["scheduled_cleanup_interval_hours"] = scheduled_cleanup_interval_hours
        cache_conf["enable_size_limit_cleanup"] = enable_size_limit_cleanup
        cache_conf["max_cache_size_mb"] = max_cache_size_mb

        draw_pending_message = _normalize_reply_text(
            reply_conf.get("draw_pending_message"),
            DEFAULT_DRAW_PENDING_MESSAGE,
        )
        selfie_pending_message = _normalize_reply_text(
            reply_conf.get("selfie_pending_message"),
            DEFAULT_SELFIE_PENDING_MESSAGE,
        )
        draw_error_message = _normalize_reply_text(
            reply_conf.get("draw_error_message"),
            DEFAULT_DRAW_ERROR_MESSAGE,
        )
        selfie_error_message = _normalize_reply_text(
            reply_conf.get("selfie_error_message"),
            DEFAULT_SELFIE_ERROR_MESSAGE,
        )
        reply_conf["draw_pending_message"] = draw_pending_message
        reply_conf["selfie_pending_message"] = selfie_pending_message
        reply_conf["draw_error_message"] = draw_error_message
        reply_conf["selfie_error_message"] = selfie_error_message

        return cls(
            providers=providers,
            video_providers=video_providers,
            chains=chains,
            presets=presets_dict,
            enable_optimizer=_to_bool(opt_conf.get("enable_optimizer", True)),
            optimizer_model=optimizer_model or "gpt-4o-mini",
            optimizer_timeout=_to_float(opt_conf.get("optimizer_timeout", 15.0), 15.0, minimum=1.0),
            max_batch_count=_to_int(opt_conf.get("max_batch_count", 0), 0, minimum=0),
            persona_name=active_persona.name,
            persona_base_prompt=active_persona.base_prompt,
            persona_ref_image=active_persona.ref_images[0] if active_persona.ref_images else "",
            persona_ref_images=list(active_persona.ref_images),
            active_persona_id=active_persona.id,
            personas=personas,
            usable_users=usable_users,
            allowed_users=user_whitelist,
            unlimited_users=list(user_whitelist),
            blocked_users=blocked_users,
            unlimited_groups=unlimited_groups,
            enable_daily_limit=enable_daily_limit,
            daily_image_limit=daily_image_limit,
            enable_checkin=enable_checkin,
            checkin_bonus_min=checkin_bonus_min,
            checkin_bonus_max=checkin_bonus_max,
            enable_scheduled_cleanup=enable_scheduled_cleanup,
            scheduled_cleanup_interval_hours=scheduled_cleanup_interval_hours,
            enable_size_limit_cleanup=enable_size_limit_cleanup,
            max_cache_size_mb=max_cache_size_mb,
            optimizer_style=str(opt_conf.get("optimizer_style", "手机日常原生感")).strip() or "手机日常原生感",
            optimizer_custom_prompt=str(opt_conf.get("optimizer_custom_prompt", "")),
            draw_pending_message=draw_pending_message,
            selfie_pending_message=selfie_pending_message,
            draw_error_message=draw_error_message,
            selfie_error_message=selfie_error_message,
            verbose_report=_to_bool(config_dict.get("verbose_report", False)),
            show_generation_time=_to_bool(config_dict.get("show_generation_time", False)),
            show_request_model=_to_bool(config_dict.get("show_request_model", False)),
        )

    def get_provider(self, provider_id: str) -> Optional[ProviderConfig]:
        for provider in self.providers:
            if provider.id == provider_id:
                return provider
        return None

    def get_video_provider(self, provider_id: str) -> Optional[ProviderConfig]:
        for provider in self.video_providers:
            if provider.id == provider_id:
                return provider
        return None

    def get_persona(self, persona_id: str) -> Optional[PersonaProfile]:
        for persona in self.personas:
            if persona.id == persona_id:
                return persona
        return None


def _ensure_dict(parent: Dict[str, Any], key: str) -> Dict[str, Any]:
    value = parent.get(key)
    if not isinstance(value, dict):
        value = {}
        parent[key] = value
    return value


def _as_list(value: Any) -> List[Any]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _split_csv_or_lines(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        items = value
    else:
        items = re.split(r"[\s,]+", str(value).replace("\r", "\n"))
    return [str(item).strip() for item in items if str(item).strip()]


def _parse_models(value: Any) -> List[str]:
    if isinstance(value, (list, tuple)):
        raw_items = value
    else:
        raw_items = str(value or "").split(",")
    seen = set()
    models = []
    for item in raw_items:
        model = str(item).strip()
        if model and model not in seen:
            seen.add(model)
            models.append(model)
    return models


def _normalize_api_type(value: Any, is_video: bool) -> str:
    raw = str(value or "").strip()
    if not raw:
        return "async_task" if is_video else "openai_image"
    lowered = raw.lower()
    if is_video:
        if "chat" in lowered or "对话" in raw:
            return "openai_chat"
        if "sync" in lowered or "同步" in raw:
            return "openai_sync"
        return "async_task"
    if lowered in {"gemini", "gemini_official", "google_gemini"} or "gemini" in lowered or "gemini" in raw.lower():
        return APIType.GEMINI_OFFICIAL
    if lowered in {"custom_endpoint", "custom"} or "自定义" in raw:
        return APIType.CUSTOM_ENDPOINT
    if "chat" in lowered or "对话" in raw:
        return APIType.OPENAI_CHAT
    return APIType.OPENAI_IMAGE


def _build_provider_config(raw_provider: Any, is_video: bool) -> ProviderConfig:
    if not isinstance(raw_provider, dict):
        raw_provider = {}

    model_raw = raw_provider.get("model", raw_provider.get("模型名称", ""))
    available_models = _parse_models(raw_provider.get("available_models", []))
    if not available_models:
        available_models = _parse_models(model_raw)

    model = str(model_raw or "").strip()
    if "," in model:
        model = model.split(",", 1)[0].strip()
    if not model and available_models:
        model = available_models[0]
    api_type = _normalize_api_type(raw_provider.get("api_type", raw_provider.get("接口模式", "")), is_video)
    if api_type == APIType.GEMINI_OFFICIAL and not model:
        model = DEFAULT_GEMINI_MODEL
    if model and model not in available_models:
        available_models.insert(0, model)

    default_timeout = 300.0 if is_video else 60.0
    return ProviderConfig(
        id=str(raw_provider.get("id", raw_provider.get("节点ID", ""))).strip(),
        api_type=api_type,
        base_url=str(
            raw_provider.get(
                "base_url",
                raw_provider.get("接口地址 (需含/v1或/v2)", raw_provider.get("接口地址 (需含/v1)", "")),
            )
        ).strip(),
        api_keys=_split_csv_or_lines(raw_provider.get("api_keys", raw_provider.get("API密钥", ""))),
        model=model,
        timeout=_to_float(raw_provider.get("timeout", raw_provider.get("超时时间(秒)", default_timeout)), default_timeout, 1.0),
        available_models=available_models,
    )


def _parse_chain(value: Any) -> List[str]:
    if isinstance(value, (list, tuple)):
        raw_items = [str(item).strip() for item in value if str(item).strip()]
    else:
        raw_items = [item for item in _split_csv_or_lines(value) if item]
    chain = []
    seen = set()
    for item in raw_items:
        if item in seen:
            continue
        seen.add(item)
        chain.append(item)
    return chain


def _parse_allowed_users(value: Any) -> List[str]:
    return _split_csv_or_lines(value)


def _merge_unique_values(*values: Any) -> List[str]:
    merged = []
    seen = set()
    for value in values:
        for item in _parse_allowed_users(value):
            if item in seen:
                continue
            seen.add(item)
            merged.append(item)
    return merged


def _normalize_reply_text(value: Any, default: str) -> str:
    text = str(value or "").strip()
    return text or default


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() not in {"false", "0", "no", "off", "关闭"}


def _to_float(value: Any, default: float, minimum: Optional[float] = None) -> float:
    try:
        result = float(str(value).strip())
    except Exception:
        result = default
    if minimum is not None:
        result = max(minimum, result)
    return result


def _to_int(value: Any, default: int, minimum: Optional[int] = None) -> int:
    try:
        result = int(float(str(value).strip()))
    except Exception:
        result = default
    if minimum is not None:
        result = max(minimum, result)
    return result


def _normalize_persona_profiles(persona_conf: Dict[str, Any], data_dir: str) -> Tuple[List[PersonaProfile], PersonaProfile]:
    refs_dir = os.path.join(data_dir, "persona_refs")
    raw_profiles = persona_conf.get("profiles")
    if not isinstance(raw_profiles, list) or not raw_profiles:
        raw_profiles = [
            {
                "id": persona_conf.get("active_persona_id") or persona_conf.get("persona_id") or "default",
                "persona_name": persona_conf.get("persona_name", "默认助理"),
                "persona_base_prompt": persona_conf.get("persona_base_prompt", ""),
                "persona_ref_image": persona_conf.get(
                    "persona_ref_image",
                    persona_conf.get("persona_ref_images", []),
                ),
            }
        ]

    used_ids: Set[str] = set()
    profiles: List[PersonaProfile] = []
    active_refs: List[str] = []

    for index, raw_profile in enumerate(raw_profiles):
        if not isinstance(raw_profile, dict):
            raw_profile = {}

        name = str(
            raw_profile.get(
                "persona_name",
                raw_profile.get("name", "默认助理" if index == 0 else f"人设 {index + 1}"),
            )
        ).strip() or ("默认助理" if index == 0 else f"人设 {index + 1}")
        profile_id = _normalize_persona_id(raw_profile.get("id", ""), name, index, used_ids)
        base_prompt = str(raw_profile.get("persona_base_prompt", raw_profile.get("base_prompt", "")))
        raw_images = raw_profile.get(
            "persona_ref_image",
            raw_profile.get("persona_ref_images", raw_profile.get("ref_images", [])),
        )
        processed_images = _process_persona_images(raw_images, refs_dir, cleanup=False)
        active_refs.extend(processed_images)
        profiles.append(
            PersonaProfile(
                id=profile_id,
                name=name,
                base_prompt=base_prompt,
                ref_images=processed_images,
            )
        )

    if not profiles:
        profiles.append(PersonaProfile(id="default", name="默认助理", base_prompt="", ref_images=[]))

    _cleanup_unused_persona_refs(refs_dir, active_refs)

    active_id = str(persona_conf.get("active_persona_id", "")).strip()
    active_persona = next(
        (profile for profile in profiles if profile.id == active_id or profile.id.lower() == active_id.lower()),
        profiles[0],
    )
    return profiles, active_persona


def _normalize_persona_id(raw_id: Any, name: str, index: int, used_ids: Set[str]) -> str:
    candidate = str(raw_id or "").strip()
    if not candidate:
        candidate = "default" if index == 0 else name
    candidate = re.sub(r"[^a-zA-Z0-9_-]+", "_", candidate).strip("_").lower()
    if not candidate:
        candidate = "default" if index == 0 else f"persona_{index + 1}"

    base_candidate = candidate
    suffix = 2
    while candidate in used_ids:
        candidate = f"{base_candidate}_{suffix}"
        suffix += 1
    used_ids.add(candidate)
    return candidate


def _process_persona_images(raw_images: Any, refs_dir: str, cleanup: bool = True) -> List[str]:
    os.makedirs(refs_dir, exist_ok=True)
    processed_images = []
    plugin_data_dir = os.path.abspath(os.path.dirname(refs_dir))

    for idx, img_data in enumerate(_as_list(raw_images)):
        if not img_data:
            continue
        img_ref = str(img_data)
        if _is_page_preview_ref(img_ref):
            continue
        if img_ref.startswith("data:image"):
            saved_path = _save_data_url_image(img_ref, refs_dir, idx)
            if saved_path:
                processed_images.append(saved_path)
        else:
            img_ref = _resolve_plugin_file_ref(img_ref, plugin_data_dir)
            processed_images.append(img_ref)

    if cleanup:
        _cleanup_unused_persona_refs(refs_dir, processed_images)
    return processed_images


def _resolve_plugin_file_ref(image_ref: str, plugin_data_dir: str) -> str:
    normalized = image_ref.replace("\\", "/").lstrip("/")
    if not normalized.startswith("files/"):
        return image_ref

    abs_path = os.path.abspath(os.path.join(plugin_data_dir, *normalized.split("/")))
    try:
        common = os.path.commonpath([plugin_data_dir, abs_path])
    except ValueError:
        return image_ref
    if common != plugin_data_dir:
        return image_ref
    return abs_path


def _is_page_preview_ref(image_ref: str) -> bool:
    return "astrbot_plugin_omnidraw/get_image" in str(image_ref)


def _save_data_url_image(data_url: str, refs_dir: str, idx: int) -> str:
    try:
        image_bytes, content_type = split_data_url(data_url)
        return save_image_bytes(image_bytes, refs_dir, data_url, "ref", idx, content_type)
    except (ValueError, binascii.Error, OSError):
        return ""


def _cleanup_unused_persona_refs(refs_dir: str, active_refs: List[str]) -> None:
    active_paths = {os.path.abspath(ref) for ref in active_refs if not str(ref).startswith("http")}
    try:
        filenames = os.listdir(refs_dir)
    except OSError:
        return

    for filename in filenames:
        if not filename.startswith("ref_"):
            continue
        filepath = os.path.abspath(os.path.join(refs_dir, filename))
        if filepath in active_paths or not os.path.isfile(filepath):
            continue
        try:
            os.remove(filepath)
        except OSError:
            continue
