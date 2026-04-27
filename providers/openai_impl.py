"""
AstrBot 万象画卷插件 v3.1 - OpenAI 标准实现
功能：保留防盗链本地拦截 + 最终提示词日志打印，纯净相对导入
"""
import aiohttp
import json
from typing import Any
from astrbot.api import logger

# 🚀 纯净的相对导入
from .base import BaseProvider

class OpenAIProvider(BaseProvider):

    async def _get_image_bytes(self, image_path_or_url: str) -> bytes:
        """拦截网络图片下载，对抗防盗链"""
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

    async def generate_image(self, prompt: str, **kwargs: Any) -> str:
        current_key = self.get_current_key()
        if not current_key:
            raise ValueError("节点未配置 API Key！")

        base_url = self.config.base_url.rstrip("/")
        ref_images = self.get_reference_images(**kwargs)

        # ==========================================
        # 📝 核心：打印最终发送给 API 的原味提示词
        # ==========================================
        logger.info(f"📝 [标准通道] 最终发送给 API 的提示词:\n{prompt}")

        if ref_images:
            url = base_url + "/images/edits"
            logger.info(f"✅ 检测到 {len(ref_images)} 张参考图，正切换至标准改图通道: {url}")

            data = aiohttp.FormData()
            for idx, ref_image in enumerate(ref_images, start=1):
                try:
                    image_bytes = await self._get_image_bytes(ref_image)
                except Exception as e:
                    raise RuntimeError(f"读取第 {idx} 张参考图数据失败: {e}")
                data.add_field('image', image_bytes, filename=f'reference_{idx}.png', content_type='image/png')

            data.add_field('prompt', prompt)
            data.add_field('model', self.config.model)
            data.add_field('n', '1')
            
            headers = {"Authorization": "Bearer " + current_key}
            timeout_obj = aiohttp.ClientTimeout(total=self.config.timeout)
            async with self.session.post(url, data=data, headers=headers, timeout=timeout_obj) as response:
                return await self._parse_response(response, base_url)
                
        else:
            # 🎨 文生图模式 (Text-to-Image / Generations)
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
