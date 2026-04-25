"""
AstrBot 万象画卷插件 v3.1
功能：精简拟真交互 + 完美兼容 Base64 与 URL 混合发图
"""
import os
import base64
import uuid
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

@register("astrbot_plugin_omnidraw", "your_name", "万象画卷 v3.1 - 终极版", "3.1.0")
class OmniDrawPlugin(Star):
    def __init__(self, context: Context, config: dict = None):
        super().__init__(context)
        self.plugin_config = PluginConfig.from_dict(config or {})
        self.cmd_parser = CommandParser()
        self.persona_manager = PersonaManager(self.plugin_config)

    def _get_event_image(self, event: AstrMessageEvent) -> str:
        for comp in event.message_obj.message:
            if isinstance(comp, Image):
                path = getattr(comp, "path", getattr(comp, "file", None))
                url = getattr(comp, "url", None)
                return path if (path and not path.startswith("http")) else url
        return ""

    def _has_permission(self, event: AstrMessageEvent) -> bool:
        allowed = self.plugin_config.allowed_users
        if not allowed:
            return True
        sender_id = str(event.get_sender_id())
        if sender_id in allowed:
            return True
        logger.warning(f"🚫 拦截无权限用户调用生图: {sender_id}")
        return False

    # ==========================================
    # 🚀 新增核心：智能发图组件构造器
    # 自动识别图片格式，防止 fromURL 报错崩溃
    # ==========================================
    def _create_image_component(self, image_url: str) -> Image:
        if image_url.startswith("data:image"):
            # 如果是 Base64，自动解码并保存为本地临时文件
            b64_data = image_url.split(",", 1)[1]
            save_dir = os.path.abspath(os.path.join(os.getcwd(), "data", "plugin_data", "astrbot_plugin_omnidraw", "temp_images"))
            os.makedirs(save_dir, exist_ok=True)
            file_path = os.path.join(save_dir, f"img_{uuid.uuid4().hex[:8]}.png")
            with open(file_path, "wb") as f:
                f.write(base64.b64decode(b64_data))
            # 使用本地文件通道发图
            return Image.fromFileSystem(file_path)
        else:
            # 如果是正常链接，走网络链接通道
            return Image.fromURL(image_url)

    # ==========================================
    # 常规指令区 (使用 yield 直接发消息)
    # ==========================================
    @filter.command("万象帮助")
    @handle_errors
    async def cmd_help(self, event: AstrMessageEvent) -> AsyncGenerator[Any, None]:
        help_text = "📖 万象画卷 v3.1 帮助\n/画 [提示词]\n/自拍 [动作描述]"
        yield event.plain_result(help_text)

    @filter.command("画")
    @handle_errors
    async def cmd_draw(self, event: AstrMessageEvent, message: str = "") -> AsyncGenerator[Any, None]:
        if not self._has_permission(event):
            yield event.plain_result(f"{MessageEmoji.WARNING} 抱歉，您暂无画图功能的使用权限哦！")
            return

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
        
        # 🚀 替换为智能组件发送
        yield event.chain_result([self._create_image_component(image_url)])

    @filter.command("自拍")
    @handle_errors
    async def cmd_selfie(self, event: AstrMessageEvent, message: str = "") -> AsyncGenerator[Any, None]:
        if not self._has_permission(event):
            yield event.plain_result(f"{MessageEmoji.WARNING} 抱歉，您暂无自拍功能的使用权限哦！")
            return

        user_input = message.strip() if message else "看着镜头微笑"
        final_prompt, extra_kwargs = self.persona_manager.build_persona_prompt(user_input)
        
        user_ref = self._get_event_image(event)
        if user_ref:
            extra_kwargs["user_ref"] = user_ref
            
        yield event.plain_result(f"{MessageEmoji.INFO} 正在为「{self.plugin_config.persona_name}」生成自拍...")
        chain_to_use = "selfie" if "selfie" in self.plugin_config.chains else "text2img"
        async with aiohttp.ClientSession() as session:
            chain_manager = ChainManager(self.plugin_config, session)
            image_url = await chain_manager.run_chain(chain_to_use, final_prompt, **extra_kwargs)
        
        # 🚀 替换为智能组件发送
        yield event.chain_result([self._create_image_component(image_url)])

    # ==========================================
    # 🤖 LLM 工具区 (静默发图 + 移交回复权)
    # ==========================================
    @llm_tool(name="generate_selfie")
    async def tool_generate_selfie(self, event: AstrMessageEvent, action: str) -> str:
        """
        以此 AI 助理（我）的固定人设拍摄自拍。
        Args:
            action (string): 动作和场景描述。纯动作描述即可，无需包含人物长相特征。
        """
        if not self._has_permission(event):
            return "系统提示：当前用户没有权限使用自拍功能，请你委婉地拒绝他。"

        try:
            final_prompt, extra_kwargs = self.persona_manager.build_persona_prompt(action)
            user_ref = self._get_event_image(event)
            if user_ref:
                extra_kwargs["user_ref"] = user_ref
                
            chain_to_use = "selfie" if "selfie" in self.plugin_config.chains else "text2img"
            async with aiohttp.ClientSession() as session:
                chain_manager = ChainManager(self.plugin_config, session)
                image_url = await chain_manager.run_chain(chain_to_use, final_prompt, **extra_kwargs)
            
            # 🚀 物理底层发图：使用智能组件解析
            await event.send(event.chain_result([self._create_image_component(image_url)]))

            return "系统提示：自拍图片已经通过底层协议成功发送给用户了。请你现在结合用户刚才的请求，用符合你人设的自然语气回复一两句作为发图后的收尾闲聊 (注意：直接输出纯文本内容，绝对不需要包含任何 Markdown 图片链接)。"
            
        except Exception as e:
            return f"系统提示：画笔坏了 ({str(e)})。请向用户道歉，并说明无法发图。"

    @llm_tool(name="generate_image")
    async def tool_generate_image(self, event: AstrMessageEvent, prompt: str) -> str:
        """
        AI 画图工具。当用户提出明确的画面要求你画出来时调用此工具。
        Args:
            prompt (string): 扩写成英文的高质量动作与场景提示词。
        """
        if not self._has_permission(event):
            return "系统提示：当前用户没有权限使用画图功能，请你委婉地拒绝他。"

        try:
            kwargs = {}
            user_ref = self._get_event_image(event)
            if user_ref:
                kwargs["user_ref"] = user_ref
                
            async with aiohttp.ClientSession() as session:
                chain_manager = ChainManager(self.plugin_config, session)
                image_url = await chain_manager.run_chain("text2img", prompt, **kwargs)

            # 🚀 物理底层发图：使用智能组件解析
            await event.send(event.chain_result([self._create_image_component(image_url)]))

            return "系统提示：画好的图已经物理发送成功了。请你现在立刻回复用户一句话，用符合你人设的语气简单聊两句作为作画后的完美收尾 (直接输出纯文本内容即可，不需要包含图片链接)。"

        except Exception as e:
            return f"系统提示：画笔坏了 ({str(e)})。请向用户道歉，并说明无法发图。"
