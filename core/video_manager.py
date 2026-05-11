"""视频任务后台渲染与轮询引擎。"""
import asyncio
import base64
import os
import re
import time
from typing import Any, Dict, List, Optional

import aiohttp
from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent
from astrbot.api.message_components import Plain, Video

from ..models import PluginConfig, ProviderConfig
from ..providers.base import build_chat_completions_endpoint, build_video_generations_endpoint, guess_image_content_type, next_api_key


class VideoTaskError(Exception):
    pass


class VideoManager:
    def __init__(self, config: PluginConfig):
        self.config = config

    def _get_video_provider_chain(self) -> List[ProviderConfig]:
        chain = self.config.chains.get("video", [])
        providers: List[ProviderConfig] = []
        seen = set()
        for provider_id in chain:
            if provider_id in seen:
                continue
            seen.add(provider_id)
            provider = self.config.get_video_provider(provider_id)
            if provider:
                providers.append(provider)
            else:
                logger.warning(f"⚠️ 视频链路中的节点 [{provider_id}] 不存在。")
        if providers:
            return providers
        return self.config.video_providers[:1] if self.config.video_providers else []

    def _get_api_key(self, provider: ProviderConfig) -> str:
        api_key = next_api_key(provider.id, provider.api_keys)
        if not api_key:
            raise VideoTaskError(f"视频节点 {provider.id} 未配置 API Key。")
        return api_key

    def _extract_url(self, text: str) -> str:
        match = re.search(r"(https?://[^\s\]\)\"']+)", text or "")
        return match.group(1) if match else text

    def _chat_endpoint(self, base_url: str) -> str:
        return build_chat_completions_endpoint(base_url)

    async def _encode_image_to_base64(self, image_ref: str, session: aiohttp.ClientSession) -> str:
        try:
            content_type = ""
            if image_ref.startswith("data:image"):
                return image_ref
            if image_ref.startswith("http"):
                logger.info("📥 正在下载视频参考图并转码 Base64...")
                headers = {"User-Agent": "Mozilla/5.0"}
                async with session.get(image_ref, headers=headers, timeout=15) as response:
                    if response.status != 200:
                        logger.warning(f"视频参考图下载失败，状态码: {response.status}")
                        return ""
                    image_bytes = await response.read()
                    content_type = guess_image_content_type(image_ref, response.headers.get("Content-Type", ""))
            elif os.path.exists(image_ref):
                with open(image_ref, "rb") as file:
                    image_bytes = file.read()
                content_type = guess_image_content_type(image_ref)
            else:
                logger.warning(f"视频参考图不存在: {image_ref}")
                return ""
            return f"data:{content_type};base64," + base64.b64encode(image_bytes).decode("utf-8")
        except Exception as exc:
            logger.error(f"❌ 图片转 Base64 失败 ({image_ref}): {exc}")
            return ""

    async def _read_error(self, response: aiohttp.ClientResponse) -> str:
        try:
            text = await response.text()
        except Exception:
            return f"HTTP {response.status}"
        return f"HTTP {response.status}: {text[:1000]}"

    async def _poll_task_result(self, provider: ProviderConfig, task_id: str, session: aiohttp.ClientSession) -> str:
        endpoint = build_video_generations_endpoint(provider.base_url)
        poll_url = f"{endpoint}/{task_id}"
        headers = {
            "Authorization": f"Bearer {self._get_api_key(provider)}",
            "Content-Type": "application/json",
        }
        max_retries = max(1, int(provider.timeout) // 10)

        for attempt in range(max_retries):
            await asyncio.sleep(10)
            try:
                async with session.get(poll_url, headers=headers, timeout=15) as response:
                    if response.status >= 400:
                        logger.warning(f"⚠️ 轮询请求失败: {await self._read_error(response)}")
                        continue
                    data = await response.json()

                status = str(data.get("status", data.get("task_status", ""))).upper()
                logger.info(f"⏳ [视频轮询] Task ID: {task_id}, 状态: {status} (尝试 {attempt + 1}/{max_retries})")

                if status in {"SUCCESS", "SUCCEEDED", "COMPLETED"}:
                    video_url = self._extract_video_url(data)
                    if video_url:
                        return video_url
                    raise VideoTaskError(f"任务显示成功，但未找到视频 URL。API 返回数据: {data}")

                if status in {"FAIL", "FAILED", "FAILURE"}:
                    error_msg = data.get("error", data.get("message", "未知失败原因"))
                    if isinstance(error_msg, dict):
                        error_msg = error_msg.get("message", str(error_msg))
                    raise VideoTaskError(f"平台反馈：{error_msg}")
            except VideoTaskError:
                raise
            except Exception as exc:
                logger.warning(f"⚠️ 轮询请求状态异常，跳过本次: {exc}")

        raise VideoTaskError(f"视频生成轮询超时，已达到设置的 {provider.timeout} 秒最大等待时间。")

    def _extract_video_url(self, data: Dict[str, Any]) -> str:
        video_url = data.get("video_url", data.get("url", data.get("output", "")))
        if video_url:
            return self._extract_url(str(video_url))
        data_field = data.get("data")
        if isinstance(data_field, list) and data_field:
            item = data_field[0]
            if isinstance(item, dict):
                return self._extract_url(str(item.get("url", item.get("output", item.get("video_url", "")))))
        if isinstance(data_field, dict):
            return self._extract_url(str(data_field.get("output", data_field.get("url", data_field.get("video_url", "")))))
        return ""

    async def _fetch_video_from_api(
        self,
        provider: ProviderConfig,
        prompt: str,
        session: aiohttp.ClientSession,
        image_urls: Optional[List[str]] = None,
        api_kwargs: Optional[Dict[str, Any]] = None,
    ) -> str:
        image_urls = image_urls or []
        api_kwargs = api_kwargs or {}
        if not provider.base_url or not provider.model:
            raise VideoTaskError(f"视频节点 {provider.id} 缺少接口地址或模型。")

        headers = {
            "Authorization": f"Bearer {self._get_api_key(provider)}",
            "Content-Type": "application/json",
        }
        base_url = provider.base_url.rstrip("/")
        api_type = str(provider.api_type).strip()
        endpoint = build_video_generations_endpoint(base_url)
        b64_images = []
        for image_url in image_urls:
            b64_image = await self._encode_image_to_base64(image_url, session)
            if b64_image:
                b64_images.append(b64_image)

        if api_type.startswith("async_task"):
            payload = {"model": provider.model, "prompt": prompt}
            if b64_images:
                payload["images"] = b64_images
            payload.update(api_kwargs)

            logger.info(f"🎬 [Async Task 模式] 提交视频任务至: {endpoint}")
            async with session.post(endpoint, headers=headers, json=payload, timeout=30) as response:
                if response.status >= 400:
                    raise VideoTaskError(await self._read_error(response))
                data = await response.json()

            task_id = data.get("id") or data.get("task_id")
            if not task_id and isinstance(data.get("data"), dict):
                task_id = data["data"].get("task_id") or data["data"].get("id")
            if not task_id:
                raise VideoTaskError(f"提交成功但未找到任务 ID。API 原始返回: {data}")

            logger.info(f"✅ 任务提交成功，获得 Task ID: {task_id}，即将进入轮询。")
            return await self._poll_task_result(provider, str(task_id), session)

        if api_type.startswith("openai_sync"):
            payload = {"model": provider.model, "prompt": prompt}
            if b64_images:
                payload["images"] = b64_images
                payload["image_url"] = b64_images[0]
            payload.update(api_kwargs)

            logger.info(f"🎬 [Sync 模式] 阻塞请求视频至: {endpoint}")
            async with session.post(endpoint, headers=headers, json=payload, timeout=provider.timeout) as response:
                if response.status >= 400:
                    raise VideoTaskError(await self._read_error(response))
                data = await response.json()
            video_url = self._extract_video_url(data)
            if video_url:
                return video_url
            raise VideoTaskError(f"Generations 同步返回值异常，未找到视频链接: {data}")

        if api_type.startswith("openai_chat"):
            endpoint = self._chat_endpoint(base_url)
            content = [{"type": "text", "text": prompt}]
            for b64_image in b64_images:
                content.append({"type": "image_url", "image_url": {"url": b64_image}})
            payload = {"model": provider.model, "messages": [{"role": "user", "content": content}]}
            payload.update(api_kwargs)

            logger.info(f"🎬 [Chat 模式] 请求视频至: {endpoint}")
            async with session.post(endpoint, headers=headers, json=payload, timeout=provider.timeout) as response:
                if response.status >= 400:
                    raise VideoTaskError(await self._read_error(response))
                data = await response.json()
            if data.get("choices"):
                raw_content = data["choices"][0].get("message", {}).get("content", "")
                return self._extract_url(str(raw_content))
            raise VideoTaskError(f"Chat 返回值异常: {data}")

        raise VideoTaskError(f"不受支持的接口模式: {api_type}，请在后台重新选择调用协议。")

    async def background_task_runner(
        self,
        event: AstrMessageEvent,
        prompt: str,
        image_urls: Optional[List[str]] = None,
        api_kwargs: Optional[Dict[str, Any]] = None,
    ) -> None:
        start_time = time.perf_counter()
        providers = self._get_video_provider_chain()
        if not providers:
            await event.send(event.plain_result("❌ 抱歉，管理员尚未配置可用的视频渲染节点。"))
            return

        last_error = ""
        try:
            async with aiohttp.ClientSession() as session:
                for index, provider in enumerate(providers, start=1):
                    logger.info(f"🎬 [视频链路] 正在尝试节点 [{provider.id}] ({index}/{len(providers)})。")
                    try:
                        video_url = await self._fetch_video_from_api(provider, prompt, session, image_urls, api_kwargs)
                        elapsed = time.perf_counter() - start_time
                        logger.info(f"✅ [视频任务完成] 节点 [{provider.id}] 成功，耗时: {elapsed:.2f} 秒，准备推送给用户。")

                        if not video_url:
                            raise VideoTaskError("API 没有返回有效视频链接。")
                        await event.send(event.chain_result([
                            Plain(f"🎬 当当当！历时 {int(elapsed)} 秒，你要求的视频渲染完成啦：\n"),
                            Video.fromURL(video_url),
                        ]))
                        return
                    except VideoTaskError as exc:
                        last_error = f"{provider.id}: {exc}"
                        logger.error(f"❌ [视频链路] 节点 [{provider.id}] 失败: {exc}")
                        if index < len(providers):
                            logger.warning("🔄 正在切换到下一个视频备用节点...")

            raise VideoTaskError(f"所有视频节点均失败。最后一次错误：{last_error or '未知错误'}")
        except VideoTaskError as exc:
            logger.error(f"❌ [后台任务] 视频生成失败: {exc}")
            try:
                await event.send(event.plain_result(f"❌ 视频生成失败: {exc}"))
            except Exception as send_exc:
                logger.error(f"⚠️ 无法将失败消息发送回聊天界面: {send_exc}")
        except Exception as exc:
            logger.error(f"❌ [后台任务] 渲染引擎发生异常: {exc}", exc_info=True)
            try:
                await event.send(event.plain_result(f"❌ 后台视频渲染引擎发生错误：{exc}"))
            except Exception as send_exc:
                logger.error(f"⚠️ 无法将失败消息发送回聊天界面: {send_exc}")
