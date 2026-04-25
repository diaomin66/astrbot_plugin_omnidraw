"""
AstrBot 万象画卷插件 v1.7.0
功能描述：人设库管理与人设 Prompt 构造服务 (智能匹配全局图库)
"""

from typing import Tuple, Dict, Any, Optional
import os
from astrbot.api import logger
from ..models import PluginConfig, PersonaConfig

class PersonaManager:
    def __init__(self, config: PluginConfig):
        self.config = config

    def get_persona(self, name: str) -> Optional[PersonaConfig]:
        for p in self.config.personas:
            if p.name == name:
                return p
        return None

    def get_closest_persona(self, action_description: str) -> PersonaConfig:
        if len(self.config.personas) <= 1:
            return self.config.personas[0] if self.config.personas else PersonaConfig(name="默认人设")
        
        action_lower = action_description.lower()
        mapping = {
            "女仆": ["女仆", "maid", "过膝袜"],
            "JK": ["JK", "jk", "制服", "裙子"],
            "写实": ["raw photo", "8k"],
            "机甲": ["机甲", "mecha", "盔甲"]
        }
        
        for name, keywords in mapping.items():
            if any(key in action_lower for key in keywords):
                closest = self.get_persona(name)
                if closest:
                    return closest
        return self.config.personas[0]

    def build_persona_prompt(self, persona: PersonaConfig, user_input_action: str) -> Tuple[str, Dict[str, Any]]:
        action_prompt_part = user_input_action.strip() or "looking at camera and smiling"
        persona_base_part = persona.base_prompt.strip()
        final_prompt = f"{persona_base_part}, {action_prompt_part}"
        
        extra_kwargs = {}
        
        # 🌟 智能雷达：去全局图库池中匹配绝对路径
        if persona.ref_image_name:
            matched_path = None
            for path in self.config.ref_images_pool:
                # 只对比文件名部分，你填 "1.jpg"，它匹配 "/data/.../1.jpg"
                if persona.ref_image_name.lower() in os.path.basename(path).lower():
                    matched_path = path
                    break
            
            if matched_path and os.path.exists(matched_path):
                extra_kwargs["ref_image_path_or_url"] = matched_path
                logger.info(f"✅ 成功从全局图库匹配到人设图: {matched_path}")
            else:
                # 兜底：如果用户直接在此处填了网络 URL，依然兼容放行
                if persona.ref_image_name.startswith("http"):
                    extra_kwargs["ref_image_path_or_url"] = persona.ref_image_name
                    logger.info(f"✅ 识别为网络 URL 参考图: {persona.ref_image_name}")
                else:
                    logger.warning(f"⚠️ 未能在全局图库中找到匹配 '{persona.ref_image_name}' 的图片！请检查上方是否已上传。")

        return final_prompt, extra_kwargs
