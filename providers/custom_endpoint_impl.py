"""Custom full-endpoint image provider."""

import asyncio
import json
from typing import Any, Dict, List
from urllib.parse import quote, urlparse

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

    TASK_POLL_INTERVAL_SECONDS = 2

    @staticmethod
    def _coerce_json_value(value: Any) -> Any:
        if not isinstance(value, str):
            return value
        try:
            return json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return value

    async def _get_image_bytes(self, image_path_or_url: str) -> bytes:
        return await self.fetch_reference_bytes(image_path_or_url)

    async def _encode_image_to_data_url(self, image_path_or_url: str) -> str:
        return await self.fetch_reference_data_url(image_path_or_url)

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

    @classmethod
    def _extract_task_id(cls, payload: Any) -> str:
        if isinstance(payload, dict):
            task_id = payload.get("task_id")
            if task_id:
                return str(task_id)
            status = str(payload.get("status", payload.get("task_status", ""))).lower()
            if status in {"submitted", "pending", "queued", "processing", "running"} and payload.get("id"):
                return str(payload["id"])
            for value in payload.values():
                task_id = cls._extract_task_id(value)
                if task_id:
                    return task_id
        elif isinstance(payload, (list, tuple)):
            for item in payload:
                task_id = cls._extract_task_id(item)
                if task_id:
                    return task_id
        return ""

    @classmethod
    def _extract_task_status(cls, payload: Any) -> str:
        if isinstance(payload, dict):
            status = payload.get("status", payload.get("task_status", payload.get("state", "")))
            if status:
                return str(status).lower()
            for value in payload.values():
                status = cls._extract_task_status(value)
                if status:
                    return status
        elif isinstance(payload, (list, tuple)):
            for item in payload:
                status = cls._extract_task_status(item)
                if status:
                    return status
        return ""

    def _task_poll_url(self, endpoint: str, task_id: str) -> str:
        parsed = urlparse(endpoint)
        return f"{parsed.scheme}://{parsed.netloc}/api/tasks/{quote(task_id, safe='')}"

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
            response_payload = await self._read_response_payload(response)
        return await self._resolve_response(response_payload, endpoint, headers)

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
            response_payload = await self._read_response_payload(response)
        return await self._resolve_response(response_payload, endpoint, headers)

    async def _read_response_payload(self, response: aiohttp.ClientResponse) -> Any:
        text = await response.text()
        if response.status >= 400:
            logger.error("💥 自定义通道 API 返回错误摘要: " + summarize_response_text_for_log(text, max_string_length=500))
            raise RuntimeError(f"HTTP {response.status}: {extract_error_message(text)}")

        try:
            return json.loads(text)
        except Exception:
            return text

    async def _resolve_response(self, payload: Any, endpoint: str, headers: Dict[str, str]) -> str:
        image_url = extract_image_url_from_response(payload, endpoint)
        if image_url:
            return image_url
        task_id = self._extract_task_id(payload)
        if task_id:
            return await self._poll_task_result(endpoint, task_id, headers)
        if isinstance(payload, (dict, list, tuple)):
            payload_summary = summarize_payload_json_for_log(payload, max_string_length=500)
        else:
            payload_summary = summarize_text_for_log(str(payload), max_string_length=500)
        raise ValueError("自定义接口返回结构异常，未找到图片数据: " + payload_summary)

    async def _poll_task_result(self, endpoint: str, task_id: str, headers: Dict[str, str]) -> str:
        poll_url = self._task_poll_url(endpoint, task_id)
        poll_interval = max(0.0, float(self.TASK_POLL_INTERVAL_SECONDS))
        attempts = max(1, int(float(self.config.timeout) / max(1.0, poll_interval)))
        for attempt in range(attempts):
            if attempt:
                await asyncio.sleep(poll_interval)
            logger.info(f"⏳ [自定义通道] 轮询图片任务 {task_id} ({attempt + 1}/{attempts})")
            async with self.session.get(
                poll_url,
                headers=headers,
                timeout=min(15.0, float(self.config.timeout)),
            ) as response:
                payload = await self._read_response_payload(response)

            image_url = extract_image_url_from_response(payload, endpoint)
            if image_url:
                return image_url
            status = self._extract_task_status(payload)
            if status in {"fail", "failed", "failure", "error", "cancelled", "canceled"}:
                raise RuntimeError(
                    "异步图片任务失败: "
                    + summarize_payload_json_for_log(payload, max_string_length=500)
                )

        raise TimeoutError(f"异步图片任务 {task_id} 在 {self.config.timeout} 秒内未完成。")

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
        api_kwargs = {
            key: self._coerce_json_value(value)
            for key, value in kwargs.items()
            if key not in internal_keys
        }
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
