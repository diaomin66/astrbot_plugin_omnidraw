"""Stable Diffusion WebUI API provider."""

import base64
import json
import re
from typing import Any, Dict, List
from urllib.parse import urljoin

import aiohttp
from astrbot.api import logger

from .base import BaseProvider, summarize_payload_json_for_log, summarize_response_text_for_log


class StableDiffusionWebUIProvider(BaseProvider):
    """Call Stable Diffusion WebUI's txt2img and img2img endpoints."""

    def _endpoint(self, suffix: str) -> str:
        base_url = str(self.config.base_url or "").strip().rstrip("/")
        if not base_url:
            raise ValueError("Stable Diffusion WebUI 节点未配置接口地址！")

        for known_suffix in ("/sdapi/v1/txt2img", "/sdapi/v1/img2img"):
            if base_url.lower().endswith(known_suffix):
                base_url = base_url[: -len(known_suffix)]
                break
        if base_url.lower().endswith("/sdapi/v1"):
            return f"{base_url}{suffix}"
        return urljoin(base_url + "/", f"sdapi/v1/{suffix.lstrip('/')}" )

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        current_key = self.get_current_key()
        if current_key:
            # Native WebUI commonly uses --api-auth (user:password); Bearer also
            # keeps compatibility with reverse proxies exposing the API this way.
            if ":" in current_key:
                encoded = base64.b64encode(current_key.encode("utf-8")).decode("ascii")
                headers["Authorization"] = f"Basic {encoded}"
            else:
                headers["Authorization"] = f"Bearer {current_key}"
        return headers

    def _size_params(self, value: Any) -> Dict[str, int]:
        match = re.fullmatch(r"\s*(\d+)\s*[xX×]\s*(\d+)\s*", str(value or ""))
        if not match:
            return {}
        width, height = int(match.group(1)), int(match.group(2))
        if width <= 0 or height <= 0:
            return {}
        return {"width": width, "height": height}

    def _coerce_json_value(self, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        try:
            return json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return value

    async def _reference_images(self, refs: List[str]) -> List[str]:
        encoded = []
        for index, ref in enumerate(refs, start=1):
            try:
                data_url = await self.fetch_reference_data_url(ref)
                encoded.append(data_url.split(",", 1)[1] if data_url.startswith("data:") else data_url)
            except Exception as exc:
                raise RuntimeError(f"读取第 {index} 张参考图数据失败: {exc}")
        return encoded

    def _image_from_response(self, payload: Any) -> str:
        if not isinstance(payload, dict) or not isinstance(payload.get("images"), list):
            return ""
        for value in payload["images"]:
            image = str(value or "").strip()
            if not image:
                continue
            if image.startswith("data:image"):
                return image
            try:
                base64.b64decode(image, validate=True)
            except Exception:
                continue
            return f"data:image/png;base64,{image}"
        return ""

    async def generate_image(self, prompt: str, **kwargs: Any) -> str:
        refs = self.get_reference_images(**kwargs)
        api_kwargs = {
            key: self._coerce_json_value(value)
            for key, value in kwargs.items()
            if key not in {
                "user_refs",
                "user_ref",
                "persona_refs",
                "persona_ref",
                "aspect_ratio",
                "size",
                "resolution",
                "model",
            }
        }
        size = kwargs.get("size") or kwargs.get("resolution") or self.config.default_size
        payload: Dict[str, Any] = {"prompt": str(prompt or "")}
        payload.update(self._size_params(size))
        model = str(kwargs.get("model") or self.config.model or "").strip()
        if model:
            payload.setdefault("override_settings", {})
            if isinstance(payload["override_settings"], dict):
                payload["override_settings"].setdefault("sd_model_checkpoint", model)
            payload.setdefault("override_settings_restore_afterwards", True)
        payload.update(api_kwargs)

        if refs:
            payload["init_images"] = await self._reference_images(refs)
            endpoint = self._endpoint("/img2img")
        else:
            endpoint = self._endpoint("/txt2img")

        logger.info(f"📝 [Stable Diffusion WebUI] 最终发送给 API 的核心提示词:\n{prompt}")
        logger.info(f"📤 [Stable Diffusion WebUI] 请求路径: {endpoint}")
        logger.info(f"📤 [Stable Diffusion WebUI] 请求体摘要: {summarize_payload_json_for_log(payload)}")

        timeout_obj = aiohttp.ClientTimeout(total=self.config.timeout)
        async with self.session.post(endpoint, json=payload, headers=self._headers(), timeout=timeout_obj) as response:
            text = await response.text()
            if response.status >= 400:
                logger.error("💥 Stable Diffusion WebUI API 返回错误摘要: " + summarize_response_text_for_log(text))
                raise RuntimeError(f"HTTP {response.status}: {text[:240]}")
            try:
                result = json.loads(text)
            except Exception as exc:
                raise ValueError(f"Stable Diffusion WebUI 返回结构异常，响应不是 JSON: {exc}")

        image = self._image_from_response(result)
        if image:
            return image
        raise ValueError("Stable Diffusion WebUI 返回结构异常，images 中未找到有效图片。")
