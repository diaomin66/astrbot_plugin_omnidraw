"""
AstrBot 万象画卷插件 v1.0.0

功能描述：
- 提供商工厂模块

作者: your_name
版本: 1.0.0
日期: 2026-04-25
"""

import aiohttp
from ..models import ProviderConfig
from ..constants import APIType
from .base import BaseProvider
from .openai_impl import OpenAIProvider

def create_provider(config: ProviderConfig, session: aiohttp.ClientSession) -> BaseProvider:
    """根据配置实例化对应的 Provider"""
    if config.api_type == APIType.OPENAI_IMAGE:
        return OpenAIProvider(config, session)
    else:
        raise NotImplementedError(f"暂不支持该类型的接口: {config.api_type}")