"""图片 Provider 工厂。"""

import aiohttp
from ..models import ProviderConfig
from ..constants import APIType
from .base import BaseProvider
from .custom_endpoint_impl import CustomEndpointProvider
from .gemini_official_impl import GeminiOfficialProvider
from .openai_impl import OpenAIProvider
from .openai_chat_impl import OpenAIChatProvider
from .stable_diffusion_webui_impl import StableDiffusionWebUIProvider

def create_provider(config: ProviderConfig, session: aiohttp.ClientSession) -> BaseProvider:
    """根据配置实例化对应的 Provider"""
    if config.api_type == APIType.OPENAI_IMAGE:
        return OpenAIProvider(config, session)
    # ===== 加入了 openai_chat 的识别分支 =====
    elif config.api_type == APIType.OPENAI_CHAT:
        return OpenAIChatProvider(config, session)
    elif config.api_type == APIType.GEMINI_OFFICIAL:
        return GeminiOfficialProvider(config, session)
    elif config.api_type == APIType.CUSTOM_ENDPOINT:
        return CustomEndpointProvider(config, session)
    elif config.api_type == APIType.STABLE_DIFFUSION_WEBUI:
        return StableDiffusionWebUIProvider(config, session)
    else:
        raise NotImplementedError(f"暂不支持该类型的接口: {config.api_type}")
