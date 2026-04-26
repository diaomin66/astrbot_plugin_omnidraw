"""
AstrBot 万象画卷插件 v3.1
功能：防盗链突破(图片本地持久化+Base64注入) + 异步视频生成 + 模型动态切换 + 完整参数解析
"""
import os
import base64
import uuid
import time
import aiohttp
import asyncio
from typing import AsyncGenerator, Any

from astrbot.api.star import Context, Star, register
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.message_components import Image, Plain, Video
from astrbot.api import logger, llm_tool 

from .models import PluginConfig
from .constants import MessageEmoji
from .utils import handle_errors
from .core.chain_manager import ChainManager
from .core.parser import CommandParser
from .core.persona_manager import PersonaManager
from .core.video_manager import VideoManager

@register("astrbot_plugin_omnidraw", "your_name", "万象画卷 v3.1 - 终极版", "3.1.0")
class OmniDrawPlugin(Star):
    def __init__(self, context: Context, config: dict = None):
        super().__init__(context)
        self.plugin_config = PluginConfig.from_dict(config or {})
        self.cmd_parser = CommandParser()
        self.persona_manager = PersonaManager(self.plugin_config)
        self.video_manager = VideoManager(self.plugin_config)

    def _get_event_images(self, event: AstrMessageEvent) -> list:
        """从消息中提取原始的图片路径或URL列表"""
        images = []
        for comp in event.message_obj.message:
            if isinstance(comp, Image):
                path = getattr(comp, "path", getattr(comp, "file", None))
                url = getattr(comp, "url", None)
                img_ref = path if (path and not path.startswith("http")) else url
                if img_ref:
                    images.append(img_ref)
        return images

    # ==========================================
    # 🚀 核心升级：防盗链突破器 (下载 -> 保存 -> Base64)
    # ==========================================
    async def _process_images_to_base64(self, raw_images: list) -> list:
        """将原始图片链接下载到本地，并转换为兼容 API 的 Base64 Data URI"""
        processed = []
        if not raw_images:
            return processed
            
        # 建立专用的本地缓存目录
        save_dir = os.path.abspath(os.path.join(os.getcwd(), "data", "plugin_data", "astrbot_plugin_omnidraw", "user_refs"))
        os.makedirs(save_dir, exist_ok=True)
        
        # 伪装成正常浏览器，防止某些图床基础拦截
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        
        async with aiohttp.ClientSession() as session:
            for img_ref in raw_images:
                if img_ref.startswith("http"):
                    try:
                        async with session.get(img_ref, headers=headers) as resp:
                            if resp.status == 200:
                                img_data = await resp.read()
                                # 1. 保存到本地 (持久化，方便你溯源排错)
                                file_name = f"ref_{uuid.uuid4().hex[:8]}.png"
                                file_path = os.path.join(save_dir, file_name)
                                with open(file_path, "wb") as f:
                                    f.write(img_data)
                                logger.info(f"🛡️ [防盗链突破] 成功下载参考图至: {file_path}")
                                
                                # 2. 转换为 Base64
                                b64_str = base64.b64encode(img_data).decode("utf-8")
                                processed.append(f"data:image/png;base64,{b64_str}")
                            else:
                                logger.error(f"❌ [防盗链突破] 下载参考图失败，状态码: {resp.status}")
                    except Exception as e:
                        logger.error(f"❌ [防盗链突破] 下载参考图异常: {e}")
                else:
                    # 如果已经是本地路径，直接读取转换
                    try:
                        if os.path.exists(img_ref):
                            with open(img_ref, "rb") as f:
                                img_data = f.read()
                            b64_str = base64.b64encode(img_data).decode("utf-8")
                            processed.append(f"data:image/png;base64,{b64_str}")
                    except Exception as e:
                        logger.error(f"❌ 读取本地图异常: {e}")
        return processed

    def _has_permission(self, event: AstrMessageEvent) -> bool:
        allowed = self.plugin_config.allowed_users
        if not allowed:
            return True
        sender_id = str(event.get_sender_id())
        if sender_id in allowed:
            return True
        logger.warning(f"🚫 拦截无权限用户调用生图: {sender_id}")
        return False

    def _create_image_component(self, image_url: str) -> Image:
        if image_url.startswith("data:image"):
            b64_data = image_url.split(",", 1)[1]
            save_dir = os.path.abspath(os.path.join(os.getcwd(), "data", "plugin_data", "astrbot_plugin_omnidraw", "temp_images"))
            os.makedirs(save_dir, exist_ok=True)
            file_path = os.path.join(save_dir, f"img_{uuid.uuid4().hex[:8]}.png")
            with open(file_path, "wb") as f:
                f.write(base64.b64decode(b64_data))
            return Image.fromFileSystem(file_path)
        else:
            return Image.fromURL(image_url)

    def _get_active_provider(self):
        chain = self.plugin_config.chains.get("text2img", [])
        if chain:
            return self.plugin_config.get_provider(chain[0])
        if self.plugin_config.providers:
            return self.plugin_config.providers[0]
        return None

    @filter.command("切换模型")
    @handle_errors
    async def cmd_switch_model(self, event: AstrMessageEvent, target: str = "") -> AsyncGenerator[Any, None]:
        if not self._has_permission(event):
            yield event.plain_result(f"{MessageEmoji.WARNING} 抱歉，您暂无权限进行此操作！")
            return

        provider = self._get_active_provider()
        if not provider:
            yield event.plain_result(f"{MessageEmoji.WARNING} 尚未配置任何生图节点，请在 WebUI 中添加！")
            return

        models = provider.available_models
        if not models:
            yield event.plain_result(f"{MessageEmoji.WARNING} 当前节点未配置可用模型，请在 WebUI 中用逗号隔开添加！")
            return

        target = target.strip()
        
        if not target:
            current = provider.model
            msg = f"⚙️ 当前节点 [{provider.id}] 的可用模型：\n"
            for i, m in enumerate(models):
                is_active = " 👈 (当前)" if m == current else ""
                msg += f"[{i+1}] {m}{is_active}\n"
            msg += "\n💡 提示：请发送 /切换模型 <序号或名称>"
            yield event.plain_result(msg)
            return

        selected_model = None
        if target.isdigit():
            idx = int(target) - 1
            if 0 <= idx < len(models):
                selected_model = models[idx]
        else:
            if target in models:
                selected_model = target

        if not selected_model:
            yield event.plain_result(f"{MessageEmoji.ERROR} 找不到该模型，请检查输入的序号或名称！")
            return

        provider.model = selected_model
        logger.info(f"🔄 节点 [{provider.id}] 的生图模型已手动切换为: {selected_model}")
        yield event.plain_result(f"✅ 已成功将节点 [{provider.id}] 切换至模型：{selected_model}")

    @filter.command("万象帮助")
    @handle_errors
    async def cmd_help(self, event: AstrMessageEvent) -> AsyncGenerator[Any, None]:
        help_text = "📖 万象画卷 v3.1 帮助\n/画 [提示词]\n/自拍 [动作描述]\n/切换模型 [序号/名称]\n/视频 [提示词]"
        yield event.plain_result(help_text)

    # ==========================================
    # 常规指令区 
    # ==========================================
    @filter.command("画")
    @handle_errors
    async def cmd_draw(self, event: AstrMessageEvent, message: str = "") -> AsyncGenerator[Any, None]:
        if not self._has_permission(event):
            yield event.plain_result(f"{MessageEmoji.WARNING} 抱歉，您暂无画图功能的使用权限哦！")
            return

        message = message.strip()
        raw_refs = self._get_event_images(event)
        
        if not message and not raw_refs:
            yield event.plain_result(f"{MessageEmoji.WARNING} 请输入提示词或附带一张参考图！")
            return
            
        yield event.plain_result(f"{MessageEmoji.PAINTING} 收到灵感，正在处理资源并绘制...")
        start_time = time.perf_counter()
        
        user_refs = await self._process_images_to_base64(raw_refs)
        user_ref = user_refs[0] if user_refs else ""
        
        prompt, kwargs = self.cmd_parser.parse(message)
        if user_ref:
            kwargs["user_ref"] = user_ref
            
        async with aiohttp.ClientSession() as session:
            chain_manager = ChainManager(self.plugin_config, session)
            image_url = await chain_manager.run_chain("text2img", prompt, **kwargs)
            
        api_time = time.perf_counter()
        yield event.chain_result([self._create_image_component(image_url)])
        end_time = time.perf_counter()
        logger.info(f"⏱️ [用时统计 - 指令画图] API 生图耗时: {api_time - start_time:.2f}秒 | 发送总耗时: {end_time - start_time:.2f}秒")

    @filter.command("自拍")
    @handle_errors
    async def cmd_selfie(self, event: AstrMessageEvent, message: str = "") -> AsyncGenerator[Any, None]:
        if not self._has_permission(event):
            yield event.plain_result(f"{MessageEmoji.WARNING} 抱歉，您暂无自拍功能的使用权限哦！")
            return

        user_input = message.strip() if message else "看着镜头微笑"
        final_prompt, extra_kwargs = self.persona_manager.build_persona_prompt(user_input)
        
        yield event.plain_result(f"{MessageEmoji.INFO} 正在为「{self.plugin_config.persona_name}」生成自拍...")
        start_time = time.perf_counter()
        
        raw_refs = self._get_event_images(event)
        user_refs = await self._process_images_to_base64(raw_refs)
        user_ref = user_refs[0] if user_refs else ""
        if user_ref:
            extra_kwargs["user_ref"] = user_ref
            
        chain_to_use = "selfie" if "selfie" in self.plugin_config.chains else "text2img"
        async with aiohttp.ClientSession() as session:
            chain_manager = ChainManager(self.plugin_config, session)
            image_url = await chain_manager.run_chain(chain_to_use, final_prompt, **extra_kwargs)
            
        api_time = time.perf_counter()
        yield event.chain_result([self._create_image_component(image_url)])
        end_time = time.perf_counter()
        logger.info(f"⏱️ [用时统计 - 指令自拍] API 生图耗时: {api_time - start_time:.2f}秒 | 发送总耗时: {end_time - start_time:.2f}秒")

    @filter.command("视频")
    @handle_errors
    async def cmd_video(self, event: AstrMessageEvent, message: str = "") -> AsyncGenerator[Any, None]:
        if not self._has_permission(event):
            yield event.plain_result(f"{MessageEmoji.WARNING} 抱歉，您暂无视频生成功能的使用权限哦！")
            return

        message = message.strip()
        raw_refs = self._get_event_images(event)
        
        if not message and not raw_refs:
            yield event.plain_result(f"{MessageEmoji.WARNING} 请输入视频提示词或附带参考图！")
            return
            
        prompt, _ = self.cmd_parser.parse(message)
        
        yield event.plain_result(f"{MessageEmoji.INFO} 收到！正在下载您的参考图并提交后台任务，请稍候...")
        
        user_refs = await self._process_images_to_base64(raw_refs)
        asyncio.create_task(self.video_manager.background_task_runner(event, prompt, user_refs))


    # ==========================================
    # 🤖 LLM 工具区 (找回丢失的参数解析！)
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
            raw_refs = self._get_event_images(event)
            user_refs = await self._process_images_to_base64(raw_refs)
            if user_refs:
                extra_kwargs["user_ref"] = user_refs[0]
                
            start_time = time.perf_counter()
            chain_to_use = "selfie" if "selfie" in self.plugin_config.chains else "text2img"
            async with aiohttp.ClientSession() as session:
                chain_manager = ChainManager(self.plugin_config, session)
                image_url = await chain_manager.run_chain(chain_to_use, final_prompt, **extra_kwargs)
            
            api_time = time.perf_counter()
            await event.send(event.chain_result([self._create_image_component(image_url)]))
            end_time = time.perf_counter()
            logger.info(f"⏱️ [用时统计 - LLM 自拍] API 生图耗时: {api_time - start_time:.2f}秒 | 发送总耗时: {end_time - start_time:.2f}秒")
            return "系统提示：自拍图片已经物理发送成功。请回复一句话闲聊收尾。"
            
        except Exception as e:
            return f"系统提示：画笔坏了 ({str(e)})。请向用户道歉。"

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
            raw_refs = self._get_event_images(event)
            user_refs = await self._process_images_tobase64(raw_refs)
            if user_refs:
                kwargs["user_ref"] = user_refs[0]
                
            start_time = time.perf_counter()
            async with aiohttp.ClientSession() as session:
                chain_manager = ChainManager(self.plugin_config, session)
                image_url = await chain_manager.run_chain("text2img", prompt, **kwargs)

            api_time = time.perf_counter()
            await event.send(event.chain_result([self._create_image_component(image_url)]))
            end_time = time.perf_counter()
            logger.info(f"⏱️ [用时统计 - LLM 画图] API 生图耗时: {api_time - start_time:.2f}秒 | 发送总耗时: {end_time - start_time:.2f}秒")
            return "系统提示：画好的图已经物理发送成功了。请立刻回复用户一句话完美收尾。"

        except Exception as e:
            return f"系统提示：画笔坏了 ({str(e)})。请向用户道歉。"

    @llm_tool(name="generate_video")
    async def tool_generate_video(self, event: AstrMessageEvent, prompt: str) -> str:
        """
        AI 视频生成工具。当用户提出明确的要求让你生成一段视频(mp4)时调用此工具。
        Args:
            prompt (string): 扩写成英文的高质量视频场景和动作提示词。
        """
        if not self._has_permission(event):
            return "系统提示：当前用户没有权限使用视频功能，请你委婉地拒绝他。"

        try:
            raw_refs = self._get_event_images(event)
            user_refs = await self._process_images_to_base64(raw_refs)
            asyncio.create_task(self.video_manager.background_task_runner(event, prompt, user_refs))
            return "系统提示：视频生成任务已经成功提交到后台！视频正在努力渲染中，让用户先稍等几分钟，做完后会主动发给他。"

        except Exception as e:
            return f"系统提示：视频渲染提交失败 ({str(e)})。请向用户道歉。"
