"""
AstrBot 万象画卷插件 v3.0
核心特性：极简架构 + 动态抓取用户发图 + 原生WebUI管理 + 完整LLM工具支持
"""
import aiohttp
from typing import AsyncGenerator, Any

from astrbot.api.star import Context, Star, register
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.message_components import Image, Plain
from astrbot.api import logger, llm_tool 

from .models import PluginConfig
from .constants import MessageEmoji
from .utils import handle_errors
from .core.chain_manager import ChainManager
from .core.parser import CommandParser
from .core.persona_manager import PersonaManager

@register("astrbot_plugin_omnidraw", "your_name", "万象画卷 v3.0 - 终极版", "3.0.0")
class OmniDrawPlugin(Star):
    def __init__(self, context: Context, config: dict = None):
        super().__init__(context)
        self.plugin_config = PluginConfig.from_dict(config or {})
        self.cmd_parser = CommandParser()
        self.persona_manager = PersonaManager(self.plugin_config)
        logger.info(f"{MessageEmoji.SUCCESS} 万象画卷 v3.0 加载完毕! (已启用动态图片捕获)")

    def _get_event_image(self, event: AstrMessageEvent) -> str:
        """智能雷达：捕获用户当前消息中的图片作为动态参考"""
        for comp in event.message_obj.message:
            if isinstance(comp, Image):
                path = getattr(comp, "path", getattr(comp, "file", None))
                url = getattr(comp, "url", None)
                return path if (path and not path.startswith("http")) else url
        return ""

    @filter.command("万象帮助")
    @handle_errors
    async def cmd_help(self, event: AstrMessageEvent) -> AsyncGenerator[Any, None]:
        help_text = f"""📖 万象画卷 v3.0 帮助
━━━━━━━━━━━━
🎨 核心作画:
/画 [提示词] [带上一张图片可做参考]

🤳 助理自拍 ({self.plugin_config.persona_name}):
/自拍 [动作描述] [发张图片让我穿同款]

🤖 智能召唤:
日常聊天提及看看你、发自拍时，大模型将自动执行。"""
        yield event.plain_result(help_text)

    @filter.command("画")
    @handle_errors
    async def cmd_draw(self, event: AstrMessageEvent, message: str = "") -> AsyncGenerator[Any, None]:
        message = message.strip()
        user_ref = self._get_event_image(event)
        
        if not message and not user_ref:
            yield event.plain_result(f"{MessageEmoji.WARNING} 请输入提示词或附带一张参考图！")
            return
        
        prompt, kwargs = self.cmd_parser.parse(message)
        if user_ref:
            kwargs["user_ref"] = user_ref
            
        yield event.plain_result(f"{MessageEmoji.PAINTING} 收到灵感，正在绘制...")
        
        async with aiohttp.ClientSession() as session:
            chain_manager = ChainManager(self.plugin_config, session)
            image_url = await chain_manager.run_chain("text2img", prompt, **kwargs)
            
        yield event.chain_result([
            Image.fromURL(image_url),
            Plain(f"\n{MessageEmoji.SUCCESS} 画好啦！")
        ])

    @filter.command("自拍")
    @handle_errors
    async def cmd_selfie(self, event: AstrMessageEvent, message: str = "") -> AsyncGenerator[Any, None]:
        user_input = message.strip() if message else "看着镜头微笑"
        final_prompt, extra_kwargs = self.persona_manager.build_persona_prompt(user_input)
        
        # 捕获用户在聊天中发来的衣服/姿势图
        user_ref = self._get_event_image(event)
        if user_ref:
            extra_kwargs["user_ref"] = user_ref
            logger.info("👕 检测到用户发送了动态参考图，已注入！")
        
        yield event.plain_result(f"{MessageEmoji.INFO} 正在为「{self.plugin_config.persona_name}」生成自拍...")

        chain_to_use = "selfie" if "selfie" in self.plugin_config.chains else "text2img"
        async with aiohttp.ClientSession() as session:
            chain_manager = ChainManager(self.plugin_config, session)
            image_url = await chain_manager.run_chain(chain_to_use, final_prompt, **extra_kwargs)
            
        yield event.chain_result([Image.fromURL(image_url)])

    @llm_tool(name="generate_selfie", description="以此 AI 助理（我）的固定人设和参考形象拍摄一张自拍或人像照片。当用户想看我、看腿、发照片时必须调用。传入的 action 必须是你根据上下文生成的动作场景描述。")
    async def tool_generate_selfie(self, event: AstrMessageEvent, action: str) -> AsyncGenerator[Any, None]:
        """
        供大模型调用的自拍工具。
        
        Args:
            action (string): 动作和场景描述。必须是你根据上下文扩写并翻译成英文的高质量提示词，包含动作、表情、服装、环境等细节。
        """
        logger.info(f"🧠 [LLM Tool] 触发智能自拍！描述: {action}")
        try:
            final_prompt, extra_kwargs = self.persona_manager.build_persona_prompt(action)
            
            # 尝试捕获上下文中用户刚发的图片
            user_ref = self._get_event_image(event)
            if user_ref:
                extra_kwargs["user_ref"] = user_ref
            
            chain_to_use = "selfie" if "selfie" in self.plugin_config.chains else "text2img"
            
            async with aiohttp.ClientSession() as session:
                chain_manager = ChainManager(self.plugin_config, session)
                image_url = await chain_manager.run_chain(chain_to_use, final_prompt, **extra_kwargs)
                
            yield event.chain_result([Image.fromURL(image_url)])
        except Exception as e:
            logger.error(f"❌ [LLM Tool] 自拍失败: {e}", exc_info=True)
            yield event.plain_result(f"{MessageEmoji.ERROR} 画笔坏了：{str(e)}")

    @llm_tool(name="generate_image", description="AI 画图工具。当用户提出明确的画面要求你画出来时调用此工具。")
    async def tool_generate_image(self, event: AstrMessageEvent, prompt: str) -> AsyncGenerator[Any, None]:
        """
        供大模型调用的画图接口。
        
        Args:
            prompt (string): 扩写成英文的高质量正向提示词。必须包含画面主体、环境、光影、画风等丰富细节。
        """
        logger.info(f"🧠 [LLM Tool] 触发画图！描述: {prompt}")
        try:
            yield event.plain_result(f"{MessageEmoji.PAINTING} 好的，马上为你作画...")
            kwargs = {}
            user_ref = self._get_event_image(event)
            if user_ref:
                kwargs["user_ref"] = user_ref
                
            async with aiohttp.ClientSession() as session:
                chain_manager = ChainManager(self.plugin_config, session)
                image_url = await chain_manager.run_chain("text2img", prompt, **kwargs)
            yield event.chain_result([Image.fromURL(image_url), Plain(f"\n{MessageEmoji.SUCCESS} 画好啦！")])
        except Exception as e:
            logger.error(f"❌ [LLM Tool] 画图失败: {e}", exc_info=True)
            yield event.plain_result(f"{MessageEmoji.ERROR} 画笔坏了：{str(e)}")
