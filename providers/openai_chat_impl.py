"""
AstrBot 万象画卷插件 v3.1 - OpenAI Chat 兼容实现
功能：严格遵循 Chat/Vision 协议，通过单 User 节点与前置图片确保参考图送达
"""
import aiohttp
import re
import json
import base64
from typing import Any
from astrbot.api import logger

from .base import BaseProvider

class OpenAIChatProvider(BaseProvider):

    async def _encode_image_to_base64(self, image_path_or_url: str) -> str:
        """拦截网络图片下载，对抗防盗链，转化为标准的 Base64 协议"""
        try:
            if image_path_or_url.startswith("http"):
                logger.info("📥 正在本地内存中拦截并下载网络参考图...")
                headers = {"User-Agent": "Mozilla/5.0"}
                async with self.session.get(image_path_or_url, headers=headers) as resp:
                    if resp.status == 200:
                        image_bytes = await resp.read()
                        # 确保带有 MimeType 前缀，这是 Vision 协议的硬性要求
                        return "data:image/png;base64," + base64.b64encode(image_bytes).decode('utf-8')
                    else:
                        logger.error(f"下载网络图片失败，状态码: {resp.status}")
                        return ""
            else:
                with open(image_path_or_url, "rb") as f:
                    return "data:image/png;base64," + base64.b64encode(f.read()).decode('utf-8')
        except Exception as e:
            logger.error("读取或下载参考图失败: " + str(e))
            return ""

    async def generate_image(self, prompt: str, **kwargs: Any) -> str:
        current_key = self.get_current_key()
        if not current_key:
            raise ValueError("节点未配置 API Key！")

        target_refs = self.get_reference_images(**kwargs)

        # ==========================================
        # 🚀 学习 Gitee AI 的标准 Vision 协议构造法
        # ==========================================
        user_content = []

        # 1. ⚠️ 关键修正：图片必须在文字之前！
        # 绝大多数大模型是顺序读取 Token 的，必须让它先“看”到图，再“听”你的要求
        image_count = 0
        for ref_image in target_refs:
            b64_image = await self._encode_image_to_base64(ref_image)
            if not b64_image:
                continue
            user_content.append({
                "type": "image_url",
                "image_url": {
                    "url": b64_image
                }
            })
            image_count += 1

        if image_count:
            logger.info(f"✅ [Chat/Vision通道] 成功将 {image_count} 张参考图封装为视觉信号 (Image First)")

        # 2. 注入提示词
        # ⚠️ 关键修正：抛弃 System 角色，将系统指令合并到 User 里，确保多模态网关不拦截
        full_prompt = (
            "You are a professional image generation assistant. "
            "Based on the prompt and the reference image or images provided above, generate the corresponding image. "
            "Return ONLY the markdown image link: ![image](url). DO NOT output any extra conversational text.\n\n"
            f"Prompt: {prompt}"
        )
        
        user_content.append({
            "type": "text",
            "text": full_prompt
        })
        
        logger.info(f"📝 [Chat/Vision通道] 最终发送给 API 的核心提示词:\n{prompt}")

        payload = {
            "model": self.config.model,
            "messages": [
                {
                    "role": "user", 
                    "content": user_content
                }
            ]
        }

        headers = {
            "Content-Type": "application/json",
            "Authorization": "Bearer " + current_key
        }
        
        base_url = self.config.base_url.rstrip("/")
        url = base_url + "/v1/chat/completions" if not base_url.endswith("/v1") else base_url + "/chat/completions"
        
        timeout_obj = aiohttp.ClientTimeout(total=self.config.timeout)
        async with self.session.post(url, json=payload, headers=headers, timeout=timeout_obj) as response:
            status = response.status
            if status != 200:
                error_text = await response.text()
                raise RuntimeError("HTTP " + str(status) + ": " + error_text)
            
            result = await response.json()
            if "choices" in result and len(result["choices"]) > 0:
                content = result["choices"][0]["message"]["content"].strip()
                match = re.search(r'!\[.*?\]\((.*?)\)', content)
                if match:
                    return match.group(1)
                if content.startswith("http") or content.startswith("data:image"):
                    return content
                raise ValueError("Chat接口未返回有效图片链接。模型原话: " + content)
            else:
                raise ValueError("API返回结构异常: " + str(result))
