"""
AstrBot 万象画卷插件 v3.1 - OpenAI 标准实现
破解失效之谜：严格遵循 multipart/form-data 规范进行改图
"""
import aiohttp
import json
from typing import Any
from astrbot.api import logger
from .base import BaseProvider

class OpenAIProvider(BaseProvider):

    async def _get_image_bytes(self, image_path_or_url: str) -> bytes:
        """获取图片的真实二进制数据，用于表单文件上传"""
        if image_path_or_url.startswith("http"):
            async with self.session.get(image_path_or_url) as resp:
                return await resp.read()
        else:
            with open(image_path_or_url, "rb") as f:
                return f.read()

    async def generate_image(self, prompt: str, **kwargs: Any) -> str:
        current_key = self.get_current_key()
        if not current_key:
            raise ValueError(f"节点 [{self.config.id}] 未配置 API Key！")

        base_url = self.config.base_url.rstrip("/")
        
        # 提取参考图 (双轨制：聊天捕获的动作图 > WebUI固定人设图)
        ref_image = kwargs.get("user_ref") or kwargs.get("persona_ref")

        if ref_image:
            # ==========================================
            # 🖼️ 图生图模式 (Image-to-Image / Edits)
            # ==========================================
            url = f"{base_url}/images/edits" if not base_url.endswith("/v1") else f"{base_url}/edits"
            logger.info(f"✅ 检测到参考图，正切换至标准改图通道: {url}")
            
            try:
                image_bytes = await self._get_image_bytes(ref_image)
            except Exception as e:
                raise RuntimeError(f"读取参考图数据失败: {e}")

            data = aiohttp.FormData()
            data.add_field('image', image_bytes, filename='reference.png', content_type='image/png')
            data.add_field('prompt', prompt)
            data.add_field('model', self.config.model)
            data.add_field('n', '1')
            
            headers = {
                "Authorization": f"Bearer {current_key}"
            }
            
            logger.debug(f"[{self.config.id}] 📦 Payload -> [Multipart Form Data: 文件流 + 提示词]")
            
            timeout_obj = aiohttp.ClientTimeout(total=self.config.timeout)
            async with self.session.post(url, data=data, headers=headers, timeout=timeout_obj) as response:
                return await self._parse_response(response, base_url)
                
        else:
            # ==========================================
            # 🎨 文生图模式 (Text-to-Image / Generations)
            # ==========================================
            url = f"{base_url}/images/generations" if not base_url.endswith("/v1") else f"{base_url}/generations"
            
            payload = {
                "model": self.config.model,
                "prompt": prompt,
                "n": 1,
            }
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {current_key}"
            }
            
            logger.debug(f"[{self.config.id}] 📦 JSON Payload -> {json.dumps(payload, ensure_ascii=False)}")
            
            timeout_obj = aiohttp.ClientTimeout(total=self.config.timeout)
            async with self.session.post(url, json=payload, headers=headers, timeout=timeout_obj) as response:
                return await self._parse_response(response, base_url)

    async def _parse_response(self, response: aiohttp.ClientResponse, base_url: str) -> str:
        status = response.status
        if status != 200:
            error_text = await response.text()
            logger.error(f"[{self.config.id}] 💥 API 返回错误:\n{error_text}")
            error_msg = error_text
            try:
                error_json = json.loads(error_text)
                if "error" in error_json and "message" in error_json["error"]:
                    error_msg = error_json["error"]["message"]
            except Exception:
                pass
            
            if "not exist" in error_text.lower() or status == 404:
                error_msg += " (提示: 您的 API 节点可能不支持标准的 /images/edits 改图接口哦)"
                
            raise RuntimeError(f"HTTP {status}: {error_msg}")
        
        result = await response.json()
        
        if "data" in result and len(result["data"]) > 0:
            if "b64_json" in result["data"][0]:
                return f"data:image/png;base64,{result['data'][0]['b64_json']}"
            if "url" in result["data"][0]:
                img_url = result["data"][0]["url"]
                if not img_url.startswith("http") and not img_url.startswith("data:"):
                    # 优化了拼接写法，防止低版本 Python 解析 f-string 报错
                    clean_base = base_url.rstrip("/v1")
                    clean_url = img_url.lstrip("/")
                    img_url = f"{clean_base}/{clean_url}"
                return img_url
                
        raise ValueError(f"API 返回
