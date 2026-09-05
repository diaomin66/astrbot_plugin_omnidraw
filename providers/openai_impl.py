import aiohttp
import base64
import json
from typing import Any

from astrbot.api import logger

from .base import (
    BaseProvider,
    build_image_edits_endpoint,
    build_image_generations_endpoint,
    extract_error_message,
    extract_image_url_from_response,
    read_response_text_limited,
    summarize_payload_json_for_log,
    summarize_response_text_for_log,
)

class OpenAIProvider(BaseProvider):
    async def generate_image(self, prompt: str, **kwargs: Any) -> str:
        current_key = self.get_current_key()
        if not current_key:
            raise ValueError("节点未配置 API Key！")

        base_url = self.config.base_url
        ref_images = self.get_reference_images(**kwargs)

        logger.info(f"📝 [标准通道] 最终发送给 API 的核心提示词:\n{prompt}")

        api_kwargs = self.filter_api_kwargs(kwargs)

        if ref_images:
            url = build_image_edits_endpoint(base_url)
            logger.info(f"✅ 检测到 {len(ref_images)} 张参考图，正切换至标准改图通道: {url}")
            max_images = 3 if url.lower().split("?", 1)[0].endswith("/images/generations") else 14
            loaded_refs = await self.load_reference_images(ref_images, max_images=max_images)

            if url.lower().split("?", 1)[0].endswith("/images/generations"):
                payload = {
                    "model": self.config.model,
                    "prompt": prompt,
                    "n": 1,
                }
                for idx, (image_bytes, mime_type) in enumerate(loaded_refs, start=1):
                    image_value = f"data:{mime_type};base64," + base64.b64encode(image_bytes).decode("utf-8")
                    payload["image" if idx == 1 else f"image{idx}"] = image_value
                payload.update(api_kwargs)
                log_payload = {k: v for k, v in payload.items() if not str(k).startswith("image")}
                logger.info(f"📤 [标准通道] 附带高级参数的请求体摘要: {summarize_payload_json_for_log(log_payload)}")
                headers = {"Content-Type": "application/json", "Authorization": "Bearer " + current_key}
                timeout_obj = aiohttp.ClientTimeout(total=self.config.timeout)
                async with self.session.post(url, json=payload, headers=headers, timeout=timeout_obj) as response:
                    return await self._parse_response(response, base_url)

            data = aiohttp.FormData()
            for idx, (image_bytes, mime_type) in enumerate(loaded_refs, start=1):
                data.add_field(
                    "image",
                    image_bytes,
                    filename=f"reference_{idx}.png",
                    content_type=mime_type,
                )

            data.add_field('prompt', prompt)
            data.add_field('model', self.config.model)
            data.add_field('n', '1')

            # 高级参数注入表单
            for k, v in api_kwargs.items():
                data.add_field(k, str(v))

            headers = {"Authorization": "Bearer " + current_key}
            timeout_obj = aiohttp.ClientTimeout(total=self.config.timeout)
            async with self.session.post(url, data=data, headers=headers, timeout=timeout_obj) as response:
                return await self._parse_response(response, base_url)

        else:
            url = build_image_generations_endpoint(base_url)

            # 基础 Payload
            payload = {
                "model": self.config.model,
                "prompt": prompt,
                "n": 1
            }

            # 🚀 完美兼容 gptimage2 / gemini-3.1-image 规范
            # 暴力将所有高级参数塞入 JSON 的最外层，中转 API 会直接识别并调用底层
            payload.update(api_kwargs)

            logger.info(f"📤 [标准通道] 附带高级参数的请求体摘要: {summarize_payload_json_for_log(payload)}")

            headers = {"Content-Type": "application/json", "Authorization": "Bearer " + current_key}

            timeout_obj = aiohttp.ClientTimeout(total=self.config.timeout)
            async with self.session.post(url, json=payload, headers=headers, timeout=timeout_obj) as response:
                return await self._parse_response(response, base_url)

    async def _parse_response(self, response: aiohttp.ClientResponse, base_url: str) -> str:
        status = response.status
        response_text = await read_response_text_limited(response)
        if status != 200:
            logger.error("💥 API 返回错误摘要: " + summarize_response_text_for_log(response_text, max_string_length=500))
            error_msg = extract_error_message(response_text)

            raise RuntimeError("HTTP " + str(status) + ": " + error_msg)

        try:
            result = json.loads(response_text)
        except Exception:
            raise ValueError("API 返回结构异常，响应不是 JSON: " + summarize_response_text_for_log(response_text))
        image_url = extract_image_url_from_response(result, base_url)
        if image_url:
            return image_url

        raise ValueError(
            "API 返回结构异常，未找到图片数据: "
            + summarize_payload_json_for_log(result, max_string_length=500)
        )
