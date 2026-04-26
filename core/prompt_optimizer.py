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

    # 🚀 新增 count 参数，返回列表
    async def optimize(self, raw_action: str, count: int = 1) -> list:
        # 如果未开启副脑，直接返回 n 个相同的词
        if not getattr(self.config, "enable_optimizer", True):
            return [raw_action] * count

        if not raw_action or raw_action.strip() == "": return [raw_action] * count

        chain = self.config.chains.get("optimizer", [])
        provider = self.config.get_provider(chain[0]) if chain else (self.config.providers[0] if self.config.providers else None)
        if not provider: return [raw_action] * count
            
        base_url = provider.base_url.rstrip("/")
        endpoint = f"{base_url}/chat/completions" if base_url.endswith("/v1") else f"{base_url}/v1/chat/completions"
        headers = {"Authorization": f"Bearer {provider.api_keys[0]}", "Content-Type": "application/json"}

        base_json_struct = """{
  "subject": {"appearance": "ultra-detailed skin texture, realistic pores...", "body_type": "...", "accessories": "..."},
  "clothing": {"top": "...", "bottom": "...", "shoes": "..."},
  "pose_and_action": {"pose": "...", "action": "[User's action expanded]", "gaze": "..."},
  "environment": {"scene": "...", "furniture": "...", "decor": "...", "items": "..."},
  "lighting": {"type": "...", "source": "...", "quality": "..."},
  "styling_and_mood": {"aesthetic": "...", "mood": "..."},
  "technical_specs": {"camera_simulation": "...", "focal_length": "...", "aperture": "...", "quality_tags": ["..."]}
}"""

        # 🚀 魔法分裂系统：根据 count 决定生成 1个 还是 JSON 数组
        if count == 1:
            sys_prompt = f"You are an expert AI image prompt engineer.\nOutput ONLY ONE valid JSON object based on the user's action.\nCRITICAL: Output ONLY valid JSON.\n{base_json_struct}"
        else:
            sys_prompt = f"You are an expert AI image prompt engineer.\nGenerate EXACTLY {count} variations of the user's action.\nCRITICAL: Output ONLY a valid JSON ARRAY `[...]` containing {count} objects.\nEnsure `subject` and `clothing` remain identical across all objects, but slightly VARY the `pose_and_action` and `environment` in each to create different angles/poses.\n[\n{base_json_struct},\n...\n]"

        payload = {
            "model": self.config.optimizer_model,
            "messages": [{"role": "system", "content": sys_prompt}, {"role": "user", "content": raw_action}],
            "max_tokens": 800 if count > 1 else 500, # 多图需更多 token
            "temperature": 0.8
        }

        async with aiohttp.ClientSession() as session:
            try:
                timeout_val = self.config.optimizer_timeout * (1.5 if count > 1 else 1.0) # 多图稍微增加超时
                logger.info(f"🧠 [副脑] 正在重构 {count} 组提示词 (模型: {self.config.optimizer_model})")
                async with session.post(endpoint, headers=headers, json=payload, timeout=timeout_val) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
                    if "choices" in data and len(data["choices"]) > 0:
                        raw_content = data["choices"][0]["message"]["content"].strip()
                        json_str = re.sub(r'^```json\s*|\s*```$', '', raw_content, flags=re.MULTILINE)
                        try:
                            prompt_data = json.loads(json_str)
                            results = []
                            # 🚀 无论大模型返回数组还是单对象，全部解析为列表
                            if isinstance(prompt_data, list):
                                for item in prompt_data:
                                    results.append(", ".join(self._flatten_json_to_tags(item)))
                            elif isinstance(prompt_data, dict):
                                results.append(", ".join(self._flatten_json_to_tags(prompt_data)))
                            
                            # 补齐防呆
                            while len(results) < count:
                                results.append(results[0] if results else raw_action)
                                
                            logger.info(f"✨ [副脑] 成功裂变 {len(results[:count])} 组神级提示词！")
                            return results[:count]
                        except Exception as e:
                            logger.warning(f"⚠️ [副脑] JSON 解析失败: {e}")
                            return [raw_action] * count
            except Exception as e:
                logger.warning(f"⚠️ [副脑降级] ({str(e)})")
                return [raw_action] * count
        return [raw_action] * count
