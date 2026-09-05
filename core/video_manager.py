"""视频任务后台渲染与轮询引擎。"""
import asyncio
import base64
import binascii
import math
import os
import re
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlsplit

import aiohttp
from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent
from astrbot.api.message_components import Plain, Video

from ..models import PluginConfig, ProviderConfig
from ..providers.base import (
    MAX_REFERENCE_IMAGE_BYTES,
    _validate_image_payload,
    _validate_remote_reference_url,
    build_chat_completions_endpoint,
    build_video_generations_endpoint,
    extract_error_message,
    filter_provider_api_kwargs,
    guess_image_content_type,
    next_api_key,
    read_response_text_limited,
    summarize_payload_json_for_log,
)


REFERENCE_IMAGE_CHUNK_BYTES = 64 * 1024
VIDEO_POLL_INTERVAL_SECONDS = 10.0


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
        scope = f"video:{provider.api_type}:{provider.base_url}"
        api_key = next_api_key(provider.id, provider.api_keys, scope=scope)
        if not api_key:
            raise VideoTaskError(f"视频节点 {provider.id} 未配置 API Key。")
        return api_key

    def _extract_url(self, text: str) -> str:
        match = re.search(r"(https?://[^\s\]\)\"']+)", text or "")
        if not match:
            return ""
        candidate = match.group(1).rstrip(".,;:!?，。；：！？>")
        parsed = urlsplit(candidate)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return ""
        return candidate

    def _chat_endpoint(self, base_url: str) -> str:
        return build_chat_completions_endpoint(base_url)

    def _format_elapsed(self, elapsed_seconds: float) -> str:
        seconds = max(0.0, float(elapsed_seconds or 0.0))
        return f"{seconds:.1f}s"

    def _safe_error_text(self, value: Any) -> str:
        return extract_error_message(str(value or "")) or "未知错误"

    def _build_success_text(self, elapsed_seconds: float, model: str, include_metadata: bool = True) -> str:
        lines = ["🎬 当当当！你要求的视频渲染完成啦："]
        if include_metadata and getattr(self.config, "show_generation_time", False):
            lines.append(f"⏱️ 生成耗时：{self._format_elapsed(elapsed_seconds)}")
        if include_metadata and getattr(self.config, "show_request_model", False) and str(model or "").strip():
            lines.append(f"🤖 请求模型：{str(model).strip()}")
        return "\n".join(lines) + "\n"

    def _effective_request_model(self, provider: ProviderConfig, api_kwargs: Optional[Dict[str, Any]]) -> str:
        api_kwargs = api_kwargs if isinstance(api_kwargs, dict) else {}
        return str(api_kwargs.get("model") or provider.model or "").strip()

    def _apply_provider_defaults(
        self,
        provider: ProviderConfig,
        api_kwargs: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        request_kwargs = dict(api_kwargs or {})
        if str(request_kwargs.get("size", "") or "").strip():
            return request_kwargs
        if str(request_kwargs.get("resolution", "") or "").strip():
            return request_kwargs

        default_size = str(getattr(provider, "default_size", "") or "").strip()
        if default_size:
            request_kwargs["size"] = default_size
        return request_kwargs

    async def _encode_image_to_base64(self, image_ref: str, session: aiohttp.ClientSession) -> str:
        try:
            content_type = ""
            if image_ref.startswith("data:image"):
                header, separator, encoded = image_ref.partition(",")
                if not separator or ";base64" not in header.lower():
                    raise VideoTaskError("视频参考图 Data URL 格式无效。")
                compact_encoded = "".join(encoded.split())
                max_encoded_length = ((MAX_REFERENCE_IMAGE_BYTES + 2) // 3) * 4
                if len(compact_encoded) > max_encoded_length:
                    raise VideoTaskError(
                        f"视频参考图超过 {MAX_REFERENCE_IMAGE_BYTES // (1024 * 1024)} MB 大小上限。"
                    )
                try:
                    decoded = base64.b64decode(compact_encoded, validate=True)
                except (binascii.Error, ValueError) as exc:
                    raise VideoTaskError("视频参考图 Data URL 的 Base64 数据无效。") from exc
                if len(decoded) > MAX_REFERENCE_IMAGE_BYTES:
                    raise VideoTaskError(
                        f"视频参考图超过 {MAX_REFERENCE_IMAGE_BYTES // (1024 * 1024)} MB 大小上限。"
                    )
                mime_type = header[5:].split(";", 1)[0].strip() or "image/png"
                _validate_image_payload(decoded, mime_type, "data URL")
                return image_ref
            if image_ref.lower().startswith(("http://", "https://")):
                logger.info("📥 正在下载视频参考图并转码 Base64...")
                headers = {"User-Agent": "Mozilla/5.0"}
                current_url = image_ref
                for redirect_count in range(4):
                    await asyncio.to_thread(_validate_remote_reference_url, current_url)
                    async with session.get(
                        current_url,
                        headers=headers,
                        timeout=15,
                        allow_redirects=False,
                    ) as response:
                        if 300 <= response.status < 400:
                            location = str(response.headers.get("Location", "") or "").strip()
                            if not location or redirect_count >= 3:
                                raise VideoTaskError("视频参考图重定向次数过多或缺少目标地址")
                            current_url = urljoin(current_url, location)
                            continue
                        if response.status != 200:
                            raise VideoTaskError(f"视频参考图下载失败，状态码: {response.status}")
                        response_headers = getattr(response, "headers", {}) or {}
                        content_length = response_headers.get("Content-Length", "")
                        if content_length:
                            try:
                                if int(content_length) > MAX_REFERENCE_IMAGE_BYTES:
                                    raise VideoTaskError(
                                        f"视频参考图超过 {MAX_REFERENCE_IMAGE_BYTES // (1024 * 1024)} MB 大小上限。"
                                    )
                            except ValueError:
                                pass
                        response_content = getattr(response, "content", None)
                        if response_content is not None and hasattr(response_content, "iter_chunked"):
                            chunks = bytearray()
                            async for chunk in response_content.iter_chunked(REFERENCE_IMAGE_CHUNK_BYTES):
                                if len(chunks) + len(chunk) > MAX_REFERENCE_IMAGE_BYTES:
                                    raise VideoTaskError(
                                        f"视频参考图超过 {MAX_REFERENCE_IMAGE_BYTES // (1024 * 1024)} MB 大小上限。"
                                    )
                                chunks.extend(chunk)
                            image_bytes = bytes(chunks)
                        else:
                            image_bytes = await response.read()
                            if len(image_bytes) > MAX_REFERENCE_IMAGE_BYTES:
                                raise VideoTaskError(
                                    f"视频参考图超过 {MAX_REFERENCE_IMAGE_BYTES // (1024 * 1024)} MB 大小上限。"
                                )
                        content_type = guess_image_content_type(current_url, response_headers.get("Content-Type", ""))
                        _validate_image_payload(image_bytes, content_type, current_url)
                        break
                else:
                    raise VideoTaskError("视频参考图重定向次数过多")
            elif os.path.exists(image_ref):
                if os.path.islink(image_ref):
                    raise VideoTaskError("视频参考图不允许使用符号链接")
                if os.path.getsize(image_ref) > MAX_REFERENCE_IMAGE_BYTES:
                    raise VideoTaskError(
                        f"视频参考图超过 {MAX_REFERENCE_IMAGE_BYTES // (1024 * 1024)} MB 大小上限。"
                    )
                with open(image_ref, "rb") as file:
                    image_bytes = file.read()
                if len(image_bytes) > MAX_REFERENCE_IMAGE_BYTES:
                    raise VideoTaskError(
                        f"视频参考图超过 {MAX_REFERENCE_IMAGE_BYTES // (1024 * 1024)} MB 大小上限。"
                    )
                content_type = guess_image_content_type(image_ref)
                _validate_image_payload(image_bytes, content_type, image_ref)
            else:
                raise VideoTaskError(f"视频参考图不存在: {image_ref}")
            return f"data:{content_type};base64," + base64.b64encode(image_bytes).decode("utf-8")
        except asyncio.CancelledError:
            raise
        except VideoTaskError:
            raise
        except Exception as exc:
            logger.error(f"❌ 图片转 Base64 失败 ({image_ref}): {exc}")
            raise VideoTaskError(f"视频参考图读取失败: {exc}") from exc

    async def _read_error(self, response: aiohttp.ClientResponse) -> str:
        try:
            text = await read_response_text_limited(response, max_bytes=1024 * 1024)
        except Exception:
            return f"HTTP {response.status}"
        message = extract_error_message(text)
        return f"HTTP {response.status}: {message}" if message else f"HTTP {response.status}"

    async def _poll_task_result(
        self,
        provider: ProviderConfig,
        task_id: str,
        session: aiohttp.ClientSession,
        api_key: Optional[str] = None,
    ) -> str:
        endpoint = build_video_generations_endpoint(provider.base_url)
        poll_url = f"{endpoint}/{task_id}"
        headers = {
            "Authorization": f"Bearer {api_key or self._get_api_key(provider)}",
            "Content-Type": "application/json",
        }
        timeout_seconds = float(provider.timeout)
        if not math.isfinite(timeout_seconds):
            raise VideoTaskError(f"视频节点 {provider.id} 的超时时间必须是有限数值。")
        timeout_seconds = max(0.0, timeout_seconds)
        deadline = asyncio.get_running_loop().time() + timeout_seconds
        attempt = 0
        consecutive_errors = 0

        async def request_once(request_timeout: float) -> Optional[Dict[str, Any]]:
            async with session.get(poll_url, headers=headers, timeout=min(15.0, request_timeout)) as response:
                if response.status >= 400:
                    logger.warning(f"⚠️ 轮询请求失败: {await self._read_error(response)}")
                    return None
                data = await response.json()
            if not isinstance(data, dict):
                raise ValueError("视频轮询接口返回的 JSON 不是对象。")
            return data

        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                break
            if attempt:
                await asyncio.sleep(min(VIDEO_POLL_INTERVAL_SECONDS, remaining))
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    break
            attempt += 1
            try:
                data = await asyncio.wait_for(request_once(remaining), timeout=remaining)
                if data is None:
                    consecutive_errors += 1
                    if consecutive_errors >= 3:
                        raise VideoTaskError("视频轮询连续请求失败。")
                    continue

                consecutive_errors = 0
                status = str(data.get("status", data.get("task_status", ""))).upper()
                logger.info(f"⏳ [视频轮询] Task ID: {task_id}, 状态: {status} (尝试 {attempt})")

                if status in {"SUCCESS", "SUCCEEDED", "COMPLETED"}:
                    video_url = self._extract_video_url(data)
                    if video_url:
                        return video_url
                    raise VideoTaskError(
                        "任务显示成功，但未找到视频 URL。API 返回摘要: "
                        + summarize_payload_json_for_log(data, max_string_length=500)
                    )

                if status in {"FAIL", "FAILED", "FAILURE"}:
                    raise VideoTaskError(f"平台反馈：{extract_error_message(data)}")
            except asyncio.CancelledError:
                raise
            except VideoTaskError:
                raise
            except Exception as exc:
                safe_error = extract_error_message(str(exc))
                logger.warning(f"⚠️ 轮询请求状态异常，跳过本次: {safe_error}")
                consecutive_errors += 1
                if consecutive_errors >= 3:
                    raise VideoTaskError(f"视频轮询连续异常: {safe_error}") from exc

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
        api_kwargs = filter_provider_api_kwargs(dict(api_kwargs or {}), provider.id)
        if not provider.base_url or not provider.model:
            raise VideoTaskError(f"视频节点 {provider.id} 缺少接口地址或模型。")
        provider_timeout = float(provider.timeout)
        if not math.isfinite(provider_timeout):
            raise VideoTaskError(f"视频节点 {provider.id} 的超时时间必须是有限数值。")

        api_key = self._get_api_key(provider)
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        base_url = provider.base_url.rstrip("/")
        api_type = str(provider.api_type).strip()
        endpoint = build_video_generations_endpoint(base_url)
        b64_images = []
        for image_url in image_urls:
            b64_image = await self._encode_image_to_base64(image_url, session)
            b64_images.append(b64_image)

        if api_type.startswith("async_task"):
            payload = {"model": provider.model, "prompt": prompt}
            if b64_images:
                payload["images"] = b64_images
            payload.update(api_kwargs)

            logger.info(f"🎬 [Async Task 模式] 提交视频任务至: {endpoint}")
            async with session.post(
                endpoint,
                headers=headers,
                json=payload,
                timeout=min(30.0, max(1.0, provider_timeout)),
            ) as response:
                if response.status >= 400:
                    raise VideoTaskError(await self._read_error(response))
                data = await response.json()
            if not isinstance(data, dict):
                raise VideoTaskError("提交接口返回的 JSON 不是对象。")

            task_id = data.get("id") or data.get("task_id")
            if not task_id and isinstance(data.get("data"), dict):
                task_id = data["data"].get("task_id") or data["data"].get("id")
            if not task_id:
                    raise VideoTaskError(
                        "提交成功但未找到任务 ID。API 返回摘要: "
                        + summarize_payload_json_for_log(data, max_string_length=500)
                    )

            logger.info(f"✅ 任务提交成功，获得 Task ID: {task_id}，即将进入轮询。")
            return await self._poll_task_result(provider, str(task_id), session, api_key=api_key)

        if api_type.startswith("openai_sync"):
            payload = {"model": provider.model, "prompt": prompt}
            if b64_images:
                payload["images"] = b64_images
                payload["image_url"] = b64_images[0]
            payload.update(api_kwargs)

            logger.info(f"🎬 [Sync 模式] 阻塞请求视频至: {endpoint}")
            async with session.post(endpoint, headers=headers, json=payload, timeout=provider_timeout) as response:
                if response.status >= 400:
                    raise VideoTaskError(await self._read_error(response))
                data = await response.json()
            if not isinstance(data, dict):
                raise VideoTaskError("同步接口返回的 JSON 不是对象。")
            video_url = self._extract_video_url(data)
            if video_url:
                return video_url
            raise VideoTaskError(
                "Generations 同步返回值异常，未找到视频链接: "
                + summarize_payload_json_for_log(data, max_string_length=500)
            )

        if api_type.startswith("openai_chat"):
            endpoint = self._chat_endpoint(base_url)
            content = [{"type": "text", "text": prompt}]
            for b64_image in b64_images:
                content.append({"type": "image_url", "image_url": {"url": b64_image}})
            payload = {"model": provider.model, "messages": [{"role": "user", "content": content}]}
            payload.update(api_kwargs)

            logger.info(f"🎬 [Chat 模式] 请求视频至: {endpoint}")
            async with session.post(endpoint, headers=headers, json=payload, timeout=provider_timeout) as response:
                if response.status >= 400:
                    raise VideoTaskError(await self._read_error(response))
                data = await response.json()
            if not isinstance(data, dict):
                raise VideoTaskError("Chat 接口返回的 JSON 不是对象。")
            if data.get("choices"):
                raw_content = data["choices"][0].get("message", {}).get("content", "")
                return self._extract_url(str(raw_content))
            raise VideoTaskError(
                "Chat 返回值异常: " + summarize_payload_json_for_log(data, max_string_length=500)
            )

        raise VideoTaskError(f"不受支持的接口模式: {api_type}，请在后台重新选择调用协议。")

    async def background_task_runner(
        self,
        event: AstrMessageEvent,
        prompt: str,
        image_urls: Optional[List[str]] = None,
        api_kwargs: Optional[Dict[str, Any]] = None,
        include_metadata: bool = True,
    ) -> None:
        start_time = time.perf_counter()
        providers = self._get_video_provider_chain()
        if not providers:
            try:
                await event.send(event.plain_result("❌ 抱歉，管理员尚未配置可用的视频渲染节点。"))
            except asyncio.CancelledError:
                logger.warning("⚠️ [后台任务] 视频任务在发送未配置提示时被取消。")
                raise
            except Exception as send_exc:
                logger.error(f"⚠️ 无法将未配置提示发送回聊天界面: {send_exc}", exc_info=True)
                raise
            return

        last_error = ""
        try:
            async with aiohttp.ClientSession() as session:
                for index, provider in enumerate(providers, start=1):
                    logger.info(f"🎬 [视频链路] 正在尝试节点 [{provider.id}] ({index}/{len(providers)})。")
                    request_kwargs = self._apply_provider_defaults(provider, api_kwargs)
                    try:
                        video_url = await self._fetch_video_from_api(provider, prompt, session, image_urls, request_kwargs)
                        if not video_url:
                            raise VideoTaskError("API 没有返回有效视频链接。")
                    except asyncio.CancelledError:
                        raise
                    except VideoTaskError as exc:
                        safe_error = self._safe_error_text(exc)
                        last_error = f"{provider.id}: {safe_error}"
                        logger.error(f"❌ [视频链路] 节点 [{provider.id}] 失败: {safe_error}")
                        if index < len(providers):
                            logger.warning("🔄 正在切换到下一个视频备用节点...")
                    except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
                        safe_error = self._safe_error_text(exc)
                        last_error = f"{provider.id}: {safe_error}"
                        logger.error(f"❌ [视频链路] 节点 [{provider.id}] 请求或响应异常: {safe_error}")
                        if index < len(providers):
                            logger.warning("🔄 正在切换到下一个视频备用节点...")
                    else:
                        elapsed = time.perf_counter() - start_time
                        logger.info(f"✅ [视频任务完成] 节点 [{provider.id}] 成功，耗时: {elapsed:.2f} 秒，准备推送给用户。")
                        try:
                            await event.send(event.chain_result([
                                Plain(self._build_success_text(
                                    elapsed,
                                    self._effective_request_model(provider, request_kwargs),
                                    include_metadata=include_metadata,
                                )),
                                Video.fromURL(video_url),
                            ]))
                        except asyncio.CancelledError:
                            logger.warning("⚠️ [后台任务] 视频任务在发送成功结果时被取消。")
                            raise
                        except Exception as send_exc:
                            logger.error(
                                f"⚠️ 无法将视频结果发送回聊天界面: {self._safe_error_text(send_exc)}"
                            )
                            raise RuntimeError("视频结果发送失败。") from send_exc
                        return

            raise VideoTaskError(f"所有视频节点均失败。最后一次错误：{last_error or '未知错误'}")
        except asyncio.CancelledError:
            logger.warning("⚠️ [后台任务] 视频生成任务已取消。")
            raise
        except VideoTaskError as exc:
            safe_error = self._safe_error_text(exc)
            logger.error(f"❌ [后台任务] 视频生成失败: {safe_error}")
            try:
                await event.send(event.plain_result(f"❌ 视频生成失败: {safe_error}"))
            except asyncio.CancelledError:
                logger.warning("⚠️ [后台任务] 视频任务在发送失败提示时被取消。")
                raise
            except Exception as send_exc:
                logger.error(f"⚠️ 无法将失败消息发送回聊天界面: {self._safe_error_text(send_exc)}")
        except Exception as exc:
            safe_error = self._safe_error_text(exc)
            logger.error(f"❌ [后台任务] 渲染引擎发生异常: {safe_error}")
            try:
                await event.send(event.plain_result(f"❌ 后台视频渲染引擎发生错误：{safe_error}"))
            except asyncio.CancelledError:
                logger.warning("⚠️ [后台任务] 视频任务在发送引擎错误提示时被取消。")
                raise
            except Exception as send_exc:
                logger.error(f"⚠️ 无法将失败消息发送回聊天界面: {self._safe_error_text(send_exc)}")
