"""
提示词副脑优化器 (Prompt Optimizer)
功能：拦截简短动作，强制 LLM 输出超高维度的 JSON 结构，支持批量裂变并严格防拼图。
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
            for value in data.values(): tags.extend(self._flatten_json_to_tags(value))
        elif isinstance(data, list):
            for item in data: tags.extend(self._flatten_json_to_tags(item))
        elif isinstance(data, str) and data.strip(): tags.append(data.strip())
        return tags

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

        # 🚀 优化点 1：在基础结构里，明确标注姿势只能是"唯一的"
        base_json_struct = """{
  "subject": {"appearance": "ultra-detailed skin texture, realistic pores", "body_type": "...", "accessories": "..."},
  "clothing": {"top": "...", "bottom": "...", "shoes": "..."},
  "pose_and_action": {
    "pose": "[CRITICAL: Describe EXACTLY ONE specific pose here. DO NOT list multiple poses!]", 
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

        # 🚀 优化点 2：加入严厉的 Anti-Collage (防拼图) 约束规则
        if count == 1:
            sys_prompt = f"""You are an expert AI image prompt engineer.
Output ONLY ONE valid JSON object based on the user's action.
CRITICAL RULES:
1. Output ONLY valid JSON.
2. ABSOLUTELY NO collages, grids, or multiple views. Describe exactly ONE single frozen moment.
{base_json_struct}"""
        else:
            sys_prompt = f"""You are an expert AI image prompt engineer.
Generate EXACTLY {count} distinct variations of the user's action as a JSON ARRAY `[...]`.

CRITICAL RULES:
1. Output ONLY a valid JSON ARRAY containing {count} objects.
2. ANTI-COLLAGE RULE: Each JSON object represents ONE SINGLE IMAGE. Do NOT list multiple poses inside one object (e.g., NEVER write "standing, sitting, kneeling"). Pick exactly ONE specific pose, ONE action, and ONE camera angle per object!
3. Ensure `subject` and `clothing` remain identical across all objects.
4. Provide ONE distinct `pose_and_action` and ONE distinct `environment` per object so that each object generates a completely different, single-frame picture.

Format:
[
{base_json_struct},
... (repeat {count} times)
]"""

        payload = {
            "model": self.config.optimizer_model,
            "messages": [{"role": "system", "content": sys_prompt}, {"role": "user", "content": raw_action}],
            "max_tokens": 1000 if count > 1 else 500, # 给足够多的 token 以免截断
            "temperature": 0.8
        }

        async with aiohttp.ClientSession() as session:
            try:
                timeout_val = self.config.optimizer_timeout * (1.5 if count > 1 else 1.0)
                logger.info(f"🧠 [副脑] 正在重构 {count} 组独立提示词 (防拼图模式, 模型: {self.config.optimizer_model})")
                async with session.post(endpoint, headers=headers, json=payload, timeout=timeout_val) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
                    if "choices" in data and len(data["choices"]) > 0:
                        raw_content = data["choices"][0]["message"]["content"].strip()
                        json_str = re.sub(r'^```json\s*|\s*```$', '', raw_content, flags=re.MULTILINE)
                        try:
                            prompt_data = json.loads(json_str)
                            results = []
                            
                            if isinstance(prompt_data, list):
                                for item in prompt_data:
                                    results.append(", ".join(self._flatten_json_to_tags(item)))
                            elif isinstance(prompt_data, dict):
                                results.append(", ".join(self._flatten_json_to_tags(prompt_data)))
                            
                            while len(results) < count:
                                results.append(results[0] if results else raw_action)
                                
                            logger.info(f"✨ [副脑] 成功裂变 {len(results[:count])} 组神级单图提示词！")
                            return results[:count]
                        except Exception as e:
                            logger.warning(f"⚠️ [副脑] JSON 解析失败: {e}")
                            return [raw_action] * count
            except Exception as e:
                logger.warning(f"⚠️ [副脑降级] ({str(e)})")
                return [raw_action] * count
        return [raw_action] * count
