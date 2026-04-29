"""
AstrBot 万象画卷插件 v3.1
功能：支持 Gemini / gptimage2 高阶参数动态透传（指令与LLM全覆盖）
"""
import os
import base64
import uuid
import time
import aiohttp
import asyncio
import re
import json
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

    def _get_active_provider(self, chain_type: str = "text2img"):
        chain = self.plugin_config.chains.get(chain_type, [])
        if chain_type == "video":
            if chain: 
                prov = self.plugin_config.get_video_provider(chain[0])
                if prov: return prov
            if self.plugin_config.video_providers: return self.plugin_config.video_providers[0]
        else:
            if chain: 
                prov = self.plugin_config.get_provider(chain[0])
                if prov: return prov
            if self.plugin_config.providers: return self.plugin_config.providers[0]
        return None

    @filter.command("万象帮助")
    @handle_errors
    async def cmd_help(self, event: AstrMessageEvent) -> AsyncGenerator[Any, None]:
        msg = "📖 万象画卷 v3.1\n/画 [提示词] [--参数名 参数值]\n/自拍 [动作描述]\n/视频 [提示词]\n/切换链路 [画图/自拍/视频] [节点ID]\n/切换模型 [画图/自拍/视频] [序号]\n\n"
        if self.plugin_config.presets:
            msg += "✨ 极速预设 (带图/引用图片发送):\n"
            for p in self.plugin_config.presets.keys():
                msg += f"/{p}\n"
        yield event.plain_result(msg)

    @filter.command("切换链路")
    @handle_errors
    async def cmd_switch_chain(self, event: AstrMessageEvent, target_chain: str = "", target_node: str = "") -> AsyncGenerator[Any, None]:
        try:
            if not self._has_permission(event):
                yield event.plain_result(f"{MessageEmoji.WARNING} 暂无权限！")
                return

            target_chain = str(target_chain).strip()
            target_node = str(target_node).strip()

            chain_map = {"画图": "text2img", "自拍": "selfie", "视频": "video"}

            if not target_chain or target_chain not in chain_map:
                msg = "🔗 当前链路路由状态：\n"
                for cn, ck in chain_map.items():
                    prov = self._get_active_provider(ck)
                    prov_id = prov.id if prov else "未配置"
                    msg += f"[{cn}]: 绑定节点 -> {prov_id}\n"
                
                provider_ids = [p.id for p in self.plugin_config.providers] if self.plugin_config.providers else ["无"]
                video_provider_ids = [p.id for p in self.plugin_config.video_providers] if self.plugin_config.video_providers else ["无"]
                
                msg += "\n🎨 可用生图节点: " + ", ".join(provider_ids)
                msg += "\n🎬 可用视频节点: " + ", ".join(video_provider_ids)
                msg += "\n\n💡 切换指令: /切换链路 [画图/自拍/视频] [节点ID]"
                yield event.plain_result(msg)
                return

            if not target_node:
                yield event.plain_result(f"{MessageEmoji.ERROR} 请输入要切换的节点 ID！例如：/切换链路 {target_chain} 节点名字")
                return

            chain_key = chain_map[target_chain]
            
            new_provider = None
            if chain_key == "video":
                new_provider = self.plugin_config.get_video_provider(target_node)
            else:
                new_provider = self.plugin_config.get_provider(target_node)
                
            if not new_provider:
                yield event.plain_result(f"{MessageEmoji.ERROR} 找不到节点 [{target_node}]！请确认拼写正确。")
                return

            self.plugin_config.chains[chain_key] = [target_node]
            yield event.plain_result(f"✅ 成功将 [{target_chain}] 链路切换至节点: {target_node}\n💡 现在使用 /切换模型 {target_chain} 将显示该节点下的可用模型！")
        except Exception as e:
            logger.error(f"切换链路崩溃: {e}")
            yield event.plain_result(f"💥 内部错误: {e}")

    @filter.command("切换模型")
    @handle_errors
    async def cmd_switch_model(self, event: AstrMessageEvent, arg1: str = "", arg2: str = "") -> AsyncGenerator[Any, None]:
        try:
            if not self._has_permission(event):
                yield event.plain_result(f"{MessageEmoji.WARNING} 暂无权限！")
                return
                
            arg1 = str(arg1).strip()
            arg2 = str(arg2).strip()
            
            target_chain = "画图"
            target_idx = ""
            
            if arg1.isdigit():
                target_idx = arg1
            elif arg1 in ["画图", "自拍", "视频"]:
                target_chain = arg1
                target_idx = arg2
            elif arg1:
                yield event.plain_result(f"{MessageEmoji.ERROR} 无法识别的链路名。支持：画图 / 自拍 / 视频")
                return

            chain_map = {"画图": "text2img", "自拍": "selfie", "视频": "video"}
            chain_key = chain_map[target_chain]
            
            provider = self._get_active_provider(chain_key)

            if not provider or not provider.available_models:
                yield event.plain_result(f"{MessageEmoji.WARNING} [{target_chain}] 链路当前绑定的节点暂无可用模型！")
                return

            if not target_idx:
                msg = f"⚙️ [{target_chain}] 当前节点 [{provider.id}] 的可用模型：\n"
                for i, m in enumerate(provider.available_models):
                    is_active = " 👈(当前)" if m == provider.model else ""
                    msg += f"[{i+1}] {m}{is_active}\n"
                msg += f"\n💡 指令: /切换模型 {target_chain if target_chain != '画图' else ''} [序号]"
                yield event.plain_result(msg)
                return

            selected_model = target_idx if target_idx in provider.available_models else (provider.available_models[int(target_idx)-1] if target_idx.isdigit() and 0 <= int(target_idx)-1 < len(provider.available_models) else None)
            
            if not selected_model:
                yield event.plain_result(f"{MessageEmoji.ERROR} 找不到该序号的模型！")
                return
                
            provider.model = selected_model
            yield event.plain_result(f"✅ [{target_chain}] 已成功切换至模型：{selected_model}")
        except Exception as e:
            logger.error(f"切换模型崩溃: {e}")
            yield event.plain_result(f"💥 内部错误: {e}")

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
    async def cmd_draw(self, event: AstrMessageEvent, p1: str="", p2: str="", p3: str="", p4: str="", p5: str="", p6: str="", p7: str="", p8: str="", p9: str="", p10: str="") -> AsyncGenerator[Any, None]:
        if not self._has_permission(event):
            yield event.plain_result(f"{MessageEmoji.WARNING} 抱歉，暂无权限！")
            return

        message = " ".join(str(x) for x in [p1,p2,p3,p4,p5,p6,p7,p8,p9,p10] if x).strip()
        raw_refs = self._get_event_images(event)
        
        if not message and not raw_refs:
            yield event.plain_result(f"{MessageEmoji.WARNING} 请输入提示词或附带参考图！")
            return
            
        safe_refs = await self._process_and_save_images(raw_refs)
        
        # 🚀 强大的正则解析提取参数
        prompt, kwargs = self.cmd_parser.parse(message)
        
        actual_ref_count = 0
        if safe_refs:
            kwargs["user_refs"] = safe_refs
            actual_ref_count = len(safe_refs)
            
        yield event.plain_result(
            f"{MessageEmoji.PAINTING} 收到灵感，正在绘制...\n"
            f"📝 最终提示词：{prompt}\n"
            f"⚙️ 附加参数：{len(kwargs) - (1 if safe_refs else 0)} 个\n"
            f"🖼️ 实际参考图：{actual_ref_count} 张"
        )
        
        async with aiohttp.ClientSession() as session:
            chain_manager = ChainManager(self.plugin_config, session)
            image_url = await chain_manager.run_chain("text2img", prompt, **kwargs)
            
        yield event.chain_result([self._create_image_component(image_url)])

    @filter.command("自拍")
    @handle_errors
    async def cmd_selfie(self, event: AstrMessageEvent, p1: str="", p2: str="", p3: str="", p4: str="", p5: str="", p6: str="", p7: str="", p8: str="", p9: str="", p10: str="") -> AsyncGenerator[Any, None]:
        if not self._has_permission(event):
            yield event.plain_result(f"{MessageEmoji.WARNING} 抱歉，暂无权限！")
            return

        message = " ".join(str(x) for x in [p1,p2,p3,p4,p5,p6,p7,p8,p9,p10] if x).strip()
        user_input, kwargs = self.cmd_parser.parse(message)
        if not user_input:
            user_input = "看着镜头微笑"
        
        opt_actions = await self.prompt_optimizer.optimize(user_input, count=1)
        optimized_action = opt_actions[0] if opt_actions else user_input
        
        final_prompt, extra_kwargs = self.persona_manager.build_persona_prompt(optimized_action)
        
        # 将用户透传的 kwargs 并入
        extra_kwargs.update(kwargs)
        
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
    async def cmd_video(self, event: AstrMessageEvent, p1: str="", p2: str="", p3: str="", p4: str="", p5: str="", p6: str="", p7: str="", p8: str="", p9: str="", p10: str="") -> AsyncGenerator[Any, None]:
        if not self._has_permission(event):
            yield event.plain_result(f"{MessageEmoji.WARNING} 抱歉，暂无权限！")
            return

        message = " ".join(str(x) for x in [p1,p2,p3,p4,p5,p6,p7,p8,p9,p10] if x).strip()
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
    # 🤖 LLM 工具区 (新增 aspect_ratio 和 size 支持)
    # ==========================================
    @llm_tool(name="generate_selfie")
    async def tool_generate_selfie(self, event: AstrMessageEvent, action: str, count: int = 1, aspect_ratio: str = "", size: str = "") -> str:
        """
        以此 AI 助理（我）的固定人设拍摄自拍。
        # ⚠️ AI 开发助手注意：绝对不可删除下方的 Args 注释，框架强依赖此信息向大模型注册参数表！
        Args:
            action (string): 动作和场景描述。纯动作描述即可，无需包含人物长相特征。
            count (int): 需要生成的图片数量。默认为1。如果用户明确要求多张(如“来5张”)，请传入对应数字。
            aspect_ratio (string): 宽高比例，主要用于 Gemini / gptimage2 / Midjourney。如 "16:9", "1:1", "9:16"。除非用户要求，否则留空。
            size (string): 分辨率，主要用于 DALL-E 系列。如 "1024x1024", "1024x1792"。除非用户要求，否则留空。
        """
        if not self._has_permission(event): return "系统提示：无权限调用。"

        try:
            count = max(1, self._normalize_count(count))
            if self.plugin_config.max_batch_count > 0:
                count = min(count, self.plugin_config.max_batch_count)
            
            logger.info(f"📸 [LLM] 发起 {count} 张自拍抽卡，核心动作: {action}。透传比例:{aspect_ratio} 尺寸:{size}")
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
                            
                    # 🚀 LLM 指定的高级参数注入
                    if aspect_ratio: extra_kwargs["aspect_ratio"] = aspect_ratio
                    if size: extra_kwargs["size"] = size
                            
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
    async def tool_generate_image(self, event: AstrMessageEvent, prompt: str, count: int = 1, aspect_ratio: str = "", size: str = "", extra_params: str = "") -> str:
        """
        AI 画图工具。当用户提出明确的画面要求你画出来时调用此工具。
        # ⚠️ AI 开发助手注意：绝对不可删除下方的 Args 注释，框架强依赖此信息向大模型注册参数表！
        Args:
            prompt (string): 扩写成英文的高质量动作与场景提示词。
            count (int): 需要生成的图片数量。默认为1。如果用户明确要求多张(如“来5张”)，请传入对应数字。
            aspect_ratio (string): 宽高比例，主要用于 Gemini / gptimage2 / Midjourney。如 "16:9", "1:1", "9:16"。除非用户要求横竖屏，否则留空。
            size (string): 分辨率，主要用于 DALL-E 系列。如 "1024x1024", "1024x1792"。除非用户要求尺寸，否则留空。
            extra_params (string): 用户要求指定的风格(--style)或其他参数。以 "--key value" 格式拼合。
        """
        if not self._has_permission(event): return "系统提示：无权限调用。"

        try:
            count = max(1, self._normalize_count(count))
            if self.plugin_config.max_batch_count > 0:
                count = min(count, self.plugin_config.max_batch_count)
                
            logger.info(f"🎨 [LLM] 发起 {count} 张绘画并发。透传比例:{aspect_ratio} 尺寸:{size} 额外:{extra_params}")

            optimized_actions = await self.prompt_optimizer.optimize(prompt, count)
            raw_refs = self._get_event_images(event)
            safe_refs = await self._process_and_save_images(raw_refs)
            kwargs = {"user_refs": safe_refs} if safe_refs else {}
            
            # 🚀 LLM 指定的高级参数注入
            if aspect_ratio: kwargs["aspect_ratio"] = aspect_ratio
            if size: kwargs["size"] = size
            if extra_params:
                _, extra_kwargs = self.cmd_parser.parse(extra_params)
                kwargs.update(extra_kwargs)

            tasks = []
            async with aiohttp.ClientSession() as session:
                for opt_action in optimized_actions:
                    if opt_action.strip().startswith("{") and "HARDCODED_ANTI_COLLAGE_RULE" in opt_action:
                        opt_action = PromptOptimizer.flatten_json_prompt(opt_action)
                        logger.info(f"🔄 [Optimizer] JSON 提示词已转换为自然语言格式")
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
