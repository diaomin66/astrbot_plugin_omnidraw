"""
AstrBot 万象画卷插件 v3.1
功能：QQ号白名单 + 大模型自然语言回复前置 (Markdown图片融合)
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
    # 常规指令区 (直接发图，不经过大模型闲聊)
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
        yield event.chain_result([Image.fromURL(image_url)])

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
        yield event.chain_result([Image.fromURL(image_url)])

    # ==========================================
    # 🤖 LLM 工具区 (拦截发图动作，移交大模型回复)
    # ==========================================
    def _save_base64_to_temp(self, b64_url: str) -> str:
        """核心组件：将 Base64 转化为本地文件，以便 Markdown 解析"""
        b64_data = b64_url.split(",", 1)[1]
        save_dir = os.path.abspath(os.path.join(os.getcwd(), "data", "plugin_data", "astrbot_plugin_omnidraw", "temp_images"))
        os.makedirs(save_dir, exist_ok=True)
        file_path = os.path.join(save_dir, f"img_{uuid.uuid4().hex[:8]}.png")
        with open(file_path, "wb") as f:
            f.write(base64.b64decode(b64_data))
        # 将反斜杠替换为正斜杠，防止 Markdown 转义失效
        return file_path.replace("\\", "/")

    @llm_tool(name="generate_selfie")
    async def tool_generate_selfie(self, event: AstrMessageEvent, action: str) -> AsyncGenerator[Any, None]:
        """
        以此 AI 助理（我）的固定人设拍摄自拍。
        Args:
            action (string): 动作和场景描述。纯动作描述即可，无需包含人物长相特征。
        """
        if not self._has_permission(event):
            yield event.plain_result(f"{MessageEmoji.WARNING} 抱歉，您的账号没有让我自拍的权限哦~")
            return

        try:
            final_prompt, extra_kwargs = self.persona_manager.build_persona_prompt(action)
            user_ref = self._get_event_image(event)
            if user_ref:
                extra_kwargs["user_ref"] = user_ref
                
            chain_to_use = "selfie" if "selfie" in self.plugin_config.chains else "text2img"
            async with aiohttp.ClientSession() as session:
                chain_manager = ChainManager(self.plugin_config, session)
                image_url = await chain_manager.run_chain(chain_to_use, final_prompt, **extra_kwargs)
            
            # 1. 临时保存并获取路径
            if image_url.startswith("data:image"):
                image_url = self._save_base64_to_temp(image_url)

            # 2. 不直接发送！而是作为系统提示词退给大模型，让大模型把它说出来！
            return f"自拍成功！图片路径：{image_url} \n请你现在立刻用符合你人设的自然语气回复用户，并且必须在你的回复内容的最后面，附上这句 Markdown 代码来发图：![image]({image_url})"
            
        except Exception as e:
            yield event.plain_result(f"{MessageEmoji.ERROR} 画笔坏了：{str(e)}")

    @llm_tool(name="generate_image")
    async def tool_generate_image(self, event: AstrMessageEvent, prompt: str) -> AsyncGenerator[Any, None]:
        """
        AI 画图工具。当用户提出明确的画面要求你画出来时调用此工具。
        Args:
            prompt (string): 扩写成英文的高质量动作与场景提示词。
        """
        if not self._has_permission(event):
            yield event.plain_result(f"{MessageEmoji.WARNING} 抱歉，我目前不能为您画图，权限不足。")
            return

        try:
            # 隐藏了以前会立刻弹出的 "好的马上作画..."，让全程更自然无感
            kwargs = {}
            user_ref = self._get_event_image(event)
            if user_ref:
                kwargs["user_ref"] = user_ref
                
            async with aiohttp.ClientSession() as session:
                chain_manager = ChainManager(self.plugin_config, session)
                image_url = await chain_manager.run_chain("text2img", prompt, **kwargs)

            # 1. 临时保存并获取路径
            if image_url.startswith("data:image"):
                image_url = self._save_base64_to_temp(image_url)

            # 2. 移交大模型回复
            return f"画图任务成功！图片路径：{image_url} \n请你现在立刻回复用户，并且必须在你的回复内容的最后面，附上这句 Markdown 代码来展示你画好的图：![image]({image_url})"

        except Exception as e:
            yield event.plain_result(f"{MessageEmoji.ERROR} 画笔坏了：{str(e)}")
