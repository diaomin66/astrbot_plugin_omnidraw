"""
AstrBot 万象画卷插件 v3.1 - OpenAI 标准实现 (极度防弹版)
破解失效之谜：严格遵循 multipart/form-data 规范进行改图
"""
import aiohttp
import json
from typing import Any
from astrbot.api import logger
from .base import BaseProvider

class OpenAIProvider(BaseProvider):

    async def _get_image_bytes(self, image_path_or_url: str) -> bytes:
        if image_path_or_url.startswith("http"):
            async with self.session.get(image_path_or_url) as resp:
                return await resp.read()
        else:
            with open(image_path_or_url, "rb") as f:
                return f.read()

    async def generate_image(self, prompt: str, **kwargs: Any) -> str:
        current_key = self.get_current_key()
        if not current_key:
            raise ValueError("节点未配置 API Key！")

        # 去掉末尾可能多余的斜杠
        base_url = self.config.base_url.rstrip("/")
        ref_image = kwargs.get("user_ref") or kwargs.get("persona_ref")

        if ref_image:
            # ==========================================
            # 🖼️ 图生图模式 (Image-to-Image / Edits)
            # 修复：直接老老实实拼接 /images/edits，不再做多余截断
            # ==========================================
            url = base_url + "/images/edits"
            logger.info("✅ 检测到参考图，正切换至标准改图通道: " + url)
            
            try:
                image_bytes = await self._get_image_bytes(ref_image)
            except Exception as e:
                raise RuntimeError("读取参考图数据失败: " + str(e))

            data = aiohttp.FormData()
            data.add_field('image', image_bytes, filename='reference.png', content_type='image/png')
            data.add_field('prompt', prompt)
            data.add_field('model', self.config.model)
            data.add_field('n', '1')
            
            headers = {"Authorization": "Bearer " + current_key}
            timeout_obj = aiohttp.ClientTimeout(total=self.config.timeout)
            async with self.session.post(url, data=data, headers=headers, timeout=timeout_obj) as response:
                return await self._parse_response(response, base_url)
                
        else:
            # ==========================================
            # 🎨 文生图模式 (Text-to-Image / Generations)
            # ==========================================
            url = base_url + "/images/generations"
            payload = {"model": self.config.model, "prompt": prompt, "n": 1}
            headers = {"Content-Type": "application/json", "Authorization": "Bearer " + current_key}
            
            timeout_obj = aiohttp.ClientTimeout(total=self.config.timeout)
            async with self.session.post(url, json=payload, headers=headers, timeout=timeout_obj) as response:
                return await self._parse_response(response, base_url)

    async def _parse_response(self, response: aiohttp.ClientResponse, base_url: str) -> str:
        status = response.status
        if status != 200:
            error_text = await response.text()
            logger.error("💥 API 返回错误:\n" + error_text)
            error_msg = error_text
            try:
                error_json = json.loads(error_text)
                if "error" in error_json and "message" in error_json["error"]:
                    error_msg = error_json["error"]["message"]
            except Exception:
                pass
                
            raise RuntimeError("HTTP " + str(status) + ": " + error_msg)
        
        result = await response.json()
        
        if "data" in result and len(result["data"]) > 0:
            data_item = result["data"][0]
            if "b64_json" in data_item:
                return "data:image/png;base64," + data_item["b64_json"]
            if "url" in data_item:
                img_url = data_item["url"]
                if not img_url.startswith("http") and not img_url.startswith("data:"):
                    clean_base = base_url.rstrip("/v1")
                    clean_url = img_url.lstrip("/")
                    img_url = clean_base + "/" + clean_url
                return img_url
                
        raise ValueError("API 返回结构异常，未找到图片数据: " + str(result))
