"""
AstrBot 万象画卷插件 v1.0.0

功能描述：
- 数据模型模块

作者: your_name
版本: 1.0.0
日期: 2026-04-25
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
from .constants import APIType

@dataclass
class ProviderConfig:
    """API 提供商配置实体"""
    id: str
    api_type: str = APIType.OPENAI_IMAGE
    base_url: str = ""
    api_key: str = ""
    model: str = ""

@dataclass
class PersonaConfig:
    """人设配置实体"""
    name: str
    base_prompt: str = ""
    ref_image_url: Optional[str] = None

@dataclass
class PluginConfig:
    """全局插件配置"""
    providers: List[ProviderConfig] = field(default_factory=list)
    chains: Dict[str, List[str]] = field(default_factory=dict)
    personas: List[PersonaConfig] = field(default_factory=list)

    @classmethod
    def from_dict(cls, config_dict: Dict[str, Any]) -> "PluginConfig":
        """从字典创建配置实例"""
        providers_data = config_dict.get("providers", [])
        providers = [
            ProviderConfig(
                id=p.get("id", ""),
                api_type=p.get("api_type", APIType.OPENAI_IMAGE),
                base_url=p.get("base_url", ""),
                api_key=p.get("api_key", ""),
                model=p.get("model", "")
            )
            for p in providers_data if p.get("id")
        ]

        # 适配扁平化后的链路配置
        chains = {
            "text2img": [p.strip() for p in config_dict.get("chain_text2img", "main_node").split(",") if p.strip()],
            "selfie": [p.strip() for p in config_dict.get("chain_selfie", "main_node").split(",") if p.strip()]
        }

        personas_data = config_dict.get("personas", [])
        personas = [
            PersonaConfig(
                name=p.get("name", ""),
                base_prompt=p.get("base_prompt", ""),
                ref_image_url=p.get("ref_image_url") or None
            )
            for p in personas_data if p.get("name")
        ]

        return cls(providers=providers, chains=chains, personas=personas)

    def get_provider_by_id(self, provider_id: str) -> Optional[ProviderConfig]:
        """根据 ID 获取 Provider 配置"""
        for p in self.providers:
            if p.id == provider_id:
                return p
        return None