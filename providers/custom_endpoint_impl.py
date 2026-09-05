"""Custom full-endpoint image provider."""

import base64
import json
from typing import Any, Dict, List
from urllib.parse import urlparse

import aiohttp
from astrbot.api import logger

from .base import (
    BaseProvider,
    extract_error_message,
    extract_image_url_from_response,
    is_complete_endpoint_url,
    read_response_text_limited,
    summarize_payload_json_for_log,
    summarize_response_text_for_log,
    summarize_text_for_log,
    summarize_url_for_log,
)


class CustomEndpointProvider(BaseProvider):
    """Request exactly the configured URL while adapting payloads by endpoint shape."""

    async def _get_image_bytes(self, image_path_or_url: str) -> bytes:
        image_bytes, _ = await self.read_reference_image(image_path_or_url)
        return image_bytes

    async def _encode_image_to_data_url(self, image_path_or_url: str) -> str:
        image_bytes, mime_type = await self.read_reference_image(image_path_or_url)
        return f"data:{mime_type};base64," + base64.b64encode(image_bytes).decode("utf-8")

    async def _encode_reference_images(self, ref_images: List[str]) -> List[str]:
        loaded_refs = await self.load_reference_images(ref_images)
        return [
            f"data:{mime_type};base64," + base64.b64encode(image_bytes).decode("utf-8")
            for image_bytes, mime_type in loaded_refs
        ]

    def _endpoint(self) -> str:
        endpoint = str(self.config.base_url or "").strip()
        if not is_complete_endpoint_url(endpoint):
            raise ValueError(
                "自定义节点必须填写完整请求路径，例如 "
                "https://api.example.com/v1/images/generations，不能只填域名或 /v1。"
            )
        return endpoint

    def _endpoint_path(self, endpoint: str) -> str:
        return urlparse(endpoint).path.rstrip("/").lower()

    def _build_chat_payload(self, prompt: str, encoded_images: List[str], api_kwargs: Dict[str, Any]) -> Dict[str, Any]:
        content: List[Dict[str, Any]] = []
        for image_url in encoded_images:
            content.append({"type": "image_url", "image_url": {"url": image_url}})
        content.append(
            {
                "type": "text",
                "text": str(prompt or ""),
            }
        )
        payload = {"model": self.config.model, "messages": [{"role": "user", "content": content}]}
        payload.update(api_kwargs)
        return payload

    def _build_responses_payload(
        self,
        prompt: str,
        encoded_images: List[str],
        api_kwargs: Dict[str, Any],
    ) -> Dict[str, Any]:
        content: List[Dict[str, Any]] = [{"type": "input_text", "text": prompt}]
        for image_url in encoded_images:
            content.append({"type": "input_image", "image_url": image_url})
        payload: Dict[str, Any] = {
            "model": self.config.model,
            "input": [{"role": "user", "content": content}] if encoded_images else prompt,
            "tools": [{"type": "image_generation"}],
        }
        payload.update(api_kwargs)
        return payload

    def _build_image_json_payload(
        self,
        prompt: str,
        encoded_images: List[str],
        api_kwargs: Dict[str, Any],
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"model": self.config.model, "prompt": prompt, "n": 1}
        for index, image_url in enumerate(encoded_images[:3]):
            payload["image" if index == 0 else f"image{index + 1}"] = image_url
        payload.update(api_kwargs)
        return payload

    async def _post_json(self, endpoint: str, headers: Dict[str, str], payload: Dict[str, Any]) -> str:
        timeout_obj = aiohttp.ClientTimeout(total=self.config.timeout)
        logger.info(f"📤 [自定义通道] 请求完整路径: {summarize_url_for_log(endpoint)}")
        logger.info(f"📤 [自定义通道] 请求体摘要: {summarize_payload_json_for_log(payload)}")
        async with self.session.post(endpoint, json=payload, headers=headers, timeout=timeout_obj) as response:
            return await self._parse_response(response, endpoint)

    async def _post_edits_form(
        self,
        endpoint: str,
        headers: Dict[str, str],
        prompt: str,
        ref_images: List[str],
        api_kwargs: Dict[str, Any],
    ) -> str:
        loaded_refs = await self.load_reference_images(ref_images)
        data = aiohttp.FormData()
        for index, (image_bytes, mime_type) in enumerate(loaded_refs, start=1):
            data.add_field(
                "image" if len(ref_images) == 1 else "image[]",
                image_bytes,
                filename=f"reference_{index}.png",
                content_type=mime_type,
            )
        data.add_field("prompt", prompt)
        data.add_field("model", self.config.model)
        data.add_field("n", "1")
        for key, value in api_kwargs.items():
            data.add_field(key, str(value))

        timeout_obj = aiohttp.ClientTimeout(total=self.config.timeout)
        logger.info(f"📤 [自定义通道] 以 multipart 请求完整路径: {summarize_url_for_log(endpoint)}")
        async with self.session.post(endpoint, data=data, headers=headers, timeout=timeout_obj) as response:
            return await self._parse_response(response, endpoint)

    async def _parse_response(self, response: aiohttp.ClientResponse, endpoint: str) -> str:
        text = await read_response_text_limited(response)
        if response.status >= 400:
            logger.error("💥 自定义通道 API 返回错误摘要: " + summarize_response_text_for_log(text, max_string_length=500))
            raise RuntimeError(f"HTTP {response.status}: {extract_error_message(text)}")

        try:
            payload = json.loads(text)
        except Exception:
            payload = text

        image_url = extract_image_url_from_response(payload, endpoint)
        if image_url:
            return image_url
        if isinstance(payload, (dict, list, tuple)):
            payload_summary = summarize_payload_json_for_log(payload, max_string_length=500)
        else:
            payload_summary = summarize_text_for_log(str(payload), max_string_length=500)
        raise ValueError("自定义接口返回结构异常，未找到图片数据: " + payload_summary)

    async def generate_image(self, prompt: str, **kwargs: Any) -> str:
        current_key = self.get_current_key()
        if not current_key:
            raise ValueError("节点未配置 API Key！")
        if not self.config.model:
            raise ValueError("自定义节点未配置模型名！")

        endpoint = self._endpoint()
        endpoint_path = self._endpoint_path(endpoint)
        ref_images = self.get_reference_images(**kwargs)
        api_kwargs = self.filter_api_kwargs(kwargs)
        headers = {"Authorization": "Bearer " + current_key}

        logger.info(f"📝 [自定义通道] 最终发送给 API 的核心提示词:\n{prompt}")

        if endpoint_path.endswith("/images/edits") and not ref_images:
            raise ValueError("自定义 /images/edits 完整路径需要至少一张参考图。")
        if endpoint_path.endswith("/images/edits"):
            return await self._post_edits_form(endpoint, headers, prompt, ref_images, api_kwargs)

        if ref_images and len(ref_images) > 3 and not endpoint_path.endswith(("/chat/completions", "/responses")):
            raise ValueError("自定义图片 JSON 接口最多支持 3 张参考图。")
        encoded_images = await self._encode_reference_images(ref_images)
        headers["Content-Type"] = "application/json"

        if endpoint_path.endswith("/chat/completions"):
            payload = self._build_chat_payload(prompt, encoded_images, api_kwargs)
        elif endpoint_path.endswith("/responses"):
            payload = self._build_responses_payload(prompt, encoded_images, api_kwargs)
        else:
            payload = self._build_image_json_payload(prompt, encoded_images, api_kwargs)

        return await self._post_json(endpoint, headers, payload)
