import aiohttp
import base64
from typing import Any

from astrbot.api import logger

from .base import (
    BaseProvider,
    build_image_edits_endpoint,
    build_image_generations_endpoint,
    extract_error_message,
    extract_image_url_from_response,
    guess_image_content_type,
    summarize_payload_json_for_log,
    summarize_response_text_for_log,
)

class OpenAIProvider(BaseProvider):

    async def _get_image_bytes(self, image_path_or_url: str) -> bytes:
        """拦截网络图片下载，对抗防盗链"""
        if image_path_or_url.startswith("data:image"):
            try:
                return base64.b64decode(image_path_or_url.split(",", 1)[1], validate=False)
            except Exception as exc:
                raise RuntimeError(f"Base64 参考图解析失败: {exc}")
        if image_path_or_url.startswith("http"):
            logger.info("📥 [标准通道] 正在本地内存中拦截并下载网络参考图...")
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            }
            async with self.session.get(image_path_or_url, headers=headers) as resp:
                if resp.status == 200:
                    return await resp.read()
                else:
                    raise RuntimeError(f"拦截下载网络图片失败，服务器返回状态码: {resp.status}")
        else:
            with open(image_path_or_url, "rb") as f:
                return f.read()

    def _content_type(self, image_path_or_url: str) -> str:
        return guess_image_content_type(image_path_or_url)

    async def _encode_image_to_data_url(self, image_path_or_url: str) -> str:
        image_bytes = await self._get_image_bytes(image_path_or_url)
        mime_type = self._content_type(image_path_or_url)
        return f"data:{mime_type};base64," + base64.b64encode(image_bytes).decode("utf-8")

    async def generate_image(self, prompt: str, **kwargs: Any) -> str:
        current_key = self.get_current_key()
        if not current_key:
            raise ValueError("节点未配置 API Key！")

        base_url = self.config.base_url
        ref_images = self.get_reference_images(**kwargs)

        logger.info(f"📝 [标准通道] 最终发送给 API 的核心提示词:\n{prompt}")

        # 🚀 剥离内置参数，剩下的全是用户或 LLM 透传的高级参数
        internal_keys = {"user_refs", "user_ref", "persona_refs", "persona_ref"}
        api_kwargs = {k: v for k, v in kwargs.items() if k not in internal_keys}

        if ref_images:
            url = build_image_edits_endpoint(base_url)
            logger.info(f"✅ 检测到 {len(ref_images)} 张参考图，正切换至标准改图通道: {url}")

            if url.lower().endswith("/images/generations"):
                payload = {
                    "model": self.config.model,
                    "prompt": prompt,
                    "n": 1,
                }
                for idx, ref_image in enumerate(ref_images[:3], start=1):
                    try:
                        image_value = await self._encode_image_to_data_url(ref_image)
                    except Exception as e:
                        raise RuntimeError(f"读取第 {idx} 张参考图数据失败: {e}")
                    payload["image" if idx == 1 else f"image{idx}"] = image_value
                payload.update(api_kwargs)
                log_payload = {k: v for k, v in payload.items() if not str(k).startswith("image")}
                logger.info(f"📤 [标准通道] 附带高级参数的请求体摘要: {summarize_payload_json_for_log(log_payload)}")
                headers = {"Content-Type": "application/json", "Authorization": "Bearer " + current_key}
                timeout_obj = aiohttp.ClientTimeout(total=self.config.timeout)
                async with self.session.post(url, json=payload, headers=headers, timeout=timeout_obj) as response:
                    return await self._parse_response(response, base_url)

            data = aiohttp.FormData()
            for idx, ref_image in enumerate(ref_images, start=1):
                try:
                    image_bytes = await self._get_image_bytes(ref_image)
                except Exception as e:
                    raise RuntimeError(f"读取第 {idx} 张参考图数据失败: {e}")
                data.add_field(
                    "image",
                    image_bytes,
                    filename=f"reference_{idx}.png",
                    content_type=self._content_type(ref_image),
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
        if status != 200:
            error_text = await response.text()
            logger.error("💥 API 返回错误摘要: " + summarize_response_text_for_log(error_text, max_string_length=500))
            error_msg = extract_error_message(error_text)

            raise RuntimeError("HTTP " + str(status) + ": " + error_msg)

        result = await response.json()
        image_url = extract_image_url_from_response(result, base_url)
        if image_url:
            return image_url

        raise ValueError(
            "API 返回结构异常，未找到图片数据: "
            + summarize_payload_json_for_log(result, max_string_length=500)
        )
