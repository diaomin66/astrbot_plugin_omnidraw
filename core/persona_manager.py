"""
AstrBot 万象画卷插件 v1.0.0

功能描述：
- 人设与风格管理器

作者: your_name
版本: 1.0.0
日期: 2026-04-25
"""

from typing import Optional, Tuple, Dict, Any
from ..models import PluginConfig, PersonaConfig

class PersonaManager:
    """人设与风格管理器类"""

    def __init__(self, config: PluginConfig):
        self.config = config

    def get_persona(self, persona_name: str) -> Optional[PersonaConfig]:
        """根据名称获取人设配置"""
        for persona in self.config.personas:
            if persona.name == persona_name:
                return persona
        return None

    def build_persona_prompt(self, persona: PersonaConfig, user_input: str) -> Tuple[str, Dict[str, Any]]:
        """组装人设专用的提示词和参数"""
        final_prompt = f"{persona.base_prompt}, {user_input}".strip(", ")
        extra_kwargs = {}
        
        if persona.ref_image_url:
            extra_kwargs['reference_image_url'] = persona.ref_image_url
            
        return final_prompt, extra_kwargs