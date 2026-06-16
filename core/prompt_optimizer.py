"""提示词副脑优化器。"""
import json
import re
import aiohttp
import asyncio
from typing import Optional
from astrbot.api import logger
from ..models import PluginConfig
from ..providers.base import build_chat_completions_endpoint, next_api_key

class PromptOptimizer:
    def __init__(self, config: PluginConfig):
        self.config = config

    async def optimize(self, raw_action: str, count: int = 1, session: Optional[aiohttp.ClientSession] = None) -> list:
        if not getattr(self.config, "enable_optimizer", True):
            return [raw_action] * count

        if not raw_action or raw_action.strip() == "": return [raw_action] * count

        chain = self.config.chains.get("optimizer", [])
        provider = self.config.get_provider(chain[0]) if chain else (self.config.providers[0] if self.config.providers else None)
        if not provider or not provider.base_url:
            return [raw_action] * count

        endpoint = build_chat_completions_endpoint(provider.base_url)
        api_key = next_api_key(provider.id, provider.api_keys)
        if not endpoint or not api_key:
            return [raw_action] * count
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

        # ==========================================
        # 🚀 动态风格插槽系统 (Dynamic Style Engine)
        # ==========================================
        style_choice = getattr(self.config, "optimizer_style", "手机日常原生感")
        custom_prompt = getattr(self.config, "optimizer_custom_prompt", "").strip()
        custom_style_hint = custom_prompt
        if custom_prompt and re.search(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]", custom_prompt):
            custom_style_hint = "the custom visual style described by the user, translated into natural English"

        universal_quality_guardrails = (
            "single coherent image, physically plausible perspective, natural proportions, believable camera distance, "
            "realistic hands and fingers, no extra limbs, no warped joints, no broken anatomy, no duplicated face, "
            "no doll-like symmetry, no waxy skin, no plastic skin, no excessive skin roughness, no excessive smoothing, "
            "no greasy shine, no metallic reflections on skin, no over-sharpened pores, no HDR look, no surreal artifacts"
        )

        # 五大黄金预设矩阵
        STYLE_PRESETS = {
            "手机日常原生感": {
                "role": "a senior prompt editor for authentic everyday smartphone photography",
                "subject": "ordinary real person or subject with believable proportions, relaxed candid expression, natural skin with balanced micro-texture, subtle pores only where appropriate, no beauty-retouch look, no exaggerated flaws",
                "clothing": "everyday clothing with believable fabric weight, natural wrinkles, normal fit, practical styling, no fashion editorial exaggeration",
                "environment": "specific everyday real-world place, lived-in but not messy, small natural background details, realistic object scale and depth",
                "lighting": "available ambient light from windows, ceiling lights, street lights, or phone flash only when appropriate, soft imperfect shadows, no studio setup, no glossy HDR highlights",
                "camera": "casual smartphone photo, natural colors, mild sensor noise, deep depth of field, normal autofocus, slight hand-held imperfection, no cinematic grading, no artificial bokeh",
                "quality": "keep the scene casual and unposed, avoid showroom perfection, avoid over-clean backgrounds, keep surfaces and skin matte to naturally satin, never oily or reflective"
            },
            "自拍专用极致真实": {
                "role": "an expert mobile selfie realism editor, portrait retoucher, and human anatomy quality controller",
                "subject": "natural everyday human selfie, believable age and facial structure, preserved identity, normal facial asymmetry, relaxed candid micro-expression, clear natural eyes, healthy matte-to-satin skin, balanced fine skin texture, very subtle pores, no waxy smoothness, no gritty rough pores, no oily shine, no wet glossy skin, no plastic beauty filter",
                "clothing": "casual daily outfit that fits the body naturally, realistic collar and shoulder structure, believable fabric folds, no floating fabric, no impossible neckline, no overly styled costume unless requested",
                "environment": "ordinary daily-life background such as bedroom, bathroom mirror, elevator, hallway, cafe, street, office, campus, car interior, or home corner, real object scale, mild background clutter, not a studio set",
                "lighting": "real available light from a window, ceiling lamp, screen glow, street light, or soft phone flash, gentle uneven illumination, realistic catchlights, natural shadows under nose and chin, no beauty dish, no glossy specular skin, no overexposure",
                "camera": "front-facing smartphone selfie, natural arm-length framing, believable shoulder and neck geometry, slight wide-angle perspective without face distortion, normal crop from chest or shoulders, deep depth of field, unedited phone color, mild sensor noise, no professional retouching",
                "quality": "strict anatomy guardrails: one head, one torso, two arms when visible, natural hand size, plausible fingers, no twisted wrists, no elongated arm, no broken shoulder, no extra teeth, no crossed eyes, no melted ears, no warped jaw, no uncanny symmetry, keep the selfie angle comfortable and physically possible"
            },
            "电影级光影大片": {
                "role": "an elite cinematographer and high-end photographic prompt engineer",
                "subject": "realistic subject with expressive but believable emotion, refined details, natural anatomy, cinematic presence without fantasy deformation",
                "clothing": "intentional styling with accurate fabric material, weight, seams, wrinkles, and gravity-aware drape",
                "environment": "specific cinematic real-world location with layered background depth, purposeful set details, atmospheric haze only when natural",
                "lighting": "controlled cinematic lighting such as soft side light, motivated practical light, rim light, or warm sunset light, realistic shadow falloff, no overdone neon glow",
                "camera": "professional photography or cinema still, accurate lens choice, controlled depth of field, refined color grade, high dynamic range without HDR artifacts",
                "quality": "cinematic but physically grounded, no fantasy anatomy, no excessive bloom, no overly polished AI texture"
            },
            "日系插画大师": {
                "role": "a master anime illustrator and visual novel background artist",
                "subject": "high-quality anime character or subject, clean silhouette, expressive eyes, delicate but consistent features, readable emotion, no malformed hands",
                "clothing": "detailed anime outfit with clear material logic, controlled folds, tasteful color accents, no cluttered unreadable details",
                "environment": "beautiful Japanese illustration background, atmospheric but coherent scenery, believable perspective, detailed sky and architecture when relevant",
                "lighting": "soft anime lighting, gentle rim light, transparent shadows, vivid but controlled color palette, no blown highlights",
                "camera": "polished 2D illustration, clean linework, refined cel shading, high resolution, balanced composition",
                "quality": "avoid extra fingers, duplicated limbs, inconsistent eye direction, broken perspective, messy line artifacts"
            },
            "3D 潮玩盲盒": {
                "role": "an expert 3D character modeler and product photography prompt engineer",
                "subject": "cute collectible blind-box figure, chibi proportions, appealing face, clean sculpt, consistent toy anatomy, smooth resin or vinyl material",
                "clothing": "stylized outfit with readable toy-scale details, neat seams, small accessories, coherent color design",
                "environment": "minimal product photography setup, clean backdrop, simple display surface, no distracting clutter",
                "lighting": "soft studio lighting, gentle rim light, realistic ambient occlusion, controlled highlights on resin, no harsh mirror reflections",
                "camera": "3D product render, macro product photography angle, sharp focus, clean composition, high-quality material rendering",
                "quality": "avoid melted toy parts, asymmetrical accidental defects, unreadable accessories, over-glossy plastic glare"
            }
        }

        # 动态组装
        if style_choice == "自定义模式" and custom_prompt:
            style_data = {
                "role": f"an AI prompt expert specializing in this exact style: {custom_style_hint}",
                "subject": f"[{custom_style_hint}] Focus on character appearance, facial details, and matching this style exactly",
                "clothing": f"[{custom_style_hint}] Appropriate clothing, textures, and details matching the custom style",
                "environment": f"[{custom_style_hint}] Background and setting matching the custom style",
                "lighting": f"[{custom_style_hint}] Lighting and mood matching the custom style",
                "camera": f"[{custom_style_hint}] Rendering style, camera specs, or art medium matching the custom style",
                "quality": f"[{custom_style_hint}] Keep the result coherent, physically plausible, cleanly composed, and free from common AI artifacts"
            }
        else:
            style_data = STYLE_PRESETS.get(style_choice, STYLE_PRESETS["手机日常原生感"])

        base_json_struct = f"""{{
  "subject_appearance": "{style_data['subject']}",
  "clothing_and_accessories": "{style_data['clothing']}",
  "pose_and_action": "CRITICAL: Translate the user request into English. Describe EXACTLY ONE specific pose or action. NEVER use words like various or multiple. Ensure natural interaction and physically possible body mechanics.",
  "environment_and_scene": "{style_data['environment']}",
  "lighting_and_mood": "{style_data['lighting']}",
  "technical_specs": "{style_data['camera']}",
  "realism_and_quality_guardrails": "{style_data['quality']}; {universal_quality_guardrails}"
}}"""

        if count == 1:
            sys_prompt = f"""You are {style_data['role']}.
Output ONLY ONE valid JSON object based on the user's action.
CRITICAL RULES:
1. Output MUST be a valid JSON object. ALL keys and values MUST be strings.
2. Escape any inner double quotes with a backslash (\\").
3. ALL output values MUST be written in fluent natural English. Translate any Chinese, Japanese, Korean, or mixed-language user input into English. Do not copy non-English text into the JSON.
4. ABSOLUTELY NO collages, grids, or multiple views. Describe exactly ONE single frozen moment.
5. STYLE ADHERENCE: Strictly follow the aesthetics, materials, lighting, anatomy, skin, and realism guardrails described in the output format.
6. Prefer concrete visual nouns and camera-language over abstract adjectives. Keep the prompt useful for an image model.
OUTPUT FORMAT (Use these exact keys):
{base_json_struct}"""
        else:
            sys_prompt = f"""You are {style_data['role']}.
Generate EXACTLY {count} distinct variations of the user's action.
CRITICAL RULES:
1. Output MUST be a valid JSON object containing a "results" array.
2. Escape any inner double quotes with a backslash (\\").
3. ALL output values MUST be written in fluent natural English. Translate any Chinese, Japanese, Korean, or mixed-language user input into English. Do not copy non-English text into the JSON.
4. ANTI-COLLAGE RULE: Each JSON object represents ONE SINGLE IMAGE. Pick exactly ONE specific pose and ONE camera angle per object.
5. STYLE ADHERENCE: Strictly follow the aesthetics, materials, lighting, anatomy, skin, and realism guardrails described in the output format.
6. Each variation must be visually distinct while remaining natural and physically plausible.

OUTPUT FORMAT:
{{
  "results": [
    {base_json_struct},
    ... (repeat {count} times)
  ]
}}"""

        payload = {
            "model": self.config.optimizer_model or provider.model,
            "messages": [{"role": "system", "content": sys_prompt}, {"role": "user", "content": raw_action}],
            "max_tokens": 4000 if count > 1 else 2500,
            "temperature": 0.8,
            "response_format": {"type": "json_object"}
        }

        session_obj = session
        close_session = False
        if session_obj is None:
            session_obj = aiohttp.ClientSession()
            close_session = True

        try:
            try:
                timeout_val = self.config.optimizer_timeout * (1.5 if count > 1 else 1.0)
                logger.info(f"🧠 [副脑] 正在以【{style_choice}】风格重构提示词 (模型: {self.config.optimizer_model})")

                async with session_obj.post(endpoint, headers=headers, json=payload, timeout=timeout_val) as resp:
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
                            keys = ["subject_appearance", "clothing_and_accessories", "pose_and_action", "environment_and_scene", "lighting_and_mood", "technical_specs", "realism_and_quality_guardrails"]

                            search_text = raw_content
                            for key in keys:
                                idx = search_text.find(f'"{key}"')
                                if idx == -1:
                                    continue
                                colon_idx = search_text.find(':', idx)
                                if colon_idx == -1:
                                    continue
                                quote_idx = search_text.find('"', colon_idx)
                                if quote_idx == -1:
                                    continue

                                next_key_idx = len(search_text)
                                for k in keys:
                                    if k == key:
                                        continue
                                    k_idx = search_text.find(f'"{k}"', quote_idx)
                                    if k_idx != -1 and k_idx < next_key_idx:
                                        next_key_idx = k_idx

                                raw_val = search_text[quote_idx + 1:next_key_idx]
                                raw_val = raw_val.strip().rstrip('}').rstrip(']').rstrip(',').strip().rstrip('"')
                                raw_val = raw_val.replace('"', "'").replace('\n', ' ')
                                if raw_val:
                                    fallback_item[key] = raw_val

                            if fallback_item:
                                items = [fallback_item]
                                logger.info(f"🚑 [副脑] 抢救成功！已强行提取 {len(fallback_item)} 个字段。")
                            else:
                                raise ValueError("抢救模式未能提取到任何有效字段")

                        results = []
                        anti_collage = "single image, one natural coherent frame, no grid, no collage, no split screen, no multiple views"

                        for item in items:
                            if isinstance(item, dict):
                                parts = []
                                for k in ["subject_appearance", "clothing_and_accessories", "pose_and_action", "environment_and_scene", "lighting_and_mood", "technical_specs", "realism_and_quality_guardrails"]:
                                    val = item.get(k, "")
                                    if val and isinstance(val, str):
                                        parts.append(val.strip())

                                master_prompt = f"{anti_collage}, " + ", ".join(parts)
                                master_prompt = re.sub(r'\s+', ' ', master_prompt)
                                results.append(master_prompt)

                        while len(results) < count:
                            results.append(results[0] if results else raw_action)

                        logger.info(f"✨ [副脑] 成功重构并提取 {len(results[:count])} 组【{style_choice}】提示词！")
                        return results[:count]

            except Exception as e:
                logger.warning(f"⚠️ [副脑降级] ({str(e)})")
                return [raw_action] * count

            return [raw_action] * count
        finally:
            if close_session and session_obj is not None:
                await session_obj.close()
