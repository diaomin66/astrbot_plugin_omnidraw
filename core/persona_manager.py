"""
AstrBot 万象画卷插件 v1.7.2
功能描述：人设库管理与人设 Prompt 构造服务 (修复相对路径判定问题)
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
            
            logger.info(f"🔍 正在图库池 (当前总计 {len(self.config.ref_images_pool)} 张图) 中匹配关键字 '{persona.ref_image_name}'...")
            
            for path in self.config.ref_images_pool:
                file_name = os.path.basename(path).lower()
                if persona.ref_image_name.lower() in file_name:
                    matched_path = path
                    break
            
            if matched_path:
                # 【核心修复】：智能补全绝对路径，解决 AstrBot 返回相对路径导致判定失败的问题
                real_path = matched_path
                # 尝试不同的前缀路径 (当前目录, 或 data 目录)
                possible_prefixes = ["", "data"]
                
                for prefix in possible_prefixes:
                    # 如果不是绝对路径，就进行组装尝试
                    if not os.path.isabs(matched_path):
                        test_path = os.path.abspath(os.path.join(os.getcwd(), prefix, matched_path))
                    else:
                        test_path = matched_path
                        
                    if os.path.exists(test_path):
                        real_path = test_path
                        break
                        
                if os.path.exists(real_path):
                    extra_kwargs["ref_image_path_or_url"] = real_path
                    logger.info(f"✅ 成功从全局图库匹配到人设物理文件: {real_path}")
                else:
                    # 兜底：强行塞进去，让底层 Provider 抛出更详细的文件未找到错误
                    logger.warning(f"⚠️ 找到了名字匹配的路径 '{matched_path}'，但磁盘上检测不到该文件。将强行尝试加载...")
                    extra_kwargs["ref_image_path_or_url"] = matched_path
            else:
                if persona.ref_image_name.startswith("http"):
                    extra_kwargs["ref_image_path_or_url"] = persona.ref_image_name
                    logger.info(f"✅ 识别为网络 URL 参考图: {persona.ref_image_name}")
                else:
                    logger.warning(f"⚠️ 匹配失败！当前图库池的实际内容为: {self.config.ref_images_pool}")

        return final_prompt, extra_kwargs
