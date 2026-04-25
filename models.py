import os
from dataclasses import dataclass, field
from typing import List, Dict, Any

@dataclass
class ProviderConfig:
    id: str
    api_type: str
    base_url: str
    api_keys: List[str]
    model: str
    timeout: float

@dataclass
class PluginConfig:
    providers: List[ProviderConfig]
    chains: Dict[str, List[str]]
    persona_base_prompt: str
    persona_ref_image: str  # 这里直接存路径

    @classmethod
    def from_dict(cls, config_dict: Dict[str, Any]) -> "PluginConfig":
        # 1. 解析 Provider
        providers = [
            ProviderConfig(
                id=p.get("id", ""),
                api_type=p.get("api_type", "openai_image"),
                base_url=p.get("base_url", ""),
                api_keys=[k.strip() for k in p.get("api_keys", "").split("\n") if k.strip()],
                model=p.get("model", ""),
                timeout=float(p.get("timeout", 60.0))
            ) for p in config_dict.get("providers", [])
        ]
        
        # 2. 提取参考图路径 (AstrBot 原生路径逻辑)
        raw_image = config_dict.get("persona_ref_image", "")
        # 如果是 file 组件返回的 dict，提取 path
        ref_path = raw_image.get("path", "") if isinstance(raw_image, dict) else str(raw_image)
        
        # 修正相对路径为绝对路径 (AstrBot 默认在 data 目录下)
        if ref_path and not os.path.isabs(ref_path):
            ref_path = os.path.join(os.getcwd(), "data", ref_path)

        return cls(
            providers=providers,
            chains={"text2img": [config_dict.get("chain_text2img", "node_1")], "selfie": [config_dict.get("chain_selfie", "node_1")]},
            persona_base_prompt=config_dict.get("persona_base_prompt", ""),
            persona_ref_image=ref_path
        )
