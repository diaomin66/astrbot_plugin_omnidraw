"""
提示词副脑优化器 (Prompt Optimizer)
"""
import json
import re
import aiohttp
import asyncio
from astrbot.api import logger
from ..models import PluginConfig

class PromptOptimizer:
    def __init__(self, config: PluginConfig):
        self.config = config

    def _flatten_json_to_tags(self, data) -> list:
        tags = []
        if isinstance(data, dict):
            for value in data.values():
                tags.extend(self._flatten_json_to_tags(value))
        elif isinstance(data, list):
            for item in data:
                tags.extend(self._flatten_json_to_tags(item))
        elif isinstance(data, str) and data.strip():
            tags.append(data.strip())
        return tags

    async def optimize(self, raw_action: str) -> str:
        if not raw_action or raw_action.strip() == "":
            return raw_action

        chain = self.config.chains.get("optimizer", [])
        provider = self.config.get_provider(chain[0]) if chain else None
        
        if not provider and self.config.providers:
            provider = self.config.providers[0]

        if not provider:
            return raw_action
            
        base_url = provider.base_url.rstrip("/")
        if base_url.endswith("/v1"):
            endpoint = f"{base_url}/chat/completions"
        else:
            endpoint = f"{base_url}/v1/chat/completions"
        
        headers = {
            "Authorization": f"Bearer {provider.api_keys[0]}",
            "Content-Type": "application/json"
        }

        sys_prompt = """You are an expert AI image prompt engineer. 
Your task is to take the user's short action description and expand it into a highly detailed, professional English prompt based on the exact JSON structure below. 
CRITICAL RULES:
1. Output ONLY a valid JSON object. No markdown formatting like ```json, no chat text.
2. ALL values must be in descriptive English keywords/phrases.
3. You must preserve and enhance extremely realistic skin textures and facial micro-details.

{
  "subject": {
    "appearance": "describe realistic face, high definition, clear facial features, ultra-detailed skin texture, realistic pores",
    "body_type": "...",
    "accessories": "..."
  },
  "clothing": {"top": "...", "bottom": "...", "shoes": "..."},
  "pose_and_action": {"pose": "...", "action": "[User's action expanded]", "gaze": "..."},
  "environment": {"scene": "...", "furniture": "...", "decor": "...", "items": "..."},
  "lighting": {"type": "...", "source": "...", "quality": "..."},
  "styling_and_mood": {"aesthetic": "...", "mood": "..."},
  "technical_specs": {
    "camera_simulation": "iPhone back camera or high-end mirrorless camera",
    "focal_length": "24mm or 50mm",
    "aperture": "f/2.0",
    "quality_tags": [
      "ultra photorealistic", "8k resolution", "RAW photo", 
      "masterpiece", "sharp focus", "Nano Banana Pro optimized", "depth of field"
    ]
  }
}"""

        payload = {
            "model": self.config.optimizer_model,
            "messages": [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": raw_action}
            ],
            "max_tokens": 500,
            "temperature": 0.7
        }

        async with aiohttp.ClientSession() as session:
            try:
                # 🚀 获取 WebUI 设定的超时时间
                timeout_val = self.config.optimizer_timeout
                logger.info(f"🧠 [副脑拦截] 正在按 JSON 结构重构提示词 (模型: {self.config.optimizer_model}, 超时: {timeout_val}s)")
                
                async with session.post(endpoint, headers=headers, json=payload, timeout=timeout_val) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
                    
                    if "choices" in data and len(data["choices"]) > 0:
                        raw_content = data["choices"][0]["message"]["content"].strip()
                        json_str = re.sub(r'^```json\s*|\s*```$', '', raw_content, flags=re.MULTILINE)
                        
                        try:
                            prompt_data = json.loads(json_str)
                            tags_list = self._flatten_json_to_tags(prompt_data)
                            optimized_prompt = ", ".join(tags_list)
                            
                            logger.info(f"✨ [副脑完成] 提示词重构成功，共 {len(tags_list)} 个特征维度。")
                            return optimized_prompt
                        except json.JSONDecodeError:
                            logger.warning(f"⚠️ [副脑降级] 未返回标准 JSON。")
                            return raw_action
                        
            except Exception as e:
                logger.warning(f"⚠️ [副脑降级] 优化接口失败或超时，向下传递原词。({str(e)})")
                return raw_action

        return raw_action
