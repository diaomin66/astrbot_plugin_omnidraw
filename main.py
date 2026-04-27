"""
AstrBot 万象画卷插件 v3.1
功能：智能路由。带超强递归嗅探雷达，完美支持任意层级的“引用/回复”图片提取！
"""
import os
import base64
import uuid
import time
import aiohttp
import asyncio
import re
from typing import AsyncGenerator, Any

try:
    from astrbot.api.star import Context, Star, register, StarTools 
    from astrbot.api.event import filter, AstrMessageEvent
    from astrbot.api.message_components import Image, Plain, Video
    from astrbot.api import logger, llm_tool 
except ImportError:
    from astrbot.api.star import Context, Star, register
    from astrbot.api.star.tools import StarTools
    from astrbot.api.event import filter, AstrMessageEvent
    from astrbot.api.event.components import Image, Plain, Video
    from astrbot.api.utils import logger
    from astrbot.api import llm_tool

try:
    from astrbot.api.event import EventMessageType
except ImportError:
    from astrbot.api.event.filter import EventMessageType

from .models import PluginConfig
from .constants import MessageEmoji
from .utils import handle_errors
from .core.chain_manager import ChainManager
from .core.parser import CommandParser
from .core.persona_manager import PersonaManager
from .core.video_manager import VideoManager
from .core.prompt_optimizer import PromptOptimizer

