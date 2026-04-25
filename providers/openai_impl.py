"""
AstrBot 万象画卷插件 v3.0 - OpenAI 兼容实现
支持多维度控制：WebUI 固定人脸 (persona_ref) + 用户动态发送姿势 (user_ref)
"""
import aiohttp
import json
from typing import Any
from astrbot.api import logger
from .base import BaseProvider

class OpenAIProvider(BaseProvider):
    
    async def generate_image(self, prompt: str, **kwargs: Any) -> str:
        current_key = self.get_current_key()
        if not current_key:
            raise ValueError(f"节点 [{self.config.id}] 未配置 API Key！")

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {current_key}"
        }
        
        base_url = self.config.base_url.rstrip("/")
        url = f"{base_url}/images/generations" if not base_url.endswith("/v1") else f"{base_url}/generations"
        
        # 提取双重参考图
        persona_ref = kwargs.get("persona_ref") # WebUI 上传的人脸/形象
        user_ref = kwargs.get("user_ref")       # 用户聊天的姿势/服装

        b64_persona = None
        b64_user = None
        
        model_lower = self.config.model.lower()
        if "dall-e" not in model_lower:
            if persona_ref:
                b64_persona = self.encode_local_image_to_base64(persona_ref) if not persona_ref.startswith("http") else persona_ref
            if user_ref:
                b64_user = self.encode_local_image_to_base64(user_ref) if not user_ref.startswith("http") else user_ref
        else:
            if persona_ref or user_ref:
                logger.warning(f"⚠️ 模型 {self.config.model} 原生不支持参考图，将退化为纯文本生图。")

        # 组装 Payload
        payload = {
            "model": self.config.model,
            "prompt": prompt,
            "n": 1,
        }
        
        # 将 kwargs 里的常规参数注入 (过滤掉自定义参数)
        for k, v in kwargs.items():
            if k not in ["persona_ref", "user_ref"]:
                payload[k] = v

        # 注入参考图逻辑 (支持 Banana 等第三方网关的 ControlNet 参数)
        if b64_user:
            payload["image"] = b64_user
            logger.info("✅ 注入动态用户参考图 (作为主图/姿势/服装控制)")
            if b64_persona:
                payload["face_ref"] = b64_persona 
                logger.info("✅ 注入固定形象面部参考图 (作为脸部锚点控制)")
        elif b64_persona:
            payload["image"] = b64_persona
            logger.info("✅ 注入固定形象参考图 (作为主图控制)")

        safe_key = f"{current_key[:4]}...{current_key[-4:]}" if len(current_key) > 8 else "INVALID_KEY"
        logger.info(f"[{self.config.id}] 📡 发起请求 -> URL: {url}")
        
        payload_for_log = {k: (v[:30] + '...' if (isinstance(v, str) and v.startswith('data:image')) else v) for k, v in payload.items()}
        logger.debug(f"[{self.config.id}] 📦 Payload -> {json.dumps(payload_for_log, ensure_ascii=False)}")
        
        timeout_obj = aiohttp.ClientTimeout(total=self.config.timeout)
        
        async with self.session.post(url, json=payload, headers=headers, timeout=timeout_obj) as response:
            status = response.status
            if status != 200:
                error_text = await response.text()
                logger.error(f"[{self.config.id}] 💥 API 返回错误:\n{error_text}")
                error_msg = error_text
                try:
                    error_json = json.loads(error_text)
                    if "error" in error_json and "message" in error_json["error"]:
                        error_msg = error_json["error"]["message"]
                except: pass
                raise RuntimeError(f"HTTP {status}: {error_msg}")
            
            result = await response.json()
            
            if "data" in result and len(result["data"]) > 0:
                if "b64_json" in result["data"][0]:
                    return f"data:image/png;base64,{result['data'][0]['b64_json']}"
                if "url" in result["data"][0]:
                    img_url = result["data"][0]["url"]
                    if not img_url.startswith("http") and not img_url.startswith("data:"):
                        img_url = f"{base_url.rstrip('/v1')}/{img_url.lstrip('/')}"
                    return img_url
                    
            raise ValueError(f"API返回结构异常，未找到图片数据: {result}")
