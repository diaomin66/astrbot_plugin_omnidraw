"""
AstrBot 万象画卷插件 v1.7.4
功能描述：人设库管理与人设 Prompt 构造服务 (本地图库极速版 - 致敬你的完美思路)
"""

from typing import Tuple, Dict, Any, Optional
import os
from astrbot.api import logger
from ..models import PluginConfig, PersonaConfig

# 获取当前文件所在目录 (core) 的上一级，也就是插件的根目录
PLUGIN_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
# 按照你的思路，在插件内部定义一个专属的图片文件夹
LOCAL_IMAGE_DIR = os.path.join(PLUGIN_ROOT, "images")

class PersonaManager:
    def __init__(self, config: PluginConfig):
        self.config = config
        # 初始化时，如果不存在这个文件夹，就自动帮你建好
        if not os.path.exists(LOCAL_IMAGE_DIR):
            os.makedirs(LOCAL_IMAGE_DIR, exist_ok=True)
            logger.info(f"📁 已自动创建插件专属本地图库: {LOCAL_IMAGE_DIR}")

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
            real_path = None
            target_filename = persona.ref_image_name.strip()
            
            # ==========================================
            # 🚀 策略 1：本地专属图库极速直读 (你的方案)
            # ==========================================
            local_guess_path = os.path.join(LOCAL_IMAGE_DIR, target_filename)
            if os.path.exists(local_guess_path):
                real_path = local_guess_path
                logger.info(f"⚡ [极速加载] 从插件本地图库瞬间找到图片: {real_path}")

            # ==========================================
            # 🔍 策略 2：定向解析 WebUI 缓存 (精准打击，拒绝全盘扫描)
            # ==========================================
            if not real_path:
                for path in self.config.ref_images_pool:
                    if target_filename.lower() in os.path.basename(path).lower():
                        # AstrBot 常见的几个相对路径基准点
                        possible_bases = [
                            os.getcwd(),                                      # 运行根目录
                            os.path.join(os.getcwd(), "data"),                # 标准 data 目录
                            os.path.abspath(os.path.join(PLUGIN_ROOT, "../../..")) # 从插件目录反推 AstrBot Core 目录
                        ]
                        for base in possible_bases:
                            test_path = os.path.join(base, path)
                            if os.path.exists(test_path):
                                real_path = test_path
                                logger.info(f"✅ 从 WebUI 缓存精准定位图片: {real_path}")
                                break
                        break

            # ==========================================
            # 🏁 最终结算
            # ==========================================
            if real_path and os.path.exists(real_path):
                extra_kwargs["ref_image_path_or_url"] = real_path
            else:
                if persona.ref_image_name.startswith("http"):
                    extra_kwargs["ref_image_path_or_url"] = persona.ref_image_name
                    logger.info(f"✅ 识别为网络 URL 参考图: {persona.ref_image_name}")
                else:
                    logger.warning(f"⚠️ 找不到图片 '{target_filename}'！\n💡 建议: 请直接将图片复制到插件的 images 文件夹 ({LOCAL_IMAGE_DIR}) 下。")

        return final_prompt, extra_kwargs
