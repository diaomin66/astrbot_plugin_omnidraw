"""
提示词副脑优化器 (Prompt Optimizer)
功能：强制 LLM 输出 JSON 格式，并物理级写死“防拼图”特征，确保百分百单图输出。
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

    @staticmethod
    def flatten_json_prompt(json_str: str) -> str:
        try:
            data = json.loads(json_str)
            if not isinstance(data, dict):
                return json_str
        except (json.JSONDecodeError, TypeError):
            return json_str

        parts = []

        if "subject" in data:
            subject = data["subject"]
            if isinstance(subject, dict):
                for key in ["appearance", "body_type", "accessories"]:
                    val = subject.get(key, "")
                    if val and val != "none": parts.append(val)

        if "clothing" in data:
            clothing = data["clothing"]
            if isinstance(clothing, dict):
                for key in ["top", "bottom", "shoes"]:
                    val = clothing.get(key, "")
                    if val and val != "none": parts.append(val)

        if "pose_and_action" in data:
            pose_data = data["pose_and_action"]
            if isinstance(pose_data, dict):
                for key in ["pose", "action", "gaze"]:
                    val = pose_data.get(key, "")
                    if val: parts.append(val)

        if "environment" in data:
            env = data["environment"]
            if isinstance(env, dict):
                for key in ["scene", "furniture", "decor", "items"]:
                    val = env.get(key, "")
                    if val: parts.append(val)

        if "lighting" in data:
            lighting = data["lighting"]
            if isinstance(lighting, dict):
                for key in ["type", "source", "quality"]:
                    val = lighting.get(key, "")
                    if val: parts.append(val)

        if "styling_and_mood" in data:
            style = data["styling_and_mood"]
            if isinstance(style, dict):
                aesthetic = style.get("aesthetic", "")
                mood = style.get("mood", "")
                if aesthetic: parts.append(aesthetic)
                if mood: parts.append(mood)

        if "technical_specs" in data:
            specs = data["technical_specs"]
            if isinstance(specs, dict):
                for key in ["camera_simulation", "focal_length", "aperture"]:
                    val = specs.get(key, "")
                    if val: parts.append(val)
                quality_tags = specs.get("quality_tags", [])
                if isinstance(quality_tags, list):
                    for tag in quality_tags:
                        if tag: parts.append(tag)

        anti_rule = data.get("HARDCODED_ANTI_COLLAGE_RULE", "")
        if anti_rule:
            parts.append(anti_rule)

        if parts:
            return ", ".join(parts)
        return json_str

    async def optimize(self, raw_action: str, count: int = 1) -> list:
        if not getattr(self.config, "enable_optimizer", True):
            return [raw_action] * count

        if not raw_action or raw_action.strip() == "": return [raw_action] * count

        chain = self.config.chains.get("optimizer", [])
        provider = self.config.get_provider(chain[0]) if chain else (self.config.providers[0] if self.config.providers else None)
        if not provider: return [raw_action] * count
            
        base_url = provider.base_url.rstrip("/")
        endpoint = f"{base_url}/chat/completions" if base_url.endswith("/v1") else f"{base_url}/v1/chat/completions"
        headers = {"Authorization": f"Bearer {provider.api_keys[0]}", "Content-Type": "application/json"}

        # 核心骨架（特别警告不准用多视图词汇）
        base_json_struct = """{
  "subject": {"appearance": "ultra-detailed skin texture, realistic pores", "body_type": "...", "accessories": "..."},
  "clothing": {"top": "...", "bottom": "...", "shoes": "..."},
  "pose_and_action": {
    "pose": "[CRITICAL: EXACTLY ONE specific pose. NEVER use words like 'various', 'multiple', 'different angles']", 
    "action": "[ONE specific action]", 
    "gaze": "..."
  },
  "environment": {"scene": "...", "furniture": "...", "decor": "...", "items": "..."},
  "lighting": {"type": "...", "source": "...", "quality": "..."},
  "styling_and_mood": {"aesthetic": "...", "mood": "..."},
  "technical_specs": {
    "camera_simulation": "...", 
    "focal_length": "...", 
    "aperture": "...", 
    "quality_tags": ["single frame", "solo", "ultra photorealistic", "8k resolution"]
  }
}"""

        if count == 1:
            sys_prompt = f"""You are an expert AI image prompt engineer.
Output ONLY ONE valid JSON object based on the user's action.
CRITICAL RULES:
1. Output MUST be a valid JSON object.
2. ABSOLUTELY NO collages, grids, or multiple views. Describe exactly ONE single frozen moment.
{base_json_struct}"""
        else:
            sys_prompt = f"""You are an expert AI image prompt engineer.
Generate EXACTLY {count} distinct variations of the user's action.
CRITICAL RULES:
1. Output MUST be a JSON object containing a "results" array: {{"results": [...]}}
2. The "results" array must contain exactly {count} objects.
3. ANTI-COLLAGE RULE: Each JSON object represents ONE SINGLE IMAGE. Pick exactly ONE specific pose and ONE camera angle per object!
4. Ensure `subject` and `clothing` remain identical across all objects.

Format:
{{
  "results": [
    {base_json_struct},
    ... (repeat {count} times)
  ]
}}"""

        payload = {
            "model": self.config.optimizer_model,
            "messages": [{"role": "system", "content": sys_prompt}, {"role": "user", "content": raw_action}],
            "max_tokens": 1200 if count > 1 else 600, 
            "temperature": 0.8,
            "response_format": {"type": "json_object"} 
        }

        async with aiohttp.ClientSession() as session:
            try:
                timeout_val = self.config.optimizer_timeout * (1.5 if count > 1 else 1.0)
                logger.info(f"🧠 [副脑] 正在重构 {count} 组独立提示词 (双重防拼图模式, 模型: {self.config.optimizer_model})")
                
                async with session.post(endpoint, headers=headers, json=payload, timeout=timeout_val) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
                    
                    if "choices" in data and len(data["choices"]) > 0:
                        raw_content = data["choices"][0]["message"]["content"].strip()
                        
                        try:
                            prompt_data = json.loads(raw_content)
                            results = []
                            
                            items = []
                            if count == 1:
                                items = [prompt_data]
                            else:
                                items = prompt_data.get("results", [])
                                if not items and isinstance(prompt_data, list):
                                    items = prompt_data
                                    
                            for item in items:
                                # 🚀【终极防拼图锁死】🚀
                                # 不管大模型写了什么，Python 代码强行在最后塞入一个极其严厉的“防拼图强制标签”
                                # 底层生图模型看到这些词，会立刻打消生成拼图的念头！
                                item["HARDCODED_ANTI_COLLAGE_RULE"] = "1girl, solo, single image, one single frame, complete and unified scene, NO grid, NO collage, NO split screen, NO character sheet, NO multiple views, NO comic panels"
                                
                                json_str = json.dumps(item, ensure_ascii=False, indent=2)
                                results.append(json_str)
                            
                            while len(results) < count:
                                results.append(results[0] if results else raw_action)
                                
                            logger.info(f"✨ [副脑] 成功提取 {len(results[:count])} 组防拼图 JSON！")
                            return results[:count]
                            
                        except Exception as e:
                            logger.warning(f"⚠️ [副脑] 原生 JSON 解析提取失败: {e}")
                            return [raw_action] * count
            except Exception as e:
                logger.warning(f"⚠️ [副脑降级] ({str(e)})")
                return [raw_action] * count
                
        return [raw_action] * count
