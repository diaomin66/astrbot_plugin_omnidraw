"""
AstrBot 万象画卷插件 v1.2.0

新增功能：
- 接入 @llm_tool 允许大语言模型自然语言调用文生图
"""

import aiohttp
from typing import AsyncGenerator, Any

from astrbot.api.star import Context, Star, register
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.message_components import Image, Plain
# 【关键修复】直接从 astrbot.api 中导入 logger 和 llm_tool
from astrbot.api import logger, llm_tool 

from .models import PluginConfig
from .constants import MessageEmoji
from .utils import handle_errors
from .core.chain_manager import ChainManager
from .core.parser import CommandParser
from .core.persona_manager import PersonaManager

@register("astrbot_plugin_omnidraw", "your_name", "万象画卷 - 终极多模态", "1.2.0")
class OmniDrawPlugin(Star):
    def __init__(self, context: Context, config: dict = None):
        super().__init__(context)
        self.plugin_config = PluginConfig.from_dict(config or {})
        self._session = aiohttp.ClientSession()
        self.chain_manager = ChainManager(self.plugin_config, self._session)
        self.cmd_parser = CommandParser()
        self.persona_manager = PersonaManager(self.plugin_config)
        logger.info(f"{MessageEmoji.SUCCESS} 万象画卷插件加载完毕 (支持大模型 Tool 调用)!")

    async def terminate(self):
        if self._session and not self._session.closed:
            await self._session.close()

    @filter.command("万象帮助")
    @handle_errors
    async def cmd_help(self, event: AstrMessageEvent) -> AsyncGenerator[Any, None]:
        help_text = """📖 万象画卷 v1.2.0 帮助
━━━━━━━━━━━━
🎨 核心指令:
/画 [提示词] [--参数]
/自拍 [人设名] [动作]

🤖 智能召唤 (新!):
直接对机器人说：“帮我画一张...”

⚙️ 管理指令:
/切模型 [节点ID] [模型名]"""
        yield event.plain_result(help_text)

    @filter.command("切模型")
    @handle_errors
    async def cmd_switch_model(self, event: AstrMessageEvent, provider_id: str = "", new_model: str = "") -> AsyncGenerator[Any, None]:
        provider_id = provider_id.strip()
        new_model = new_model.strip()

        if not provider_id or not new_model:
            info = "当前节点列表:\n"
            for p in self.plugin_config.providers:
                info += f"• [{p.id}]: {p.model}\n"
            yield event.plain_result(f"{info}\n用法: /切模型 [节点ID] [新模型名]")
            return

        provider = self.plugin_config.get_provider(provider_id)
        if not provider:
            yield event.plain_result(f"{MessageEmoji.ERROR} 未找到节点: {provider_id}")
            return

        old_model = provider.model
        provider.model = new_model
        
        logger.info(f"👤 用户 {event.get_sender_id()} 将节点 {provider_id} 的模型切换为 {new_model}")
        yield event.plain_result(f"{MessageEmoji.SUCCESS} 节点 [{provider_id}] 模型已切换为: {new_model}")

    @filter.command("画")
    @handle_errors
    async def cmd_draw(self, event: AstrMessageEvent, message: str = "") -> AsyncGenerator[Any, None]:
        message = message.strip()
        if not message:
            yield event.plain_result(f"{MessageEmoji.WARNING} 请输入提示词，例如：/画 一只猫")
            return
        
        prompt, kwargs = self.cmd_parser.parse(message)
        yield event.plain_result(f"{MessageEmoji.PAINTING} 收到指令，正在绘制，请稍候...")
        
        image_url = await self.chain_manager.run_chain("text2img", prompt, **kwargs)
        yield event.chain_result([
            Image.fromURL(image_url),
            Plain(f"\n{MessageEmoji.SUCCESS} 画好啦！\n提示词: {prompt}")
        ])

    @filter.command("自拍")
    @handle_errors
    async def cmd_selfie(self, event: AstrMessageEvent, persona_name: str = "", message: str = "") -> AsyncGenerator[Any, None]:
        persona_name = persona_name.strip()
        if not persona_name:
            available = [p.name for p in self.plugin_config.personas]
            yield event.plain_result(f"{MessageEmoji.WARNING} 请指定人设名！可用人设: {', '.join(available) if available else '无'}")
            return

        persona = self.persona_manager.get_persona(persona_name)
        if not persona:
            yield event.plain_result(f"{MessageEmoji.ERROR} 未找到名为「{persona_name}」的人设！")
            return

        message = message.strip()
        user_input = message if message else "看着镜头微笑"
        
        final_prompt, extra_kwargs = self.persona_manager.build_persona_prompt(persona, user_input)
        yield event.plain_result(f"{MessageEmoji.INFO} 正在以「{persona_name}」的形象进行拍摄...")

        chain_to_use = "selfie" if "selfie" in self.plugin_config.chains else "text2img"
        image_url = await self.chain_manager.run_chain(chain_to_use, final_prompt, **extra_kwargs)
        yield event.chain_result([
            Image.fromURL(image_url),
            Plain(f"\n{MessageEmoji.SUCCESS} 拍好啦！")
        ])

   # ==========================================
    # 🌟 核心新功能：大模型自然语言绘图工具
    # ==========================================
    @llm_tool(name="generate_image", description="AI 绘图生成器。当用户请求画图、生成图片或提出明确的画面描述要求你画出来时，必须调用此工具。")
    async def tool_generate_image(self, event: AstrMessageEvent, prompt: str) -> AsyncGenerator[Any, None]:
        """
        供大语言模型调用的画图接口。
        
        Args:
            prompt (string): 你根据用户需求扩写并翻译成英文的高质量提示词。必须是英文，包含画面主体、环境、光影、画风等丰富细节。
        """
        logger.info(f"🧠 [LLM Tool] 触发自然语言画图！模型生成的提示词: {prompt}")
        
        try:
            yield event.plain_result(f"{MessageEmoji.PAINTING} 好的，我马上为你作画，请稍等片刻...")
            
            image_url = await self.chain_manager.run_chain("text2img", prompt)
            
            yield event.chain_result([
                Image.fromURL(image_url),
                Plain(f"\n{MessageEmoji.SUCCESS} 铛铛！为你画好啦！\n(Prompt: {prompt})")
            ])
            
        except Exception as e:
            logger.error(f"❌ [LLM Tool] 画图失败: {e}", exc_info=True)
            yield event.plain_result(f"{MessageEmoji.ERROR} 哎呀，画笔好像坏了：{str(e)}")
