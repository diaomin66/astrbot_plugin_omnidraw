"""
AstrBot 万象画卷插件 v3.0 - 单一人设 Prompt 构造服务
"""
import os
from typing import Tuple, Dict, Any
from astrbot.api import logger
from ..models import PluginConfig
from ..core.prompt_optimizer import PromptOptimizer

class PersonaManager:
    def __init__(self, config: PluginConfig):
        self.config = config

    def build_persona_prompt(self, user_input_action: str) -> Tuple[str, Dict[str, Any]]:
        action_prompt_part = user_input_action.strip() or "looking at camera and smiling"
        
        if action_prompt_part.startswith("{") and "HARDCODED_ANTI_COLLAGE_RULE" in action_prompt_part:
            action_prompt_part = PromptOptimizer.flatten_json_prompt(action_prompt_part)
            logger.info(f"🔄 [Persona] JSON 提示词已转换为自然语言格式")

        persona_base_part = self.config.persona_base_prompt.strip()
        
        if persona_base_part:
            final_prompt = f"{persona_base_part}, {action_prompt_part}"
        else:
            final_prompt = action_prompt_part
        
        extra_kwargs = {}
        target_img = self.config.persona_ref_image
        
        if target_img:
            if target_img.startswith("http"):
                extra_kwargs["persona_ref"] = target_img
                logger.info(f"🌐 已加载网络 URL 形象参考图: {target_img}")
            elif os.path.exists(target_img):
                extra_kwargs["persona_ref"] = target_img
                logger.info(f"⚡ 已加载本地固定形象参考图: {target_img}")
            else:
                logger.warning(f"⚠️ 找不到配置的形象参考图: '{target_img}'，请在 WebUI 重新上传。")

        return final_prompt, extra_kwargs
