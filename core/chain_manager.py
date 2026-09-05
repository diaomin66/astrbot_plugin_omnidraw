"""兜底链路调度器。"""

import time
from dataclasses import dataclass
from typing import Any

import aiohttp
from astrbot.api import logger
from ..constants import APIType
from ..models import PluginConfig
from ..providers import create_provider


@dataclass(frozen=True)
class ChainRunResult:
    image_url: str
    provider_id: str
    model: str
    elapsed_seconds: float


class ChainManager:
    def __init__(self, config: PluginConfig, session: aiohttp.ClientSession):
        self.config = config
        self.session = session

    async def run_chain(self, chain_name: str, prompt: str, **kwargs: Any) -> str:
        result = await self.run_chain_with_metadata(chain_name, prompt, **kwargs)
        return result.image_url

    def _effective_request_model(self, default_model: str, kwargs: Any) -> str:
        override = kwargs.get("model") if isinstance(kwargs, dict) else None
        return str(override or default_model or "").strip()

    def _apply_provider_defaults(self, provider_config: Any, kwargs: Any) -> dict:
        request_kwargs = dict(kwargs or {})
        if str(request_kwargs.get("size", "") or "").strip():
            return request_kwargs
        if str(request_kwargs.get("resolution", "") or "").strip():
            return request_kwargs

        default_size = str(getattr(provider_config, "default_size", "") or "").strip()
        if default_size:
            request_kwargs["size"] = default_size
        return request_kwargs

    async def run_chain_with_metadata(self, chain_name: str, prompt: str, **kwargs: Any) -> ChainRunResult:
        raw_chain = self.config.chains.get(chain_name)
        chain = []
        seen = set()
        for provider_id in raw_chain or []:
            provider_id = str(provider_id).strip()
            if provider_id and provider_id not in seen:
                seen.add(provider_id)
                chain.append(provider_id)
        if not chain:
            raise ValueError(f"未找到链路配置: {chain_name}")

        last_error = None
        skipped_errors = []
        start_time = time.perf_counter()

        for provider_id in chain:
            provider_config = self.config.get_provider(provider_id)
            if not provider_config:
                skipped_errors.append(f"{provider_id}: 节点不存在")
                logger.warning(f"⚠️ 链路 [{chain_name}] 中的节点 [{provider_id}] 不存在。")
                continue
            if (
                (not provider_config.base_url or not provider_config.model)
                and provider_config.api_type != APIType.GEMINI_OFFICIAL
            ):
                skipped_errors.append(f"{provider_id}: 缺少接口地址或模型")
                logger.warning(f"⚠️ 链路 [{chain_name}] 中的节点 [{provider_id}] 缺少接口地址或模型。")
                continue
            if not provider_config.has_api_key:
                skipped_errors.append(f"{provider_id}: 未配置 API Key")
                logger.warning(f"⚠️ 链路 [{chain_name}] 中的节点 [{provider_id}] 未配置 API Key。")
                continue

            logger.info(f"🚀 [Chain] 正在将任务交由节点 [{provider_id}] 处理...")
            try:
                provider = create_provider(provider_config, self.session)
                request_kwargs = self._apply_provider_defaults(provider_config, kwargs)
                result = await provider.generate_image(prompt, **request_kwargs)
                logger.info(f"✅ [Chain] 节点 [{provider_id}] 创作成功！")
                return ChainRunResult(
                    image_url=result,
                    provider_id=provider_id,
                    model=self._effective_request_model(provider_config.model, request_kwargs),
                    elapsed_seconds=time.perf_counter() - start_time,
                )

            except Exception as e:
                # 增强日志捕获
                error_detail = repr(e)
                last_error = error_detail
                logger.error(f"❌ [Chain] 节点 [{provider_id}] 发生异常: {error_detail}", exc_info=True)
                logger.warning("🔄 正在尝试切换到下一个备用节点...")
                continue

        failure_detail = last_error or "；".join(skipped_errors) or "没有可尝试的有效节点"
        raise RuntimeError(f"所有节点均已失败！最后一次报错内容: {failure_detail}")
