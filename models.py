"""
AstrBot 万象画卷插件 v3.1 - 数据模型
新增功能：加入专属的视频服务商配置 (video_providers)
"""
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
    available_models: List[str] = field(default_factory=list) 

@dataclass
class PluginConfig:
    providers: List[ProviderConfig]
    video_providers: List[ProviderConfig]  # 🚀 新增：专门存放视频 API 节点
    chains: Dict[str, List[str]]
    persona_name: str
    persona_base_prompt: str
    persona_ref_image: str
    allowed_users: List[str]

    @classmethod
    def from_dict(cls, config_dict: Dict[str, Any]) -> "PluginConfig":
        # 1. 解析画图节点
        providers = []
        for p in config_dict.get("providers", []):
            model_raw = str(p.get("model", ""))
            available_models = [m.strip() for m in model_raw.replace("，", ",").split(",") if m.strip()]
            active_model = available_models[0] if available_models else ""
            
            providers.append(ProviderConfig(
                id=p.get("id", ""),
                api_type=p.get("api_type", "openai_image"),
                base_url=p.get("base_url", ""),
                api_keys=[k.strip() for k in p.get("api_keys", "").split("\n") if k.strip()],
                model=active_model,
                timeout=float(p.get("timeout", 60.0)),
                available_models=available_models
            ))
            
        # 🚀 2. 解析视频节点 (结构和画图类似，但独立存放)
        video_providers = []
        for p in config_dict.get("video_providers", []):
            model_raw = str(p.get("model", ""))
            available_models = [m.strip() for m in model_raw.replace("，", ",").split(",") if m.strip()]
            active_model = available_models[0] if available_models else ""
            
            video_providers.append(ProviderConfig(
                id=p.get("id", ""),
                api_type=p.get("api_type", "openai_video"), # 例如 Grok Video 或 Veo
                base_url=p.get("base_url", ""),
                api_keys=[k.strip() for k in p.get("api_keys", "").split("\n") if k.strip()],
                model=active_model,
                timeout=float(p.get("timeout", 300.0)), # 视频默认超时时间给长一点：5分钟
                available_models=available_models
            ))

        # 3. 处理人设图与链
        raw_image = config_dict.get("persona_ref_image", "")
        ref_path = ""
        if isinstance(raw_image, list) and len(raw_image) > 0:
            raw_image = raw_image[0]
            
        if isinstance(raw_image, dict):
            ref_path = raw_image.get("path") or raw_image.get("url") or raw_image.get("file") or ""
        elif isinstance(raw_image, str):
            ref_path = raw_image.strip()
            
        if ref_path and not ref_path.startswith("http") and not os.path.isabs(ref_path):
            plugin_data_dir = os.path.join(os.getcwd(), "data", "plugin_data", "astrbot_plugin_omnidraw")
            target_path = os.path.abspath(os.path.join(plugin_data_dir, ref_path))
            if not os.path.exists(target_path):
                fallback_path = os.path.abspath(os.path.join(os.getcwd(), "data", ref_path))
                if os.path.exists(fallback_path):
                    target_path = fallback_path
            ref_path = target_path
            
        chains = {
            "text2img": [p.strip() for p in config_dict.get("chain_text2img", "node_1").split(",") if p.strip()],
            "selfie": [p.strip() for p in config_dict.get("chain_selfie", "node_1").split(",") if p.strip()],
            "video": [p.strip() for p in config_dict.get("chain_video", "video_node_1").split(",") if p.strip()] # 🚀 新增：视频专用执行链
        }

        # 4. 白名单
        raw_users = config_dict.get("allowed_users", "")
        if isinstance(raw_users, str):
            allowed_users = [u.strip() for u in raw_users.replace("，", ",").split(",") if u.strip()]
        elif isinstance(raw_users, list):
            allowed_users = [str(u).strip() for u in raw_users]
        else:
            allowed_users = []

        return cls(
            providers=providers,
            video_providers=video_providers,
            chains=chains,
            persona_name=config_dict.get("persona_name", "默认助理"),
            persona_base_prompt=config_dict.get("persona_base_prompt", ""),
            persona_ref_image=ref_path,
            allowed_users=allowed_users
        )

    def get_provider(self, provider_id: str) -> ProviderConfig:
        return next((p for p in self.providers if p.id == provider_id), None)
        
    def get_video_provider(self, provider_id: str) -> ProviderConfig:
        return next((p for p in self.video_providers if p.id == provider_id), None)
