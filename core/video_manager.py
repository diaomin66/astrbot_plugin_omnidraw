"""
视频任务后台挂机引擎 (Background Polling Task)
功能：代替大模型忍受视频生成的漫长耗时，不阻塞聊天通道，支持自动降级轮询接口与多图参考
"""
import re
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

    def _extract_url(self, text: str) -> str:
        """从 chat 接口返回的杂乱文本中精准提取出 URL 链接"""
        match = re.search(r'(https?://[^\s\]\)"\']+)', text)
        return match.group(1) if match else text

    # 🚀 升级：将 image_url (字符串) 升级为 image_urls (列表)
    async def _fetch_video_from_api(self, provider: ProviderConfig, prompt: str, image_urls: list = None) -> str:
        """
        终极健壮版：自动按顺序尝试多个视频接口，并支持不限张数的参考图
        """
        if image_urls is None:
            image_urls = []
            
        headers = {
            "Authorization": f"Bearer {provider.api_keys[0]}",
            "Content-Type": "application/json"
        }
        
        endpoints_to_try = [
            "/v1/chat/completions",
            "/v1/videos/generations",
            "/v1/images/generations"
        ]
        
        last_error = None
        
        async with aiohttp.ClientSession() as session:
            for endpoint_suffix in endpoints_to_try:
                endpoint = provider.base_url.rstrip("/") + endpoint_suffix
                
                # 1. 动态构建 Payload
                if endpoint_suffix == "/v1/chat/completions":
                    # Chat 接口要求 messages 格式，支持多模态多图片拼接
                    content = [{"type": "text", "text": prompt}]
                    for img in image_urls:
                        content.append({"type": "image_url", "image_url": {"url": img}})
                        
                    payload = {
                        "model": provider.model,
                        "messages": [{"role": "user", "content": content}]
                    }
                else:
                    # Generations 接口要求 prompt 格式
                    payload = {
                        "model": provider.model,
                        "prompt": prompt
                    }
                    if image_urls:
                        # 兼容处理：如果只有一张图传字符串，多图传列表
                        payload["image_url"] = image_urls[0] if len(image_urls) == 1 else image_urls

                try:
                    logger.info(f"🎬 [尝试视频接口] 正在请求: {endpoint} (携带 {len(image_urls)} 张参考图)")
                    async with session.post(endpoint, headers=headers, json=payload, timeout=provider.timeout) as resp:
                        resp.raise_for_status() 
                        data = await resp.json()
                        
                        # 2. 动态解析返回值
                        if endpoint_suffix == "/v1/chat/completions":
                            if "choices" in data and len(data["choices"]) > 0:
                                raw_content = data["choices"][0]["message"]["content"]
                                final_url = self._extract_url(raw_content)
                                logger.info(f"✅ 成功从 {endpoint_suffix} 获取视频！")
                                return final_url
                            else:
                                raise Exception(f"Chat返回值异常: {data}")
                        else:
                            if "data" in data and len(data["data"]) > 0:
                                logger.info(f"✅ 成功从 {endpoint_suffix} 获取视频！")
                                return data["data"][0].get("url", "")
                            else:
                                raise Exception(f"Generations返回值异常: {data}")
                                
                except Exception as e:
                    last_error = str(e)
                    logger.warning(f"⚠️ 接口 {endpoint_suffix} 尝试失败: {e}，自动切换下一个...")
                    continue

            logger.error(f"❌ 所有视频接口均尝试失败。最后的错误: {last_error}")
            raise Exception(f"所有接口均不支持该操作。最后错误: {last_error}")

    async def background_task_runner(self, event: AstrMessageEvent, prompt: str, image_urls: list = None):
        """
        👻 核心幽灵任务：在后台默默执行，不受 LLM 时间限制！
        """
        start_time = time.perf_counter()
        provider = self._get_active_video_provider()
        
        if not provider:
            await event.send(Plain("❌ 抱歉，管理员尚未配置可用的视频渲染节点。"))
            return

        try:
            video_url = await self._fetch_video_from_api(provider, prompt, image_urls)
            end_time = time.perf_counter()
            logger.info(f"✅ [视频任务完成] 耗时: {end_time - start_time:.2f} 秒！准备逆向推送给用户。")
            
            if video_url:
                await event.send(event.chain_result([
                    Plain("🎬 当当当！你要求的视频渲染完成啦：\n"),
                    Video.fromURL(video_url)
                ]))
            else:
                await event.send(Plain("❌ 视频渲染失败：API 没有返回视频链接。"))

        except Exception as e:
            await event.send(Plain(f"❌ 后台视频渲染引擎发生错误：{str(e)}"))
