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
    video_providers: List[ProviderConfig]
    chains: Dict[str, List[str]]
    enable_optimizer: bool        
    optimizer_model: str  
    optimizer_timeout: float  
    max_batch_count: int      # 🚀 新增批量上限控制
    persona_name: str
    persona_base_prompt: str
    persona_ref_image: str
    allowed_users: List[str]

    @classmethod
    def from_dict(cls, config_dict: Dict[str, Any]) -> "PluginConfig":
        providers = []
        for p in config_dict.get("providers", []):
            model_raw = str(p.get("model", ""))
            available_models = [m.strip() for m in model_raw.replace("，", ",").split(",") if m.strip()]
            providers.append(ProviderConfig(
                id=p.get("id", ""),
                api_type=p.get("api_type", "openai_image"),
                base_url=p.get("base_url", ""),
                api_keys=[k.strip() for k in p.get("api_keys", "").split("\n") if k.strip()],
                model=available_models[0] if available_models else "",
                timeout=float(p.get("timeout", 60.0)),
                available_models=available_models
            ))
            
        video_providers = []
        for p in config_dict.get("video_providers", []):
            model_raw = str(p.get("model", ""))
            available_models = [m.strip() for m in model_raw.replace("，", ",").split(",") if m.strip()]
            video_providers.append(ProviderConfig(
                id=p.get("id", ""),
                api_type=p.get("api_type", "openai_video"),
                base_url=p.get("base_url", ""),
                api_keys=[k.strip() for k in p.get("api_keys", "").split("\n") if k.strip()],
                model=available_models[0] if available_models else "",
                timeout=float(p.get("timeout", 300.0)),
                available_models=available_models
            ))

        persona_conf = config_dict.get("persona_config", {})
        opt_conf = config_dict.get("optimizer_config", {})
        router_conf = config_dict.get("router_config", {})
        perm_conf = config_dict.get("permission_config", {})

        raw_image = persona_conf.get("persona_ref_image", "")
        ref_path = ""
        if isinstance(raw_image, list) and len(raw_image) > 0: raw_image = raw_image[0]
        if isinstance(raw_image, dict):
            ref_path = raw_image.get("path") or raw_image.get("url") or raw_image.get("file") or ""
        elif isinstance(raw_image, str): ref_path = raw_image.strip()
            
        if ref_path and not ref_path.startswith("http") and not os.path.isabs(ref_path):
            plugin_data_dir = os.path.join(os.getcwd(), "data", "plugin_data", "astrbot_plugin_omnidraw")
            target_path = os.path.abspath(os.path.join(plugin_data_dir, ref_path))
            ref_path = target_path if os.path.exists(target_path) else os.path.abspath(os.path.join(os.getcwd(), "data", ref_path))
            
        chains = {
            "text2img": [p.strip() for p in router_conf.get("chain_text2img", "node_1").split(",") if p.strip()],
            "selfie": [p.strip() for p in router_conf.get("chain_selfie", "node_1").split(",") if p.strip()],
            "video": [p.strip() for p in router_conf.get("chain_video", "video_node_1").split(",") if p.strip()],
            "optimizer": [p.strip() for p in opt_conf.get("chain_optimizer", "node_1").split(",") if p.strip()] 
        }

        raw_users = perm_conf.get("allowed_users", "")
        allowed_users = [u.strip() for u in raw_users.replace("，", ",").split(",") if u.strip()] if isinstance(raw_users, str) else []

        return cls(
            providers=providers,
            video_providers=video_providers,
            chains=chains,
            enable_optimizer=opt_conf.get("enable_optimizer", True),
            optimizer_model=opt_conf.get("optimizer_model", "gpt-4o-mini"),
            optimizer_timeout=float(opt_conf.get("optimizer_timeout", 15.0)),
            max_batch_count=int(opt_conf.get("max_batch_count", 0)), # 🚀
            persona_name=persona_conf.get("persona_name", "默认助理"),
            persona_base_prompt=persona_conf.get("persona_base_prompt", ""),
            persona_ref_image=ref_path,
            allowed_users=allowed_users
        )

    def get_provider(self, provider_id: str) -> ProviderConfig:
        return next((p for p in self.providers if p.id == provider_id), None)
        
    def get_video_provider(self, provider_id: str) -> ProviderConfig:
        return next((p for p in self.video_providers if p.id == provider_id), None)
