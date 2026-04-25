"""
AstrBot 万象画卷插件 v1.4.0

功能描述：
- OpenAI Chat 接口 (/v1/chat/completions) 出图实现
- [增强版]：支持向多模态视觉模型发送本地/网络参考图 (Vision 格式)
- [增强版]：支持动态读取 WebUI 配置的超时时间
"""

import aiohttp
import asyncio
import re
import json
from typing import Any
from astrbot.api import logger
from .base import BaseProvider

class OpenAIChatProvider(BaseProvider):
    """OpenAI 聊天接口出图支持"""
    
    async def generate_image(self, prompt: str, **kwargs: Any) -> str:
        current_key = self.get_current_key()
        if not current_key:
            raise ValueError(f"节点 [{self.config.id}] 未配置任何 API Key！")

        # --- 增强版参数解析：支持给 Chat 模型喂图片 ---
        image_path_or_url = kwargs.get("ref_image_path_or_url")
        b64_image = None
        
        if image_path_or_url:
            # 基类的这个方法会自动处理转码
            b64_image = self.encode_local_image_to_base64(image_path_or_url)
            if b64_image:
                logger.info(f"✅ [OpenAI Chat] 准备通过视觉模型(Vision)格式发送参考图。")

        # --- 组装对话的 Content ---
        if b64_image:
            # 如果有图片，必须使用复杂的 List 结构
            user_content = [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": b64_image}}
            ]
        else:
            # 如果没图片，用简单的纯文本格式就行
            user_content = prompt

        payload = {
            "model": self.config.model,
            "messages": [
                {
                    "role": "system", 
                    "content": "You are a direct image link generator. Based on the user's prompt and the reference image (if provided), generate an image and output ONLY the image markdown link: ![image](url). Do not output any other text."
                },
                {
                    "role": "user", 
                    "content": user_content
                }
            ]
        }
        
        safe_key = f"{current_key[:4]}...{current_key[-4:]}" if len(current_key) > 8 else "INVALID_KEY"
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {current_key}"
        }
        
        base_url = self.config.base_url.rstrip("/")
        url = f"{base_url}/v1/chat/completions" if not base_url.endswith("/v1") else f"{base_url}/chat/completions"
        
        # --- 阶段 1：请求前日志查岗 ---
        logger.info(f"[{self.config.id}] 📡 发起请求 -> URL: {url}")
        logger.info(f"[{self.config.id}] 🔑 使用凭证 -> Bearer {safe_key}")
        
        # 为了防止 Base64 这种超长的乱码刷爆你的控制台，做个友好的脱敏打印
        payload_for_log = json.loads(json.dumps(payload))
        if b64_image:
            payload_for_log["messages"][1]["content"][1]["image_url"]["url"] = "data:image/png;base64, [已为您省略超长字符串...]"
        logger.debug(f"[{self.config.id}] 📦 Payload -> {json.dumps(payload_for_log, ensure_ascii=False)}")
        
        # 【读取动态超时配置】
        timeout_obj = aiohttp.ClientTimeout(total=self.config.timeout)
        logger.info(f"[{self.config.id}] ⏳ 当前节点设置的超时时间为: {self.config.timeout} 秒")
        
        async with self.session.post(url, json=payload, headers=headers, timeout=timeout_obj) as response:
            status = response.status
            logger.info(f"[{self.config.id}] 📥 收到响应状态码: {status}")
            
            # --- 阶段 2：请求后验尸 ---
            if status != 200:
                error_text = await response.text()
                logger.error(f"[{self.config.id}] 💥 API 返回了错误内容:\n{error_text}")
                raise RuntimeError(f"HTTP {status}: {error_text}")
            
            result = await response.json()
            
            # --- 阶段 3：数据解析 ---
            if "choices" in result and len(result["choices"]) > 0:
                content = result["choices"][0]["message"]["content"].strip()
                logger.info(f"[{self.config.id}] 🤖 模型回复原话: {content}")
                
                match = re.search(r'!\[.*?\]\((.*?)\)', content)
                if match:
                    return match.group(1)
                
                if content.startswith("http") or content.startswith("data:image"):
                    return content
                    
                raise ValueError(f"Chat接口未返回有效图片链接。模型原话: {content}")
            else:
                raise ValueError(f"API返回结构异常: {result}")
