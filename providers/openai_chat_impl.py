"""
AstrBot 万象画卷插件 v1.1.0

功能描述：
- OpenAI Chat 接口 (/v1/chat/completions) 出图实现
- 已支持多密钥自动轮询与增强日志

作者: your_name
版本: 1.1.0
日期: 2026-04-25
"""

import aiohttp
import asyncio
import re
import json
from typing import Any
from astrbot.api import logger
from .base import BaseProvider
from ..constants import API_TIMEOUT_DEFAULT

class OpenAIChatProvider(BaseProvider):
    """OpenAI 聊天接口出图支持"""
    
    async def generate_image(self, prompt: str, **kwargs: Any) -> str:
        # 【关键修改 1】：通过父类方法获取当前轮询到的 Key
        current_key = self.get_current_key()
        if not current_key:
            raise ValueError(f"节点 [{self.config.id}] 未配置任何 API Key！")

        # 强制模型只返回 Markdown 图片链接
        payload = {
            "model": self.config.model,
            "messages": [
                {
                    "role": "system", 
                    "content": "You are a direct image link generator. Based on the user's prompt, generate an image and output ONLY the image markdown link: ![image](url). Do not output any other text or explanations."
                },
                {
                    "role": "user", 
                    "content": prompt
                }
            ]
        }
        
        if kwargs:
            logger.info(f"[{self.config.id}] 收到额外高级参数: {kwargs}")
        
        # 安全脱敏 Key (只显示前4位和后4位，注意这里使用的是 current_key)
        safe_key = f"{current_key[:4]}...{current_key[-4:]}" if len(current_key) > 8 else "INVALID_KEY"
        
        # 【关键修改 2】：请求头注入当前轮询的 Key
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {current_key}"
        }
        
        base_url = self.config.base_url.rstrip("/")
        url = f"{base_url}/v1/chat/completions" if not base_url.endswith("/v1") else f"{base_url}/chat/completions"
        
        # --- 阶段 1：请求前日志查岗 ---
        logger.info(f"[{self.config.id}] 📡 发起请求 -> URL: {url}")
        logger.info(f"[{self.config.id}] 🔑 使用凭证 -> Bearer {safe_key}")
        logger.debug(f"[{self.config.id}] 📦 Payload -> {json.dumps(payload, ensure_ascii=False)}")
        
        timeout_obj = aiohttp.ClientTimeout(total=API_TIMEOUT_DEFAULT)
        
        async with self.session.post(url, json=payload, headers=headers, timeout=timeout_obj) as response:
            status = response.status
            logger.info(f"[{self.config.id}] 📥 收到响应状态码: {status}")
            
            # --- 阶段 2：请求后验尸 ---
            if status != 200:
                error_text = await response.text()
                logger.error(f"[{self.config.id}] 💥 API 返回了错误内容:\n{error_text}")
                raise RuntimeError(f"HTTP {status}: {error_text}")
            
            result = await response.json()
            logger.debug(f"[{self.config.id}] 📄 API 原始返回 JSON: {json.dumps(result, ensure_ascii=False)}")
            
            # --- 阶段 3：数据解析 ---
            if "choices" in result and len(result["choices"]) > 0:
                content = result["choices"][0]["message"]["content"].strip()
                logger.info(f"[{self.config.id}] 🤖 模型回复原话: {content}")
                
                # 正则提取 Markdown URL: ![...](URL)
                match = re.search(r'!\[.*?\]\((.*?)\)', content)
                if match:
                    return match.group(1)
                
                # 兼容直接返回链接的情况
                if content.startswith("http") or content.startswith("data:image"):
                    return content
                    
                raise ValueError(f"Chat接口未返回有效图片链接。模型原话: {content}")
            else:
                raise ValueError(f"API返回结构异常: {result}")
