"""
AstrBot 万象画卷插件 v1.3.0

功能描述：
- OpenAI 标准绘图接口 (/v1/images/generations) 实现
- [增强版]：同时兼容 Dall-E-3 无参考图文生图，以及兼容 API 网关的 Image-to-Image / ControlNet
"""

import aiohttp
import asyncio
import json
from typing import Any
from astrbot.api import logger
from .base import BaseProvider
from ..constants import API_TIMEOUT_SLOW

class OpenAIProvider(BaseProvider):
    """OpenAI 标准绘图接口出图支持"""
    
    async def generate_image(self, prompt: str, **kwargs: Any) -> str:
        current_key = self.get_current_key()
        if not current_key:
            raise ValueError(f"节点 [{self.config.id}] 未配置任何 API Key！")

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {current_key}"
        }
        
        # 安全脱敏日志
        safe_key = f"{current_key[:4]}...{current_key[-4:]}" if len(current_key) > 8 else "INVALID_KEY"
        
        base_url = self.config.base_url.rstrip("/")
        # 处理 DALL-E-3 接口路由
        url = f"{base_url}/images/generations" if not base_url.endswith("/v1") else f"{base_url}/generations"
        
        # --- 增强版参数解析：支持 Image-to-Image ---
        # 尝试从 kwargs 中获取由 PersonaManager 注入的参考图路径
        image_path_or_url = kwargs.get("ref_image_path_or_url")
        b64_image = None
        
        # 如果提供了参考图路径且需要启用 Image-to-Image
        # 关键限制警告：Dall-E-3 原生不支持 Image-to-Image。以下逻辑仅适用于提供该功能的兼容网关。
        if image_path_or_url:
            # 判断如果是本地路径且非 dall-e-3 模型，才尝试 Image-to-Image
            # 这是为了防止在原生 DALL-E-3 节点强行发送图片组件导致报错
            model_lower = self.config.model.lower()
            if "dall-e" not in model_lower:
                # 尝试转 Base64。基类方法会检查路径是否存在。
                b64_image = self.encode_local_image_to_base64(image_path_or_url)
            else:
                logger.warning(f"⚠️ [OpenAI] 模型为 {self.config.model}，不支持人设图参考。将仅使用 Prompt Description 文生图。")

        # --- 组装最终 Payload ---
        payload = {
            "model": self.config.model,
            "prompt": prompt,
            "n": 1,
            # 将 kwargs 的附加参数 (如尺寸 --size 1024x1024) 覆盖注入
            **{k: v for k, v in kwargs.items() if k not in ["ref_image_path_or_url"]} 
        }
        
        # Dall-E-3 的 size 有严格要求，需要检查
        if "dall-e-3" in self.config.model and "size" in payload:
            if payload["size"] not in ["1024x1024", "1024x1792", "1792x1024"]:
                logger.warning(f"⚠️ [OpenAI] DALL-E-3 不支持 size={payload['size']}, 已重置为默认值。")
                payload.pop("size")

        # 如果注入了 Base64 参考图，采用 Image-to-Image 格式发送 Payload
        if b64_image:
            logger.info(f"✅ [OpenAI] 节点支持，正在以 Image-to-Image / ControlNet 模式发送请求。")
            # 这里采用了许多 Dall-E-3 兼容 Image-to-Image 接口流行的参数格式
            # 具体格式可能需要根据你实际的兼容 API 网关进行微调。
            # 通常是将 Base64 图片塞入一个 image 或 images 参数中。
            payload["image"] = b64_image # 示例：将 Base64 塞入 image
            # 如果是 ControlNet 网关，payload["image_to_image"] 等也可能需要注入

        # --- 阶段 1：请求前日志查岗 ---
        logger.info(f"[{self.config.id}] 📡 发起请求 -> URL: {url}")
        logger.info(f"[{self.config.id}] 🔑 使用凭证 -> Bearer {safe_key}")
        # 日志中脱敏 Base64 文本，防止污染
        payload_for_log = {k: (v[:30] + '...' if k == "image" and isinstance(v, str) else v) for k, v in payload.items()}
        logger.debug(f"[{self.config.id}] 📦 Payload -> {json.dumps(payload_for_log, ensure_ascii=False)}")
        
        # 慢动作请求 ( timeout 设置长一些)
        timeout_obj = aiohttp.ClientTimeout(total=API_TIMEOUT_SLOW)
        
        async with self.session.post(url, json=payload, headers=headers, timeout=timeout_obj) as response:
            status = response.status
            logger.info(f"[{self.config.id}] 📥 收到响应状态码: {status}")
            
            # --- 阶段 2：请求后验尸 ---
            if status != 200:
                error_text = await response.text()
                logger.error(f"[{self.config.id}] 💥 API 返回了错误内容:\n{error_text}")
                # 增强错误解析逻辑，看看有没有具体的 error message
                error_msg = error_text
                try:
                    error_json = json.loads(error_text)
                    if "error" in error_json and "message" in error_json["error"]:
                        error_msg = error_json["error"]["message"]
                except: pass
                
                # 特殊捕获：如果用户使用了原生 DALL-E-3 强行发了图片，DALL-E-3 的报错是：'extra_keys_not_allowed'
                if "extra_keys_not_allowed" in error_text:
                    raise RuntimeError(f"API节点 {self.config.id} ({self.config.model}) 不支持Image-to-Image参考图。报错详情: {error_msg}")
                    
                raise RuntimeError(f"HTTP {status}: {error_msg}")
            
            result = await response.json()
            # logger.debug(f"[{self.config.id}] 📄 API 原始返回 JSON: {json.dumps(result, ensure_ascii=False)}")
            
            # --- 阶段 3：数据解析 ---
            # 兼容标准 OpenAI dall-e-3 格式: {"data": [{"url": "..."}]}
            if "data" in result and len(result["data"]) > 0:
                # 优先检查 b64_json (用于兼容性好的 Image-to-Image 接口)
                if "b64_json" in result["data"][0]:
                    # 如果返回的是 Base64 数据，我们需要返回 Base64 字符串供外界调用 Image.fromBase64
                    # 这里直接返回整个 data:image/png;base64,... 用于外界统一 Image.fromURL 兼容？
                    # 最好统一处理。这里假设外界 Image.fromURL 完美兼容 data 开头的 Base64
                    b64_data = result["data"][0]["b64_json"]
                    return f"data:image/png;base64,{b64_data}"
                
                # 标准 URL
                if "url" in result["data"][0]:
                    url = result["data"][0]["url"]
                    # 许多自定义网关返回相对路径，我们需要拼接
                    if not url.startswith("http") and not url.startswith("data:"):
                        url = f"{base_url.rstrip('/v1')}/{url.lstrip('/')}"
                    return url
                    
            raise ValueError(f"API返回结构异常: {result}")
