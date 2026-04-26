"""
视频任务后台挂机引擎 (Background Polling Task)
功能：代替大模型忍受视频生成的漫长耗时，不阻塞聊天通道
"""
import time
import aiohttp
import asyncio
from typing import Optional
from astrbot.api import logger
from astrbot.api.message_components import Video, Plain
from astrbot.api.event import AstrMessageEvent

from ..models import PluginConfig, ProviderConfig

class VideoManager:
    def __init__(self, config: PluginConfig):
        self.config = config

    def _get_active_video_provider(self) -> Optional[ProviderConfig]:
        """获取当前的主力视频节点"""
        chain = self.config.chains.get("video", [])
        if chain:
            return self.config.get_video_provider(chain[0])
        if self.config.video_providers:
            return self.config.video_providers[0]
        return None

    async def _fetch_video_from_api(self, provider: ProviderConfig, prompt: str, image_url: str = "") -> str:
        """
        实际向视频 API 发送请求的底层逻辑。
        注意：目前大多数兼容 OpenAI 的视频站也是走 /v1/images/generations 或者类似的兼容接口。
        （此处兼容大部分标准的 OpenAI 镜像站视频请求格式）
        """
        headers = {
            "Authorization": f"Bearer {provider.api_keys[0]}",
            "Content-Type": "application/json"
        }
        
        # 兼容目前市面上主流的视频模型格式 (如 Grok Video, Runway, Kling等镜像站)
        payload = {
            "model": provider.model,
            "prompt": prompt
        }
        
        # 如果带有参考图 (图生视频)
        if image_url:
            payload["image_url"] = image_url

        endpoint = provider.base_url.rstrip("/") + "/v1/images/generations" # 有的镜像站视频用的也是这个端点，你可根据实际情况修改
        
        async with aiohttp.ClientSession() as session:
            try:
                logger.info(f"🎬 [视频任务发出] 正在请求模型: {provider.model} (这可能需要几分钟...)")
                # 设定长达几分钟的超时时间，因为视频 API 通常是长连接阻塞返回
                async with session.post(endpoint, headers=headers, json=payload, timeout=provider.timeout) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
                    
                    if "data" in data and len(data["data"]) > 0:
                        return data["data"][0].get("url", "")
                    else:
                        raise Exception(f"API 返回数据异常: {data}")
            except Exception as e:
                logger.error(f"❌ 视频生成失败: {e}")
                raise

    async def background_task_runner(self, event: AstrMessageEvent, prompt: str, image_url: str = ""):
        """
        👻 核心幽灵任务：在后台默默执行，不受 LLM 时间限制！
        """
        start_time = time.perf_counter()
        provider = self._get_active_video_provider()
        
        if not provider:
            await event.send(Plain("❌ 抱歉，管理员尚未配置可用的视频渲染节点。"))
            return

        try:
            # 1. 挂机等待 API 生成完毕 (即使卡5分钟，也不会影响大模型聊天)
            video_url = await self._fetch_video_from_api(provider, prompt, image_url)
            
            end_time = time.perf_counter()
            logger.info(f"✅ [视频任务完成] 耗时: {end_time - start_time:.2f} 秒！准备逆向推送给用户。")
            
            # 2. 逆向物理推送：调用框架的底层 API，直接把 mp4 砸到群里
            if video_url:
                await event.send(event.chain_result([
                    Plain("🎬 当当当！你要求的视频渲染完成啦：\n"),
                    Video.fromURL(video_url)
                ]))
            else:
                await event.send(Plain("❌ 视频渲染失败：API 没有返回视频链接。"))

        except Exception as e:
            await event.send(Plain(f"❌ 后台视频渲染引擎发生错误：{str(e)}"))
