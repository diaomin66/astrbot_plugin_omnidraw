"""
提示词副脑优化器 (Prompt Optimizer)
功能：强制 LLM 输出 JSON 格式，并扁平化为纯自然语言，专门针对“真实日常手机拍照感”进行终极优化。
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

        # 🚀 【手机日常原相机质感】核心骨架：强制要求大模型抛弃棚拍感，转而输出带有生活气息、未经修饰的日常氛围词汇
        base_json_struct = """{
  "subject_appearance": "exact age, ethnicity, everyday casual look, unretouched skin, natural pores, subtle real-world flaws, normal daily makeup, candid natural expression",
  "clothing_and_accessories": "casual everyday clothing, realistic fabric textures, messy or natural drape, no overly styled outfits",
  "pose_and_action": "CRITICAL: EXACTLY ONE specific pose. natural everyday posture, casual selfie angle, spontaneous, not overly posed",
  "environment_and_scene": "real-world everyday location, authentic daily life setting, slight background clutter, realistic unarranged environment",
  "lighting_and_mood": "natural ambient light, uneven room lighting, authentic everyday atmosphere, NO studio lights, NO cinematic lighting, flat natural lighting or direct phone flash",
  "technical_specs": "CAMERA SPECS: Shot on iPhone 15 front camera, 24mm wide angle, deep depth of field (background is clear), everything in focus, candid snap, amateur photography, unedited, raw realistic colors, NO bokeh, NO professional color grading, realistic mobile phone photo"
}"""

        if count == 1:
            sys_prompt = f"""You are an expert in authentic, amateur smartphone photography prompts for AI image generation.
Output ONLY ONE valid JSON object based on the user's action.
CRITICAL RULES:
1. Output MUST be a valid JSON object. ALL keys and values MUST be strings.
2. Escape any inner double quotes with a backslash (\\").
3. ABSOLUTELY NO collages, grids, or multiple views. Describe exactly ONE single frozen moment.
4. EVERYDAY REALISM RULE: The goal is an authentic, unedited, candid photo taken with a regular smartphone. 
5. PROHIBITED WORDS: Do NOT use professional terms like "bokeh", "cinematic lighting", "DSLR", "studio", "masterpiece", or "perfect".
OUTPUT FORMAT (Use these exact keys):
{base_json_struct}"""
        else:
            sys_prompt = f"""You are an expert in authentic, amateur smartphone photography prompts for AI image generation.
Generate EXACTLY {count} distinct variations of the user's action.
CRITICAL RULES:
1. Output MUST be a valid JSON object containing a "results" array.
2. Escape any inner double quotes with a backslash (\\").
3. ANTI-COLLAGE RULE: Each JSON object represents ONE SINGLE IMAGE. Pick exactly ONE specific pose and ONE camera angle per object!
4. EVERYDAY REALISM RULE: Focus on authentic, unedited smartphone snaps. No professional studio lighting, no extreme background blur (bokeh), no cinematic color grading.

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
                logger.info(f"🧠 [副脑] 正在重构 {count} 组【日常手机原相机质感】提示词 (模型: {self.config.optimizer_model})")
                
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
                            prompt_data = json.loads(clean_json_str)
                            if count == 1:
                                items = [prompt_data]
                            else:
                                items = prompt_data.get("results", [])
                                if not items and isinstance(prompt_data, list):
                                    items = prompt_data
                        except Exception as e:
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

                        # 🚀 降维打击：将日常质感碎片拼接为平铺的自然语言 Tag 流
                        results = []
                        anti_collage = "1girl, solo, single image, one single frame, NO grid, NO collage, NO split screen"
                        
                        for item in items:
                            if isinstance(item, dict):
                                parts = []
                                for k in ["subject_appearance", "clothing_and_accessories", "pose_and_action", "environment_and_scene", "lighting_and_mood", "technical_specs"]:
                                    val = item.get(k, "")
                                    if val and isinstance(val, str):
                                        parts.append(val.strip())
                                        
                                # 融合成充满生活气息的提示词
                                master_prompt = f"{anti_collage}, " + ", ".join(parts)
                                master_prompt = re.sub(r'\s+', ' ', master_prompt)
                                results.append(master_prompt)
                            
                        while len(results) < count:
                            results.append(results[0] if results else raw_action)
                            
                        logger.info(f"✨ [副脑] 成功提取并转化 {len(results[:count])} 组【日常原相机质感】提示词！")
                        return results[:count]
                        
            except Exception as e:
                logger.warning(f"⚠️ [副脑降级] ({str(e)})")
                return [raw_action] * count
                
        return [raw_action] * count
