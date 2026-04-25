"""
AstrBot 万象画卷插件 v3.1 - OpenAI Chat 兼容实现
功能描述：多模态对话大模型 (Vision) 专用生图/改图通道
核心特性：原生支持双图同传 (人设图 + 动态姿势图混合注入)
"""

import aiohttp
import re
import json
import base64
from typing import Any
from astrbot.api import logger
from data.plugins.astrbot_plugin_omnidraw.providers.base import BaseProvider

class OpenAIChatProvider(BaseProvider):

    async def _encode_image_to_base64(self, image_path_or_url: str) -> str:
        """将图片安全地转为 Base64 Data URL (Chat Vision 标准格式)"""
        if image_path_or_url.startswith("http"):
            return image_path_or_url  # 网络图片直接传 URL

        try:
            with open(image_path_or_url, "rb") as f:
                b64_data = base64.b64encode(f.read()).decode('utf-8')
                # Chat 接口严格要求带 MIME 头部前缀
                return f"data:image/png;base64,{b64_data}"
        except Exception as e:
            logger.error(f"读取本地参考图失败: {e}")
            return ""

    async def generate_image(self, prompt: str, **kwargs: Any) -> str:
        current_key = self.get_current_key()
        if not current_key:
            raise ValueError(f"节点 [{self.config.id}] 未配置 API Key！")

        # 提取参考图
        persona_ref = kwargs.get("persona_ref") # WebUI 上传的人脸/形象
        user_ref = kwargs.get("user_ref")       # 用户聊天的姿势/服装

        user_content = [{"type": "text", "text": prompt}]

        # ==========================================
        # 👁️ 视觉通道：注入参考图 (支持双图同传)
        # ==========================================
        if persona_ref:
            b64_persona = await self._encode_image_to_base64(persona_ref)
            if b64_persona:
                user_content.append({"type": "image_url", "image_url": {"url": b64_persona}})
                logger.info("✅ [Chat/Vision] 成功将【专属人设图】转化为视觉信号注入对话")

        if user_ref:
            b64_user = await self._encode_image_to_base64(user_ref)
            if b64_user:
                user_content.append({"type": "image_url", "image_url": {"url": b64_user}})
                logger.info("✅ [Chat/Vision] 成功将【动态姿势图】转化为视觉信号注入对话")

        # 如果一张图片都没有，退化为简单的纯文本格式
        if len(user_content) == 1:
            user_content = prompt

        payload = {
            "model": self.config.model,
            "messages": [
                {
                    "role": "system", 
                    "content": "You are a professional image generation assistant. Based on the prompt and any reference images (e.g., character face or pose), generate the corresponding image and return ONLY the markdown image link: ![image](url). DO NOT output any extra conversational text."
                },
                {
                    "role": "user", 
                    "content": user_content
                }
            ]
        }

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {current_key}"
        }
        
        base_url = self.config.base_url.rstrip("/")
        url = f"{base_url}/v1/chat/completions" if not base_url.endswith("/v1") else f"{base_url}/chat/completions"
        
        logger.info(f"[{self.config.id}] 📡 发起 Vision 请求 -> URL: {url}")
        
        # 脱敏日志，防止 Base64 乱码刷屏
        payload_for_log = json.loads(json.dumps(payload))
        if isinstance(user_content, list):
            for item in payload_for_log["messages"][1]["content"]:
                if item["type"] == "image_url":
                    item["image_url"]["url"] = "data:image/png;base64, [为了日志清爽，已省略长字符串...]"
        logger.debug(f"[{self.config.id}] 📦 Payload -> {json.dumps(payload_for_log, ensure_ascii=False)}")
        
        timeout_obj = aiohttp.ClientTimeout(total=self.config.timeout)
        
        async with self.session.post(url, json=payload, headers=headers, timeout=timeout_obj) as response:
            status = response.status
            if status != 200:
                error_text = await response.text()
                logger.error(f"[{self.config.id}] 💥 API 返回错误:\n{error_text}")
                raise RuntimeError(f"HTTP {status}: {error_text}")
            
            result = await response.json()
            
            if "choices" in result and len(result["choices"]) > 0:
                content = result["choices"][0]["message"]["content"].strip()
                logger.info(f"[{self.config.id}] 🤖 Chat模型回复原话: {content}")
                
                # 正则提取 Markdown 链接
                match = re.search(r'!\[.*?\]\((.*?)\)', content)
                if match:
                    return match.group(1)
                
                if content.startswith("http") or content.startswith("data:image"):
                    return content
                    
                raise ValueError(f"Chat接口未返回有效图片链接。模型原话: {content}")
            else:
                raise ValueError(f"API返回结构异常: {result}")
