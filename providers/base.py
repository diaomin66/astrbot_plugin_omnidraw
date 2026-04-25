"""
AstrBot 万象画卷插件 v1.0.0

功能描述：
- Provider 抽象基类

作者: your_name
版本: 1.0.0
日期: 2026-04-25
"""

import aiohttp
from abc import ABC, abstractmethod
from typing import Any
from ..models import ProviderConfig

class BaseProvider(ABC):
    """所有绘图 API 提供商的基类"""
    
    def __init__(self, config: ProviderConfig, session: aiohttp.ClientSession):
        self.config = config
        self.session = session

    @abstractmethod
    async def generate_image(self, prompt: str, **kwargs: Any) -> str:
        """
        统一的生成图像接口
        """
        pass