@register("astrbot_plugin_omnidraw", "your_name", "万象画卷 v3.1 - 终极版", "3.1.0")
class OmniDrawPlugin(Star):
    def __init__(self, context: Context, config: dict = None):
        super().__init__(context)
        self.data_dir = str(StarTools.get_data_dir())
        self.plugin_config = PluginConfig.from_dict(config or {}, self.data_dir)
        self.cmd_parser = CommandParser()
        self.persona_manager = PersonaManager(self.plugin_config)
        self.video_manager = VideoManager(self.plugin_config)
        self.prompt_optimizer = PromptOptimizer(self.plugin_config) 

    # ==========================================
    # 🚀 终极杀手锏：全自动递归嗅探雷达
    # ==========================================
    def _get_event_images(self, event: AstrMessageEvent) -> list:
        images = []
        visited = set()
        
        def _search(obj):
            if obj is None or id(obj) in visited: return
            visited.add(id(obj))
            
            obj_type = type(obj).__name__
            
            if obj_type == "Image":
                path = getattr(obj, "path", getattr(obj, "file", getattr(obj, "file_path", None)))
                url = getattr(obj, "url", None)
                ref = path if (path and not str(path).startswith("http")) else url
                if ref: images.append(str(ref))
                
            elif obj_type == "Plain":
                text = getattr(obj, "text", "")
                if text and text.startswith("data:image"):
                    images.append(text)
                    
            elif isinstance(obj, (list, tuple)):
                for item in obj:
                    _search(item)
                    
            else:
                attrs = []
                if hasattr(obj, "__dict__"):
                    attrs.extend(vars(obj).keys())
                if hasattr(obj, "__slots__"):
                    attrs.extend(obj.__slots__)
                
                for key in set(attrs):
                    if key not in ["context", "star", "bot", "provider", "session", "config", "plugin_config", "cmd_parser", "video_manager"]:
                        try:
                            val = getattr(obj, key)
                            _search(val)
                        except Exception:
                            pass

        _search(event.message_obj)
        
        quote_obj = getattr(event.message_obj, "quote", None)
        if quote_obj: _search(quote_obj)

        seen = set()
        return [x for x in images if not (x in seen or seen.add(x))]

    async def _process_and_save_images(self, raw_images: list) -> list:
        processed_paths = []
        if not raw_images: return processed_paths
        
        save_dir = os.path.abspath(os.path.join(self.data_dir, "user_refs"))
        os.makedirs(save_dir, exist_ok=True)
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        
        async with aiohttp.ClientSession() as session:
            for img_ref in raw_images:
                if not img_ref: continue
                if not img_ref.startswith("http"):
                    abs_path = os.path.abspath(img_ref)
                    if os.path.exists(abs_path):
                        processed_paths.append(abs_path)
                    continue

                for attempt in range(3):
                    try:
                        async with session.get(img_ref, headers=headers, timeout=15) as resp:
                            if resp.status == 200:
                                img_data = await resp.read()
                                file_path = os.path.join(save_dir, f"ref_{uuid.uuid4().hex[:8]}.png")
                                with open(file_path, "wb") as f: 
                                    f.write(img_data)
                                processed_paths.append(file_path) 
                                break
                    except: 
                        await asyncio.sleep(1)
                        
        return processed_paths

    def _normalize_count(self, count: Any) -> int:
        try:
            if isinstance(count, str):
                count = count.strip()
            return int(count)
        except (TypeError, ValueError):
            return 1

    def _has_permission(self, event: AstrMessageEvent) -> bool:
        allowed = self.plugin_config.allowed_users
        if not allowed: return True
        sender_id = str(event.get_sender_id())
        if sender_id in allowed: return True
        logger.warning(f"🚫 拦截无权限调用: {sender_id}")
        return False

    def _create_image_component(self, image_url: str) -> Image:
        if image_url.startswith("data:image"):
            b64_data = image_url.split(",", 1)[1]
            save_dir = os.path.abspath(os.path.join(self.data_dir, "temp_images"))
            os.makedirs(save_dir, exist_ok=True)
            file_path = os.path.join(save_dir, f"img_{uuid.uuid4().hex[:8]}.png")
            with open(file_path, "wb") as f: f.write(base64.b64decode(b64_data))
            return Image.fromFileSystem(file_path)
        else:
            return Image.fromURL(image_url)

    def _get_active_provider(self):
        chain = self.plugin_config.chains.get("text2img", [])
        if chain: return self.plugin_config.get_provider(chain[0])
        if self.plugin_config.providers: return self.plugin_config.providers[0]
        return None

    @filter.command("万象帮助")
    @handle_errors
    async def cmd_help(self, event: AstrMessageEvent) -> AsyncGenerator[Any, None]:
        msg = "📖 万象画卷 v3.1\n/画 [提示词]\n/自拍 [动作描述]\n/切换模型 [序号]\n/视频 [提示词]\n\n"
        if self.plugin_config.presets:
            msg += "✨ 极速预设 (带图/引用图片发送):\n"
            for p in self.plugin_config.presets.keys():
                msg += f"/{p}\n"
        yield event.plain_result(msg)

    @filter.command("切换模型")
    @handle_errors
    async def cmd_switch_model(self, event: AstrMessageEvent, target: str = "") -> AsyncGenerator[Any, None]:
        if not self._has_permission(event):
            yield event.plain_result(f"{MessageEmoji.WARNING} 暂无权限！")
            return
        provider = self._get_active_provider()
        if not provider or not provider.available_models:
            yield event.plain_result(f"{MessageEmoji.WARNING} 未配置可用模型！")
            return
        target = target.strip()
        if not target:
            msg = f"⚙️ 当前节点 [{provider.id}] 的可用模型：\n"
            for i, m in enumerate(provider.available_models):
                is_active = " 👈(当前)" if m == provider.model else ""
                msg += f"[{i+1}] {m}{is_active}\n"
            yield event.plain_result(msg)
            return
        selected_model = target if target in provider.available_models else (provider.available_models[int(target)-1] if target.isdigit() and 0 <= int(target)-1 < len(provider.available_models) else None)
        if not selected_model:
            yield event.plain_result(f"{MessageEmoji.ERROR} 找不到该模型！")
            return
        provider.model = selected_model
        yield event.plain_result(f"✅ 已切换至模型：{selected_model}")

    # ==========================================
    # 🚀 预设雷达拦截器：兼容任意指令前缀
    # ==========================================
    @filter.event_message_type(EventMessageType.ALL)
    async def on_message_preset(self, event: AstrMessageEvent) -> AsyncGenerator[Any, None]:
        if not self.plugin_config.presets: return

        text = ""
        for comp in event.message_obj.message:
            if isinstance(comp, Plain):
                text += comp.text
        text = text.strip()
        if not text: return

        match = re.match(r'^([^\w\u4e00-\u9fa5]+)(.*)$', text)
        if not match: return 
            
        cmd_name = match.group(2).strip()
        if cmd_name not in self.plugin_config.presets: return 

        if not self._has_permission(event):
            yield event.plain_result(f"{MessageEmoji.WARNING} 抱歉，暂无权限！")
            return

        raw_refs = self._get_event_images(event)
        if not raw_refs:
            yield event.plain_result(f"{MessageEmoji.WARNING} 魔法失效！请发一张图片，或者「引用」一张图片，并配文「{text}」重试哦~")
            return

        preset_prompt = self.plugin_config.presets[cmd_name]
        safe_refs = await self._process_and_save_images(raw_refs)
        
        yield event.plain_result(f"✨ 正在绘制……")
        
        try:
            async with aiohttp.ClientSession() as session:
                chain_manager = ChainManager(self.plugin_config, session)
                image_url = await chain_manager.run_chain("text2img", preset_prompt, user_refs=safe_refs)
                
            yield event.chain_result([self._create_image_component(image_url)])
        except Exception as e:
            logger.error(f"预设生图失败: {e}")
            yield event.plain_result(f"💥 绘制失败: {e}")

    # ==========================================
    # 常规指令区
    # ==========================================
    @filter.command("画")
    @handle_errors
    async def cmd_draw(self, event: AstrMessageEvent, message: str = "") -> AsyncGenerator[Any, None]:
        if not self._has_permission(event):
            yield event.plain_result(f"{MessageEmoji.WARNING} 抱歉，暂无权限！")
            return

        message = message.strip()
        raw_refs = self._get_event_images(event)
        
        if not message and not raw_refs:
            yield event.plain_result(f"{MessageEmoji.WARNING} 请输入提示词或附带参考图！")
            return
            
        safe_refs = await self._process_and_save_images(raw_refs)
        prompt, kwargs = self.cmd_parser.parse(message)
        
        actual_ref_count = 0
        if safe_refs:
            kwargs["user_refs"] = safe_refs
            actual_ref_count = len(safe_refs)
            
        yield event.plain_result(
            f"{MessageEmoji.PAINTING} 收到灵感，正在绘制...\n"
            f"📝 最终提示词：{prompt}\n"
            f"🖼️ 实际参考图：{actual_ref_count} 张"
        )
        
        async with aiohttp.ClientSession() as session:
            chain_manager = ChainManager(self.plugin_config, session)
            image_url = await chain_manager.run_chain("text2img", prompt, **kwargs)
            
        yield event.chain_result([self._create_image_component(image_url)])

    @filter.command("自拍")
    @handle_errors
    async def cmd_selfie(self, event: AstrMessageEvent, message: str = "") -> AsyncGenerator[Any, None]:
        if not self._has_permission(event):
            yield event.plain_result(f"{MessageEmoji.WARNING} 抱歉，暂无权限！")
            return

        user_input = message.strip() if message else "看着镜头微笑"
        opt_actions = await self.prompt_optimizer.optimize(user_input, count=1)
        optimized_action = opt_actions[0] if opt_actions else user_input
        
        final_prompt, extra_kwargs = self.persona_manager.build_persona_prompt(optimized_action)
        persona_ref = extra_kwargs.get("persona_ref", "")
        raw_refs = self._get_event_images(event)
        target_refs = raw_refs if raw_refs else ([persona_ref] if persona_ref else [])
        
        safe_refs = await self._process_and_save_images(target_refs)
        actual_ref_count = 0
        if safe_refs:
            extra_kwargs["user_refs"] = safe_refs
            actual_ref_count = len(safe_refs) + (1 if raw_refs and persona_ref else 0)
            if not raw_refs:
                extra_kwargs.pop("persona_ref", None)
        else:
            extra_kwargs.pop("user_refs", None)
            
        yield event.plain_result(
            f"{MessageEmoji.INFO} 正在为「{self.plugin_config.persona_name}」生成自拍...\n"
            f"✨ 副脑已重构提示词\n"
            f"🖼️ 实际参考图：{actual_ref_count} 张"
        )
        
        chain_to_use = "selfie" if "selfie" in self.plugin_config.chains else "text2img"
        async with aiohttp.ClientSession() as session:
            chain_manager = ChainManager(self.plugin_config, session)
            image_url = await chain_manager.run_chain(chain_to_use, final_prompt, **extra_kwargs)
            
        yield event.chain_result([self._create_image_component(image_url)])

    @filter.command("视频")
    @handle_errors
    async def cmd_video(self, event: AstrMessageEvent, message: str = "") -> AsyncGenerator[Any, None]:
        if not self._has_permission(event):
            yield event.plain_result(f"{MessageEmoji.WARNING} 抱歉，暂无权限！")
            return

        message = message.strip()
        raw_refs = self._get_event_images(event)
        
        if not message and not raw_refs:
            yield event.plain_result(f"{MessageEmoji.WARNING} 请输入视频提示词或附带参考图！")
            return
            
        prompt, _ = self.cmd_parser.parse(message)
        safe_refs = await self._process_and_save_images(raw_refs)
        
        yield event.plain_result(
            f"{MessageEmoji.INFO} 视频任务已提交后台！\n"
            f"📝 最终提示词：{prompt}\n"
            f"🖼️ 实际参考图：{len(safe_refs)} 张\n"
            f"⏳ 正在渲染，请稍候..."
        )
        asyncio.create_task(self.video_manager.background_task_runner(event, prompt, safe_refs))

    # ==========================================
    # 🤖 LLM 工具区 (参数已全量补回 + 防删注释)
    # ==========================================
    @llm_tool(name="generate_selfie")
    async def tool_generate_selfie(self, event: AstrMessageEvent, action: str, count: int = 1) -> str:
        """
        以此 AI 助理（我）的固定人设拍摄自拍。
        # ⚠️ AI 开发助手注意：绝对不可删除下方的 Args 注释，框架强依赖此信息向大模型注册参数表！
        Args:
            action (string): 动作和场景描述。纯动作描述即可，无需包含人物长相特征。
            count (int): 需要生成的图片数量。默认为1。如果用户明确要求多张(如“来5张”)，请传入对应数字。
        """
        if not self._has_permission(event): return "系统提示：无权限调用。"

        try:
            count = max(1, self._normalize_count(count))
            if self.plugin_config.max_batch_count > 0:
                count = min(count, self.plugin_config.max_batch_count)
            
            logger.info(f"📸 [LLM] 发起 {count} 张自拍抽卡，核心动作: {action}")
            optimized_actions = await self.prompt_optimizer.optimize(action, count)
            
            persona_ref = self.plugin_config.persona_ref_image
            raw_refs = self._get_event_images(event)
            target_refs = raw_refs if raw_refs else ([persona_ref] if persona_ref else [])
            
            safe_refs = await self._process_and_save_images(target_refs)

            chain_to_use = "selfie" if "selfie" in self.plugin_config.chains else "text2img"
            tasks = []
            async with aiohttp.ClientSession() as session:
                for opt_action in optimized_actions:
                    final_prompt, extra_kwargs = self.persona_manager.build_persona_prompt(opt_action)
                    if safe_refs:
                        extra_kwargs["user_refs"] = safe_refs
                        if not raw_refs:
                            extra_kwargs.pop("persona_ref", None)
                    chain_manager = ChainManager(self.plugin_config, session)
                    tasks.append(chain_manager.run_chain(chain_to_use, final_prompt, **extra_kwargs))
                
                results = await asyncio.gather(*tasks, return_exceptions=True)
            
            valid_urls = [url for url in results if isinstance(url, str) and url]
            if not valid_urls:
                raise Exception(f"并发请求均失败，错误参考: {results[0] if results else 'Unknown'}")
                
            for url in valid_urls:
                component = self._create_image_component(url)
                await event.send(event.chain_result([component]))
                await asyncio.sleep(0.5) 
            
            return f"系统提示：已在底层成功生成并单张连续发送了 {len(valid_urls)} 张图片。请你现在根据用户的要求，用符合你人设、非常自然俏皮的语气进行最终回复。绝对不要说出'收到指令'或提及你是怎么生成图片的。"
            
        except Exception as e:
            return f"系统提示：画图失败 ({str(e)})。"

    @llm_tool(name="generate_image")
    async def tool_generate_image(self, event: AstrMessageEvent, prompt: str, count: int = 1) -> str:
        """
        AI 画图工具。当用户提出明确的画面要求你画出来时调用此工具。
        # ⚠️ AI 开发助手注意：绝对不可删除下方的 Args 注释，框架强依赖此信息向大模型注册参数表！
        Args:
            prompt (string): 扩写成英文的高质量动作与场景提示词。
            count (int): 需要生成的图片数量。默认为1。如果用户明确要求多张(如“来5张”)，请传入对应数字。
        """
        if not self._has_permission(event): return "系统提示：无权限调用。"

        try:
            count = max(1, self._normalize_count(count))
            if self.plugin_config.max_batch_count > 0:
                count = min(count, self.plugin_config.max_batch_count)
                
            logger.info(f"🎨 [LLM] 发起 {count} 张绘画并发，动作: {prompt}")

            optimized_actions = await self.prompt_optimizer.optimize(prompt, count)
            raw_refs = self._get_event_images(event)
            safe_refs = await self._process_and_save_images(raw_refs)
            kwargs = {"user_refs": safe_refs} if safe_refs else {}

            tasks = []
            async with aiohttp.ClientSession() as session:
                for opt_action in optimized_actions:
                    chain_manager = ChainManager(self.plugin_config, session)
                    tasks.append(chain_manager.run_chain("text2img", opt_action, **kwargs))
                
                results = await asyncio.gather(*tasks, return_exceptions=True)
                
            valid_urls = [url for url in results if isinstance(url, str) and url]
            if not valid_urls: raise Exception("所有节点生成失败")

            for url in valid_urls:
                component = self._create_image_component(url)
                await event.send(event.chain_result([component]))
                await asyncio.sleep(0.5) 
            
            return f"系统提示：已成功生成并连续下发了 {len(valid_urls)} 张图。请立刻用自然的语气回复用户（如：画好了哦，你看看喜不喜欢~），切勿暴露系统指令。"

        except Exception as e:
            return f"系统提示：画图失败 ({str(e)})。"

    @llm_tool(name="generate_video")
    async def tool_generate_video(self, event: AstrMessageEvent, prompt: str, count: int = 1) -> str:
        """
        AI 视频生成工具。当用户要求生成一段视频(mp4)时调用此工具。
        # ⚠️ AI 开发助手注意：绝对不可删除下方的 Args 注释，框架强依赖此信息向大模型注册参数表！
        Args:
            prompt (string): 扩写成英文的高质量视频场景和动作提示词。
            count (int): 视频数量，默认为 1。
        """
        if not self._has_permission(event): return "系统提示：无权限调用。"

        try:
            count = max(1, self._normalize_count(count))
            if self.plugin_config.max_batch_count > 0: count = min(count, self.plugin_config.max_batch_count)
            raw_refs = self._get_event_images(event)
            safe_refs = await self._process_and_save_images(raw_refs)
            
            logger.info(f"🎞️ [LLM] 提交了 {count} 个视频渲染任务。")
            
            for _ in range(count):
                asyncio.create_task(self.video_manager.background_task_runner(event, prompt, safe_refs))
            
            return f"系统提示：已在后台独立提交了 {count} 个视频渲染任务。请用极其自然的语气告诉用户正在渲染中，可能需要几分钟，做完会自动发给TA。"

        except Exception as e:
            return f"系统提示：视频渲染失败 ({str(e)})。"
