"""
AstrBot 万象画卷插件 v1.8.0
功能描述：人设库管理与人设 Prompt 构造服务 (完全本地化加载版)
"""

from typing import Tuple, Dict, Any, Optional
import os
from astrbot.api import logger
from ..models import PluginConfig, PersonaConfig

PLUGIN_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LOCAL_IMAGE_DIR = os.path.join(PLUGIN_ROOT, "images")

class PersonaManager:
    def __init__(self, config: PluginConfig):
        self.config = config
        os.makedirs(LOCAL_IMAGE_DIR, exist_ok=True)

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
        
        if persona.ref_image_name:
            target_filename = persona.ref_image_name.strip()
            
            # 第一优先级：精确匹配本地文件夹
            local_guess_path = os.path.join(LOCAL_IMAGE_DIR, target_filename)
            if os.path.exists(local_guess_path):
                extra_kwargs["ref_image_path_or_url"] = local_guess_path
                logger.info(f"⚡ [极速加载] 从本地图库瞬间读取成功: {local_guess_path}")
            
            # 第二优先级：网络链接
            elif target_filename.startswith("http"):
                extra_kwargs["ref_image_path_or_url"] = target_filename
                logger.info(f"🌐 识别为网络 URL 参考图: {target_filename}")
                
            # 第三优先级：模糊搜索本地文件夹（比如你只输入了 "120c8d"）
            else:
                matched = False
                for file in os.listdir(LOCAL_IMAGE_DIR):
                    if target_filename.lower() in file.lower():
                        matched_path = os.path.join(LOCAL_IMAGE_DIR, file)
                        extra_kwargs["ref_image_path_or_url"] = matched_path
                        logger.info(f"🎯 [智能补全] 从本地图库模糊匹配成功: {matched_path}")
                        matched = True
                        break
                
                if not matched:
                    logger.warning(f"⚠️ 找不到图片 '{target_filename}'！当前专属图库 ({LOCAL_IMAGE_DIR}) 内存在的图片有: {os.listdir(LOCAL_IMAGE_DIR)}")

        return final_prompt, extra_kwargs
