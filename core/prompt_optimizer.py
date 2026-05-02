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

        # 核心骨架（保留原有 Key 结构，深度增强对真实光影、人体解剖、镜头物理的约束）
        base_json_struct = """{
  "subject": {
    "appearance": "flawless anatomical correctness, physically accurate human proportions, ultra-detailed skin texture, realistic pores, subtle natural micro-blemishes", 
    "body_type": "...", 
    "accessories": "..."
  },
  "clothing": {
    "top": "[specify real-world fabric textures, e.g., thick knit, worn denim, wrinkled cotton]", 
    "bottom": "...", 
    "shoes": "..."
  },
  "pose_and_action": {
    "pose": "[CRITICAL: EXACTLY ONE specific pose. NEVER use words like 'various', 'multiple', 'different angles'. Obey real-world gravity and physics]", 
    "action": "[ONE specific action]", 
    "gaze": "..."
  },
  "environment": {
    "scene": "...", 
    "furniture": "...", 
    "decor": "...", 
    "items": "..."
  },
  "lighting": {
    "type": "physically accurate lighting (e.g., volumetric sunlight, cinematic chiaroscuro, Rembrandt lighting)", 
    "source": "realistic light source direction with natural decay", 
    "quality": "realistic shadows, global illumination, bounce light"
  },
  "styling_and_mood": {
    "aesthetic": "...", 
    "mood": "..."
  },
  "technical_specs": {
    "camera_simulation": "specific real-world camera (e.g., ARRI Alexa 65, Hasselblad H6D, 35mm film)", 
    "focal_length": "exact millimeter (e.g., 85mm macro, 24mm wide)", 
    "aperture": "exact f-stop for realistic depth of field (e.g., f/1.4, f/8)", 
    "quality_tags": ["single frame", "solo", "ultra photorealistic", "8k resolution", "award-winning photography", "raw photo", "physically based rendering"]
  }
}"""

        if count == 1:
            sys_prompt = f"""You are an elite Cinematographer, Anatomist, and AI Prompt Engineer.
Output ONLY ONE valid JSON object based on the user's action.
CRITICAL RULES:
1. Output MUST be a valid JSON object.
2. ABSOLUTELY NO collages, grids, or multiple views. Describe exactly ONE single frozen moment.
3. HYPER-REALISM RULE: Ensure strict anatomical correctness, real-world physics (gravity/fabric folds), and physically accurate lighting (shadows, light bounce).
4. Do NOT use cartoonish or stylized descriptions unless explicitly requested by the user. Focus on real-world photographic precision.
{base_json_struct}"""
        else:
            sys_prompt = f"""You are an elite Cinematographer, Anatomist, and AI Prompt Engineer.
Generate EXACTLY {count} distinct variations of the user's action.
CRITICAL RULES:
1. Output MUST be a JSON object containing a "results" array: {{"results": [...]}}
2. The "results" array must contain exactly {count} objects.
3. ANTI-COLLAGE RULE: Each JSON object represents ONE SINGLE IMAGE. Pick exactly ONE specific pose and ONE camera angle per object!
4. Ensure `subject` and `clothing` remain identical across all objects, but vary the `technical_specs`, `pose`, and `environment`.
5. HYPER-REALISM RULE: Strictly enforce real-world anatomical proportions, physically accurate lighting, and authentic lens behaviors (depth of field, focal length).

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
                        
                        # 🚀 核心修复：暴力清洗 Markdown 代码块外壳 (兼容 Gemini/Claude)
                        raw_content = re.sub(r"^
http://googleusercontent.com/immersive_entry_chip/0

**改动总结：**
1. **彻底解决了 `Expecting value` 报错**：在解析 JSON 之前，加入了强大的正则过滤 `re.sub(r"^
http://googleusercontent.com/immersive_entry_chip/1
