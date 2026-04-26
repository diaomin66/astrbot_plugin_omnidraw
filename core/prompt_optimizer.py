"""
提示词副脑优化器 (Prompt Optimizer)
功能：强制 LLM 开启 JSON 模式，输出高维度的 JSON 结构，并原汁原味地传递给底层画图 API。
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

        # 核心骨架
        base_json_struct = """{
  "subject": {"appearance": "ultra-detailed skin texture, realistic pores", "body_type": "...", "accessories": "..."},
  "clothing": {"top": "...", "bottom": "...", "shoes": "..."},
  "pose_and_action": {
    "pose": "[CRITICAL: EXACTLY ONE specific pose. NO multiple poses!]", 
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
            # 批量模式：为了符合官方 json_object 要求，必须包裹在一个对象的 key 里
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

        # 🚀 强开官方 JSON 模式 (response_format)
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
                logger.info(f"🧠 [副脑] 正在重构 {count} 组独立提示词 (强制纯 JSON 模式, 模型: {self.config.optimizer_model})")
                
                async with session.post(endpoint, headers=headers, json=payload, timeout=timeout_val) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
                    
                    if "choices" in data and len(data["choices"]) > 0:
                        raw_content = data["choices"][0]["message"]["content"].strip()
                        
                        try:
                            # 提取 JSON 对象
                            prompt_data = json.loads(raw_content)
                            results = []
                            
                            if count == 1:
                                # 单张图，直接将 JSON 对象转回优雅的字符串保留结构
                                json_str = json.dumps(prompt_data, ensure_ascii=False, indent=2)
                                results.append(json_str)
                            else:
                                # 多张图，从 results 数组中提取每个对象，并保持 JSON 格式
                                items = prompt_data.get("results", [])
                                if not items and isinstance(prompt_data, list):
                                    items = prompt_data # 极少数模型叛逆兜底
                                    
                                for item in items:
                                    json_str = json.dumps(item, ensure_ascii=False, indent=2)
                                    results.append(json_str)
                            
                            # 补齐防呆
                            while len(results) < count:
                                results.append(results[0] if results else raw_action)
                                
                            logger.info(f"✨ [副脑] 成功提取 {len(results[:count])} 组原生 JSON 提示词！")
                            return results[:count]
                            
                        except Exception as e:
                            logger.warning(f"⚠️ [副脑] 原生 JSON 解析提取失败: {e}")
                            return [raw_action] * count
            except Exception as e:
                logger.warning(f"⚠️ [副脑降级] ({str(e)})")
                return [raw_action] * count
                
        return [raw_action] * count
