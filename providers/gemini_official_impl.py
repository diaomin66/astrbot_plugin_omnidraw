"""Google Gemini native image provider."""

import asyncio
import base64
import json
import math
import re
from typing import Any, Dict, List
from urllib.parse import quote

import aiohttp
from astrbot.api import logger

from ..constants import DEFAULT_GEMINI_BASE_URL, DEFAULT_GEMINI_MODEL
from .base import (
    BaseProvider,
    extract_error_message,
    extract_image_url_from_response,
    guess_image_content_type,
    normalize_base_url,
    summarize_payload_json_for_log,
    summarize_response_text_for_log,
    summarize_url_for_log,
)


MAX_REFERENCE_IMAGES = 14
ALLOWED_ASPECT_RATIOS = (
    "1:1",
    "3:4",
    "4:3",
    "9:16",
    "16:9",
    "2:3",
    "3:2",
    "4:5",
    "5:4",
    "21:9",
    "1:4",
    "4:1",
    "1:8",
    "8:1",
)


class GeminiOfficialProvider(BaseProvider):
    """Call Google's native Gemini generateContent endpoint."""

    async def _get_image_bytes(self, image_path_or_url: str) -> bytes:
        return await self.fetch_reference_bytes(image_path_or_url)

    async def _inline_image_part(self, image_path_or_url: str) -> Dict[str, Any]:
        image_bytes = await self._get_image_bytes(image_path_or_url)
        encoded = await asyncio.to_thread(lambda: base64.b64encode(image_bytes).decode("ascii"))
        return {
            "inlineData": {
                "mimeType": guess_image_content_type(image_path_or_url),
                "data": encoded,
            }
        }

    def _request_model(self, api_kwargs: Dict[str, Any]) -> str:
        model = str(api_kwargs.pop("model", "") or self.config.model or DEFAULT_GEMINI_MODEL).strip()
        if model.startswith("models/"):
            return model.split("/", 1)[1]
        return model

    def _endpoint(self, model: str) -> str:
        base_url = normalize_base_url(self.config.base_url) or DEFAULT_GEMINI_BASE_URL
        if ":generateContent" in base_url:
            return base_url
        if "/models/" in base_url:
            return f"{base_url}:generateContent"
        if base_url.endswith("/models"):
            base_url = base_url[: -len("/models")]
        return f"{base_url}/models/{quote(model, safe='-._~')}:generateContent"

    def _pop_any(self, params: Dict[str, Any], *names: str) -> Any:
        for name in names:
            if name in params:
                return params.pop(name)
        return None

    def _normalize_modalities(self, value: Any) -> List[str]:
        if isinstance(value, (list, tuple)):
            raw_items = value
        else:
            raw_items = re.split(r"[\s,]+", str(value or ""))
        items = []
        for item in raw_items:
            text = str(item or "").strip().upper()
            if text:
                items.append("IMAGE" if text == "IMG" else text)
        return items or ["TEXT", "IMAGE"]

    def _aspect_ratio_from_size(self, value: Any) -> str:
        match = re.fullmatch(r"\s*(\d+)\s*[xX×]\s*(\d+)\s*", str(value or ""))
        if not match:
            return ""
        width, height = int(match.group(1)), int(match.group(2))
        if width <= 0 or height <= 0:
            return ""
        ratio = width / height
        best = min(
            ALLOWED_ASPECT_RATIOS,
            key=lambda item: abs(math.log(ratio / (int(item.split(":")[0]) / int(item.split(":")[1])))),
        )
        return best

    def _build_generation_config(self, params: Dict[str, Any]) -> Dict[str, Any]:
        modalities = self._pop_any(params, "responseModalities", "response_modalities")
        generation_config: Dict[str, Any] = {
            "responseModalities": self._normalize_modalities(modalities or ["TEXT", "IMAGE"])
        }

        key_map = {
            "temperature": "temperature",
            "topP": "topP",
            "top_p": "topP",
            "topK": "topK",
            "top_k": "topK",
            "candidateCount": "candidateCount",
            "candidate_count": "candidateCount",
            "maxOutputTokens": "maxOutputTokens",
            "max_output_tokens": "maxOutputTokens",
            "seed": "seed",
        }
        for source_key, target_key in key_map.items():
            if source_key in params:
                generation_config[target_key] = params.pop(source_key)

        aspect_ratio = self._pop_any(params, "aspectRatio", "aspect_ratio")
        if not aspect_ratio:
            aspect_ratio = self._aspect_ratio_from_size(self._pop_any(params, "size"))
        image_size = self._pop_any(params, "imageSize", "image_size")
        image_options = {}
        if aspect_ratio:
            image_options["aspectRatio"] = str(aspect_ratio).strip()
        if image_size:
            image_options["imageSize"] = str(image_size).strip().upper()
        if image_options:
            generation_config["imageConfig"] = image_options
        return generation_config

    def _build_top_level_overrides(self, params: Dict[str, Any]) -> Dict[str, Any]:
        top_level = {}
        for source_key, target_key in (
            ("safetySettings", "safetySettings"),
            ("safety_settings", "safetySettings"),
            ("systemInstruction", "systemInstruction"),
            ("system_instruction", "systemInstruction"),
        ):
            if source_key in params:
                top_level[target_key] = params.pop(source_key)
        return top_level

    def _failure_summary(self, payload: Any) -> str:
        if not isinstance(payload, dict):
            return summarize_response_text_for_log(str(payload), max_string_length=500)
        candidates = payload.get("candidates")
        if isinstance(candidates, list) and candidates:
            candidate = candidates[0] if isinstance(candidates[0], dict) else {}
            finish_reason = candidate.get("finishReason") or candidate.get("finish_reason") or "UNKNOWN"
            content = candidate.get("content") or {}
            parts = content.get("parts") if isinstance(content, dict) else []
            texts = []
            if isinstance(parts, list):
                texts = [str(part.get("text", "")).strip() for part in parts if isinstance(part, dict) and part.get("text")]
            text_suffix = f"；文本响应: {' '.join(texts)[:240]}" if texts else ""
            return f"finishReason={finish_reason}{text_suffix}"
        return summarize_payload_json_for_log(payload, max_string_length=500)

    async def _post_json(self, endpoint: str, headers: Dict[str, str], payload: Dict[str, Any]) -> str:
        timeout_obj = aiohttp.ClientTimeout(total=self.config.timeout)
        logger.info(f"📤 [Gemini官方通道] 请求路径: {summarize_url_for_log(endpoint)}")
        logger.info(f"📤 [Gemini官方通道] 请求体摘要: {summarize_payload_json_for_log(payload)}")
        async with self.session.post(endpoint, json=payload, headers=headers, timeout=timeout_obj) as response:
            text = await response.text()
            if response.status >= 400:
                logger.error("💥 Gemini官方通道 API 返回错误摘要: " + summarize_response_text_for_log(text, max_string_length=500))
                raise RuntimeError(f"HTTP {response.status}: {extract_error_message(text)}")
            try:
                result = json.loads(text)
            except Exception:
                raise ValueError("Gemini 官方接口返回结构异常，响应不是 JSON: " + summarize_response_text_for_log(text))
            image_url = extract_image_url_from_response(result, endpoint)
            if image_url:
                return image_url
            raise ValueError("Gemini 官方接口未返回图片数据: " + self._failure_summary(result))

    async def generate_image(self, prompt: str, **kwargs: Any) -> str:
        current_key = self.get_current_key()
        if not current_key:
            raise ValueError("节点未配置 API Key！")

        ref_images = self.get_reference_images(**kwargs)
        if len(ref_images) > MAX_REFERENCE_IMAGES:
            raise ValueError(f"Gemini 官方接口最多支持 {MAX_REFERENCE_IMAGES} 张参考图。")

        internal_keys = {"user_refs", "user_ref", "persona_refs", "persona_ref"}
        api_kwargs = {key: value for key, value in kwargs.items() if key not in internal_keys}
        model = self._request_model(api_kwargs)
        if not model:
            raise ValueError("Gemini 官方节点未配置模型名！")

        endpoint = self._endpoint(model)
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": current_key,
        }

        parts: List[Dict[str, Any]] = [{"text": str(prompt or "")}]
        for index, ref_image in enumerate(ref_images, start=1):
            try:
                parts.append(await self._inline_image_part(ref_image))
            except Exception as exc:
                raise RuntimeError(f"读取第 {index} 张参考图数据失败: {exc}")

        payload: Dict[str, Any] = {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": self._build_generation_config(api_kwargs),
        }
        payload.update(self._build_top_level_overrides(api_kwargs))

        if api_kwargs:
            ignored = ", ".join(sorted(str(key) for key in api_kwargs))
            logger.info(f"ℹ️ [Gemini官方通道] 已忽略非 Gemini 官方参数: {ignored}")

        logger.info(f"📝 [Gemini官方通道] 最终发送给 API 的核心提示词:\n{prompt}")
        return await self._post_json(endpoint, headers, payload)
