"""Custom full-endpoint image provider."""

import base64
import json
import os
from typing import Any, Dict, List
from urllib.parse import urlparse

import aiohttp
from astrbot.api import logger

from .base import (
    BaseProvider,
    extract_error_message,
    extract_image_url_from_response,
    guess_image_content_type,
    is_complete_endpoint_url,
    summarize_payload_json_for_log,
    summarize_response_text_for_log,
    summarize_text_for_log,
    summarize_url_for_log,
)


class CustomEndpointProvider(BaseProvider):
    """Request exactly the configured URL while adapting payloads by endpoint shape."""

    async def _get_image_bytes(self, image_path_or_url: str) -> bytes:
        if image_path_or_url.startswith("data:image"):
            try:
                return base64.b64decode(image_path_or_url.split(",", 1)[1], validate=False)
            except Exception as exc:
                raise RuntimeError(f"Base64 参考图解析失败: {exc}")
        if image_path_or_url.startswith("http"):
            logger.info("📥 [自定义通道] 正在下载网络参考图并转码...")
            headers = {"User-Agent": "Mozilla/5.0"}
            async with self.session.get(image_path_or_url, headers=headers) as response:
                if response.status != 200:
                    raise RuntimeError(f"参考图下载失败，服务器返回状态码: {response.status}")
                return await response.read()
        if not os.path.exists(image_path_or_url):
            raise RuntimeError(f"本地参考图不存在: {image_path_or_url}")
        with open(image_path_or_url, "rb") as file:
            return file.read()

    async def _encode_image_to_data_url(self, image_path_or_url: str) -> str:
        image_bytes = await self._get_image_bytes(image_path_or_url)
        mime_type = guess_image_content_type(image_path_or_url)
        return f"data:{mime_type};base64," + base64.b64encode(image_bytes).decode("utf-8")

    async def _encode_reference_images(self, ref_images: List[str]) -> List[str]:
        encoded_images = []
        for index, ref_image in enumerate(ref_images, start=1):
            try:
                encoded_images.append(await self._encode_image_to_data_url(ref_image))
            except Exception as exc:
                raise RuntimeError(f"读取第 {index} 张参考图数据失败: {exc}")
        return encoded_images

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
                "text": (
                    "Generate an image from the following prompt and return only one image URL, "
                    "data URL, or markdown image link.\n\n"
                    f"Prompt: {prompt}"
                ),
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
        data = aiohttp.FormData()
        for index, ref_image in enumerate(ref_images, start=1):
            try:
                image_bytes = await self._get_image_bytes(ref_image)
            except Exception as exc:
                raise RuntimeError(f"读取第 {index} 张参考图数据失败: {exc}")
            data.add_field(
                "image" if len(ref_images) == 1 else "image[]",
                image_bytes,
                filename=f"reference_{index}.png",
                content_type=guess_image_content_type(ref_image),
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
        text = await response.text()
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
        internal_keys = {"user_refs", "user_ref", "persona_refs", "persona_ref"}
        api_kwargs = {key: value for key, value in kwargs.items() if key not in internal_keys}
        headers = {"Authorization": "Bearer " + current_key}

        logger.info(f"📝 [自定义通道] 最终发送给 API 的核心提示词:\n{prompt}")

        if endpoint_path.endswith("/images/edits") and not ref_images:
            raise ValueError("自定义 /images/edits 完整路径需要至少一张参考图。")
        if endpoint_path.endswith("/images/edits"):
            return await self._post_edits_form(endpoint, headers, prompt, ref_images, api_kwargs)

        encoded_images = await self._encode_reference_images(ref_images)
        headers["Content-Type"] = "application/json"

        if endpoint_path.endswith("/chat/completions"):
            payload = self._build_chat_payload(prompt, encoded_images, api_kwargs)
        elif endpoint_path.endswith("/responses"):
            payload = self._build_responses_payload(prompt, encoded_images, api_kwargs)
        else:
            payload = self._build_image_json_payload(prompt, encoded_images, api_kwargs)

        return await self._post_json(endpoint, headers, payload)
