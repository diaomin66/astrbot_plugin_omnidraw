"""
AstrBot 万象画卷插件 v1.3.0 - 数据模型
"""
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
import os

@dataclass
class ProviderConfig:
    id: str
    api_type: str
    base_url: str
    api_keys: List[str] = field(default_factory=list)
    model: str = ""

@dataclass
class PersonaConfig:
    name: str
    base_prompt: str = ""
    # 这里存储的是一个 URL 或者本地路径
    ref_image_url: Optional[str] = None

    @property
    def local_image_exists(self) -> bool:
        """检查配置的是否是存在的本地文件"""
        if not self.ref_image_url:
            return False
        # 如果不是 http 开头，且本地存在该文件，则认为是本地人设
        return not self.ref_image_url.startswith("http") and os.path.exists(self.ref_image_url)

@dataclass
class PluginConfig:
    providers: List[ProviderConfig] = field(default_factory=list)
    chains: Dict[str, List[str]] = field(default_factory=dict)
    personas: List[PersonaConfig] = field(default_factory=list)

    @classmethod
    def from_dict(cls, config_dict: Dict[str, Any]) -> "PluginConfig":
        providers_data = config_dict.get("providers", [])
        providers = [
            ProviderConfig(
                id=p.get("id", ""),
                api_type=p.get("api_type", "openai_image"),
                base_url=p.get("base_url", ""),
                api_keys=[k.strip() for k in p.get("api_keys", "").split("\n") if k.strip()],
                model=p.get("model", "")
            )
            for p in providers_data if p.get("id")
        ]

        chains = {
            "text2img": [p.strip() for p in config_dict.get("chain_text2img", "main_node").split(",") if p.strip()],
            "selfie": [p.strip() for p in config_dict.get("chain_selfie", "main_node").split(",") if p.strip()]
        }

        personas_data = config_dict.get("personas", [])
        personas = [
            PersonaConfig(
                name=p.get("name", ""),
                base_prompt=p.get("base_prompt", ""),
                ref_image_url=p.get("ref_image_url")
            )
            for p in personas_data if p.get("name")
        ]

        return cls(providers=providers, chains=chains, personas=personas)

    def get_provider(self, provider_id: str) -> Optional[ProviderConfig]:
        return next((p for p in self.providers if p.id == provider_id), None)
