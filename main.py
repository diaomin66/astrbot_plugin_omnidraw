"""
AstrBot 万象画卷插件 v1.0.0

功能描述：
- 主入口文件

作者: your_name
版本: 1.0.0
日期: 2026-04-25
"""

import aiohttp
from typing import AsyncGenerator, Any

from astrbot.api.star import Context, Star, register
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.message_components import Image, Plain
from astrbot.api import logger

from .models import PluginConfig
from .constants import MessageEmoji
from .utils import handle_errors
from .core.chain_manager import ChainManager
from .core.parser import CommandParser
from .core.persona_manager import PersonaManager

@register("astrbot_plugin_omnidraw", "your_name", "万象画卷 - 终极多模态绘图聚合器", "1.0.0")
class OmniDrawPlugin(Star):
    """插件主类"""

    def __init__(self, context: Context, config: dict = None):
        super().__init__(context)
        # 1. 结构化配置
        self.plugin_config = PluginConfig.from_dict(config or {})
        
        # 2. 初始化全局 HTTP Session (性能优化)
        self._session = aiohttp.ClientSession()
        
        # 3. 模块化加载核心服务
        self.chain_manager = ChainManager(self.plugin_config, self._session)
        self.cmd_parser = CommandParser()
        self.persona_manager = PersonaManager(self.plugin_config)
        
        logger.info(f"{MessageEmoji.SUCCESS} 万象画卷插件加载完毕! 提供商数量: {len(self.plugin_config.providers)}")

    async def terminate(self):
        """插件卸载时清理资源"""
        if self._session and not self._session.closed:
            await self._session.close()
            logger.info("全局 aiohttp Session 已安全关闭")

    @filter.command("万象帮助")
    @handle_errors
    async def cmd_help(self, event: AstrMessageEvent) -> AsyncGenerator[Any, None]:
        """查看帮助"""
        help_text = f"""📖 万象画卷帮助 v1.0.0
━━━━━━━━━━━━
🎨 核心指令:
/画 [提示词] - 基础作画
/自拍 [人设名] [动作] - 以预设人设作画

💡 高级参数:
支持在提示词中附加 --参数名 参数值
例如: /画 一只猫 --ar 16:9 --size 1024x1024
"""
        yield event.plain_result(help_text)

    @filter.command("画")
    @handle_errors
    async def cmd_draw(self, event: AstrMessageEvent, *args) -> AsyncGenerator[Any, None]:
        """基础画图指令"""
        if not args:
            yield event.plain_result(f"{MessageEmoji.WARNING} 请输入提示词，例如：/画 一只猫")
            return

        raw_input = " ".join(args)
        
        # 分离文本与高级参数
        prompt, kwargs = self.cmd_parser.parse(raw_input)
        
        yield event.plain_result(f"{MessageEmoji.PAINTING} 收到灵感，正在绘制，请稍候...")

        # 执行文生图链路
        image_url = await self.chain_manager.run_chain("text2img", prompt, **kwargs)

        yield event.chain_result([
            Image.fromURL(image_url),
            Plain(f"\n{MessageEmoji.SUCCESS} 画好啦！\n提示词: {prompt}")
        ])

    @filter.command("自拍")
    @handle_errors
    async def cmd_selfie(self, event: AstrMessageEvent, persona_name: str = None, *args) -> AsyncGenerator[Any, None]:
        """人设自拍模式"""
        if not persona_name:
            # 如果没提供名字，列出所有可用人设
            available = [p.name for p in self.plugin_config.personas]
            yield event.plain_result(f"{MessageEmoji.WARNING} 请指定人设名！可用人设: {', '.join(available) if available else '无'}")
            return

        persona = self.persona_manager.get_persona(persona_name)
        if not persona:
            yield event.plain_result(f"{MessageEmoji.ERROR} 未找到名为「{persona_name}」的人设！")
            return

        user_input = " ".join(args) if args else "看着镜头微笑"
        
        # 组装 Prompt
        final_prompt, extra_kwargs = self.persona_manager.build_persona_prompt(persona, user_input)
        
        yield event.plain_result(f"{MessageEmoji.INFO} 正在以「{persona_name}」的形象进行拍摄...")

        chain_to_use = "selfie" if "selfie" in self.plugin_config.chains else "text2img"
        image_url = await self.chain_manager.run_chain(chain_to_use, final_prompt, **extra_kwargs)

        yield event.chain_result([
            Image.fromURL(image_url),
            Plain(f"\n{MessageEmoji.SUCCESS} 拍好啦！")
        ])