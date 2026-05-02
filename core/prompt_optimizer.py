"""
提示词副脑优化器 (Prompt Optimizer)
功能：强制 LLM 输出 JSON 格式，并物理级写死“防拼图”特征，确保百分百单图输出。
带有无敌抢救模式，无视一切 JSON 语法错误与截断。
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

        # 核心扁平化骨架
        base_json_struct = """{
  "subject_appearance": "flawless anatomical correctness, physically accurate human proportions, ultra-detailed skin texture, realistic pores",
  "clothing_and_accessories": "specify real-world fabric textures like thick knit, worn denim",
  "pose_and_action": "CRITICAL: EXACTLY ONE specific pose. NEVER use words like various or multiple. Obey real-world gravity.",
  "environment_and_scene": "describe the specific location, atmosphere, and props",
  "lighting_and_mood": "physically accurate lighting like volumetric sunlight, cinematic chiaroscuro, realistic shadows",
  "technical_specs": "specific real-world camera like ARRI Alexa 65, focal length, aperture, single frame, solo, ultra photorealistic, raw photo"
}"""

        if count == 1:
            sys_prompt = f"""You are an elite Cinematographer, Anatomist, and AI Prompt Engineer.
Output ONLY ONE valid JSON object based on the user's action.
CRITICAL RULES:
1. Output MUST be a valid JSON object. ALL keys and values MUST be strings.
2. Escape any inner double quotes with a backslash (\\"). Do NOT use unescaped quotes inside strings.
3. ABSOLUTELY NO collages, grids, or multiple views. Describe exactly ONE single frozen moment.
4. HYPER-REALISM RULE: Ensure strict anatomical correctness, real-world physics, and physically accurate lighting.
OUTPUT FORMAT (Use these exact keys):
{base_json_struct}"""
        else:
            sys_prompt = f"""You are an elite Cinematographer, Anatomist, and AI Prompt Engineer.
Generate EXACTLY {count} distinct variations of the user's action.
CRITICAL RULES:
1. Output MUST be a valid JSON object containing a "results" array.
2. Escape any inner double quotes with a backslash (\\"). 
3. ANTI-COLLAGE RULE: Each JSON object represents ONE SINGLE IMAGE. Pick exactly ONE specific pose and ONE camera angle per object!

OUTPUT FORMAT:
{{
  "results": [
    {base_json_struct},
    ... (repeat {count} times)
  ]
}}"""

        payload = {
            "model": self.config.optimizer_model,
            "messages": [{"role": "system", "content": sys_prompt}, {"role": "user", "content": raw_action}],
            "max_tokens": 4000 if count > 1 else 2500, 
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
                        
                        start_idx = raw_content.find('{')
                        end_idx = raw_content.rfind('}')
                        clean_json_str = raw_content[start_idx:end_idx+1] if (start_idx != -1 and end_idx != -1 and end_idx >= start_idx) else raw_content
                            
                        clean_json_str = clean_json_str.replace('\n', ' ').replace('\r', '')
                        clean_json_str = re.sub(r',\s*}', '}', clean_json_str)
                        clean_json_str = re.sub(r',\s*]', ']', clean_json_str)
                        
                        items = []
                        try:
                            # 正常解析尝试
                            prompt_data = json.loads(clean_json_str)
                            if count == 1:
                                items = [prompt_data]
                            else:
                                items = prompt_data.get("results", [])
                                if not items and isinstance(prompt_data, list):
                                    items = prompt_data
                        except Exception as e:
                            # 🚀 无敌抢救模式
                            logger.warning(f"⚠️ [副脑] 原生 JSON 解析失败, 启动无敌抢救模式... 错误: {e}")
                            fallback_item = {}
                            keys = ["subject_appearance", "clothing_and_accessories", "pose_and_action", "environment_and_scene", "lighting_and_mood", "technical_specs"]
                            
                            search_text = raw_content
                            for key in keys:
                                idx = search_text.find(f'"{key}"')
                                if idx == -1: continue
                                colon_idx = search_text.find(':', idx)
                                if colon_idx == -1: continue
                                quote_idx = search_text.find('"', colon_idx)
                                if quote_idx == -1: continue
                                
                                next_key_idx = len(search_text)
                                for k in keys:
                                    if k == key: continue
                                    k_idx = search_text.find(f'"{k}"', quote_idx)
                                    if k_idx != -1 and k_idx < next_key_idx:
                                        next_key_idx = k_idx
                                        
                                raw_val = search_text[quote_idx+1:next_key_idx]
                                raw_val = raw_val.strip().rstrip('}').rstrip(']').rstrip(',').strip().rstrip('"')
                                raw_val = raw_val.replace('"', "'").replace('\n', ' ')
                                if raw_val:
                                    fallback_item[key] = raw_val
                            
                            if fallback_item:
                                items = [fallback_item]
                                logger.info(f"🚑 [副脑] 抢救成功！已强行提取 {len(fallback_item)} 个字段。")
                            else:
                                raise ValueError("抢救模式未能提取到任何有效字段")

                        # 后期处理：拼接防拼图咒语
                        results = []
                        for item in items:
                            if isinstance(item, dict):
                                item["HARDCODED_ANTI_COLLAGE_RULE"] = (
                                    "1girl, solo, single image, one single frame, complete and unified scene, "
                                    "NO grid, NO collage, NO split screen, NO character sheet, NO multiple views, NO comic panels"
                                )
                                results.append(json.dumps(item, ensure_ascii=False, indent=2))
                            
                        while len(results) < count:
                            results.append(results[0] if results else raw_action)
                            
                        logger.info(f"✨ [副脑] 成功提取 {len(results[:count])} 组防拼图 JSON！")
                        return results[:count]
                        
            except Exception as e:
                logger.warning(f"⚠️ [副脑降级] ({str(e)})")
                return [raw_action] * count
                
        return [raw_action] * count
