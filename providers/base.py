"""
AstrBot 万象画卷插件 v1.3.0 - Provider 基类
"""
import aiohttp
import base64
import os
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, List
from astrbot.api import logger
from ..models import ProviderConfig

class BaseProvider(ABC):
    # 使用类变量或实例变量存储每个节点的轮询位置
    _key_indices: Dict[str, int] = {}

    def __init__(self, config: ProviderConfig, session: aiohttp.ClientSession):
        self.config = config
        self.session = session
        if self.config.id not in BaseProvider._key_indices:
            BaseProvider._key_indices[self.config.id] = 0

    def get_current_key(self) -> str:
        if not self.config.api_keys:
            return ""
        idx = BaseProvider._key_indices[self.config.id]
        key = self.config.api_keys[idx % len(self.config.api_keys)]
        BaseProvider._key_indices[self.config.id] = (idx + 1) % len(self.config.api_keys)
        return key

    def encode_local_image_to_base64(self, image_path: str) -> Optional[str]:
        """将本地图片文件转为 API 兼容的 Base64 字符串"""
        if not image_path or not os.path.exists(image_path):
            return None
        
        logger.info(f"[{self.config.id}] 正在将本地参考图转为 Base64: {image_path}")
        try:
            with open(image_path, "rb") as image_file:
                encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
                # OpenAI 格式通常需要包含前缀
                return f"data:image/png;base64,{encoded_string}"
        except Exception as e:
            logger.error(f"❌ 读取本地图片失败: {e}")
            return None

    def get_reference_images(self, **kwargs: Any) -> List[str]:
        refs: List[str] = []
        for key in ("user_refs", "persona_refs"):
            value = kwargs.get(key)
            if isinstance(value, (list, tuple)):
                refs.extend(str(item) for item in value if item)

        for key in ("user_ref", "persona_ref"):
            value = kwargs.get(key)
            if value:
                refs.append(str(value))

        seen = set()
        return [ref for ref in refs if not (ref in seen or seen.add(ref))]

    @abstractmethod
    async def generate_image(self, prompt: str, **kwargs: Any) -> str:
        pass
