"""
提示词副脑优化器 (Prompt Optimizer)
功能：拦截简短动作，强制 LLM 输出超高维度的 JSON 结构，并将其展平为顶级英文提示词。
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
        """递归遍历 JSON，把所有的字符串值提取成列表"""
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
        """核心优化函数：将简单的动作指令重写为结构化的神级提示词"""
        if not raw_action or raw_action.strip() == "":
            return raw_action

        # 🚀 动态获取你在 WebUI 设定的链路节点
        chain = self.config.chains.get("optimizer", [])
        provider = self.config.get_provider(chain[0]) if chain else None
        
        # 兜底：如果填错节点，就用第一个生图节点
        if not provider and self.config.providers:
            provider = self.config.providers[0]

        if not provider:
            return raw_action
            
        base_url = provider.base_url.rstrip("/")
        endpoint = f"{base_url}/v1/chat/completions"
        
        headers = {
            "Authorization": f"Bearer {provider.api_keys[0]}",
            "Content-Type": "application/json"
        }

        # 👑 顶级魔法预设：强制英文 JSON 输出，锁定皮肤细节与 Nano Banana Pro 标准
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
            "model": self.config.optimizer_model, # 🚀 动态读取你在 WebUI 设定的模型！
            "messages": [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": raw_action}
            ],
            "max_tokens": 500,
            "temperature": 0.7
        }

        async with aiohttp.ClientSession() as session:
            try:
                logger.info(f"🧠 [副脑拦截] 正在按 JSON 结构重构提示词: {raw_action} (模型: {self.config.optimizer_model})")
                # 超时稍微放宽到 8 秒，因为输出完整的 JSON 需要稍微多一点 token
                async with session.post(endpoint, headers=headers, json=payload, timeout=8.0) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
                    
                    if "choices" in data and len(data["choices"]) > 0:
                        raw_content = data["choices"][0]["message"]["content"].strip()
                        
                        # 强力剥离可能的 Markdown 代码块
                        json_str = re.sub(r'^```json\s*|\s*```$', '', raw_content, flags=re.MULTILINE)
                        
                        try:
                            # 1. 解析 JSON
                            prompt_data = json.loads(json_str)
                            # 2. 将高维 JSON 打平为逗号分隔的纯英文 Prompt
                            tags_list = self._flatten_json_to_tags(prompt_data)
                            optimized_prompt = ", ".join(tags_list)
                            
                            logger.info(f"✨ [副脑完成] 提示词重构成功，共 {len(tags_list)} 个特征维度。")
                            return optimized_prompt
                        except json.JSONDecodeError:
                            logger.warning(f"⚠️ [副脑降级] 大模型未返回标准 JSON，提取失败。原样返回。内容: {raw_content[:50]}...")
                            return raw_action
                        
            except Exception as e:
                logger.warning(f"⚠️ [副脑降级] 优化接口失败或超时，向下传递原词。({str(e)})")
                return raw_action

        return raw_action
