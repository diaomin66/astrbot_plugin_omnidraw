"""
AstrBot 万象画卷插件 v1.3.0
功能描述：人设库管理与人设 Prompt 构造服务 (深度兼容本地文件参考图)
"""

from typing import Tuple, Dict, Any, Optional
from astrbot.api import logger
from ..models import PluginConfig, PersonaConfig

class PersonaManager:
    def __init__(self, config: PluginConfig):
        self.config = config

    def get_persona(self, name: str) -> Optional[PersonaConfig]:
        """根据名称获取人设配置"""
        for p in self.config.personas:
            if p.name == name:
                return p
        return None

    def get_closest_persona(self, action_description: str) -> PersonaConfig:
        """根据 LLM 决策的动作描述，自动选择一个最匹配的人设。
        目前版本使用简单的关键词匹配，未来可引入文本相似度算法。
        """
        # 如果只有一个，直接返回，别废话
        if len(self.config.personas) <= 1:
            return self.config.personas[0] if self.config.personas else PersonaConfig(name="默认人设")
        
        logger.debug(f"[PersonaManager] 正在匹配人设...")
        # 关键词匹配 (示例)
        action_lower = action_description.lower()
        
        # 定义一个简单的映射规则
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
                    logger.info(f"✅ LLM 自动匹配人设: {name}")
                    return closest
                    
        # 兜底返回第一个
        logger.debug(f"[PersonaManager] 未找到关键词匹配，返回默认人设: {self.config.personas[0].name}")
        return self.config.personas[0]

    def build_persona_prompt(self, persona: PersonaConfig, user_input_action: str) -> Tuple[str, Dict[str, Any]]:
        """
        核心 Prompt 重塑服务：
        1. 翻译扩写用户动作。
        2. 注入人设固定描述描述。
        3. 关键修复：当配置本地人设图文件时，检查文件是否存在并注入路径。
        """
        logger.info(f"[PersonaManager] 正在以人设「{persona.name}」构造 Prompt，动作: {user_input_action[:10]}...")
        
        # 1. 扩写动作为高质量 Prompt (这里假设大模型调用时已经帮我们翻译成英文了)
        action_prompt_part = user_input_action.strip() or "looking at camera and smiling"
        
        # 2. 注入人设固定 Prompt Description (用于文生图基础描述)
        persona_base_part = persona.base_prompt.strip()
        
        # 组装最终正向提示词
        final_prompt = f"{persona_base_part}, {action_prompt_part}"
        
        # 3. 关键修复：人设文件注入本地人设本地文件路径
        extra_kwargs = {}
        
        # 检查是否配置了本地人设图文件，且文件确实存在
        if persona.ref_image_url and persona.local_image_exists:
            # 填入绝对路径，交由 Provider 基类去转 Base64 发 API
            # 将 kwargs 命名为 'ref_image_path_or_url' 供 Provider 识别
            extra_kwargs["ref_image_path_or_url"] = persona.ref_image_url
            logger.info(f"✅ 成功注入本地人设图路径: {persona.ref_image_url}")
        else:
            if persona.ref_image_url and persona.ref_image_url.startswith("http"):
                # 如果是网络URL，也传给 Provider
                extra_kwargs["ref_image_path_or_url"] = persona.ref_image_url
                logger.info(f"✅ 成功注入网络人设图 URL: {persona.ref_image_url[:15]}...")

        return final_prompt, extra_kwargs
