"""
AstrBot 万象画卷插件 v3.1 - 数据模型
支持全中文 UI 变量映射与向后兼容。
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
    video_providers: List[ProviderConfig]
    chains: Dict[str, List[str]]
    presets: Dict[str, str]       
    enable_optimizer: bool        
    optimizer_model: str  
    optimizer_timeout: float  
    max_batch_count: int      
    persona_name: str
    persona_base_prompt: str
    persona_ref_image: str
    allowed_users: List[str]

    @classmethod
    def from_dict(cls, config_dict: Dict[str, Any], data_dir: str) -> "PluginConfig":
        providers = []
        for p in config_dict.get("providers", []):
            model_raw = str(p.get("模型名称", p.get("model", "")))
            available_models = [m.strip() for m in model_raw.replace("，", ",").split(",") if m.strip()]
            providers.append(ProviderConfig(
                id=str(p.get("节点ID", p.get("id", ""))),
                api_type=str(p.get("接口模式", p.get("api_type", "openai_image"))),
                base_url=str(p.get("接口地址", p.get("base_url", ""))),
                api_keys=[k.strip() for k in str(p.get("API密钥", p.get("api_keys", ""))).split("\n") if k.strip()],
                model=available_models[0] if available_models else "",
                timeout=float(p.get("超时时间", p.get("timeout", 60.0))),
                available_models=available_models
            ))
            
        video_providers = []
        for p in config_dict.get("video_providers", []):
            model_raw = str(p.get("模型名称", p.get("model", "")))
            available_models = [m.strip() for m in model_raw.replace("，", ",").split(",") if m.strip()]
            video_providers.append(ProviderConfig(
                id=str(p.get("节点ID", p.get("id", ""))),
                api_type=str(p.get("接口模式", p.get("api_type", "async_task"))),
                base_url=str(p.get("接口地址", p.get("base_url", ""))),
                api_keys=[k.strip() for k in str(p.get("API密钥", p.get("api_keys", ""))).split("\n") if k.strip()],
                model=available_models[0] if available_models else "",
                timeout=float(p.get("超时时间", p.get("timeout", 300.0))),
                available_models=available_models
            ))

        presets_dict = {}
        for p in config_dict.get("presets", []):
            if isinstance(p, str):
                separator = "：" if "：" in p else ":"
                if separator in p:
                    parts = p.split(separator, 1)
                    if len(parts) == 2:
                        cmd = parts[0].strip()
                        prompt = parts[1].strip()
                        if cmd and prompt:
                            if cmd.startswith("/"): cmd = cmd[1:]
                            presets_dict[cmd] = prompt

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
            target_path = os.path.abspath(os.path.join(data_dir, ref_path))
            ref_path = target_path if os.path.exists(target_path) else os.path.abspath(os.path.join(data_dir, ref_path))
            
        chains = {
            "text2img": [p.strip() for p in str(router_conf.get("chain_text2img", "node_1")).split(",") if p.strip()],
            "selfie": [p.strip() for p in str(router_conf.get("chain_selfie", "node_1")).split(",") if p.strip()],
            "video": [p.strip() for p in str(router_conf.get("chain_video", "video_node_1")).split(",") if p.strip()],
            "optimizer": [p.strip() for p in str(opt_conf.get("chain_optimizer", "node_1")).split(",") if p.strip()] 
        }

        raw_users = perm_conf.get("allowed_users", "")
        allowed_users = [u.strip() for u in str(raw_users).replace("，", ",").split(",") if u.strip()] if raw_users else []

        return cls(
            providers=providers,
            video_providers=video_providers,
            chains=chains,
            presets=presets_dict,
            enable_optimizer=bool(opt_conf.get("enable_optimizer", True)),
            optimizer_model=str(opt_conf.get("optimizer_model", "gpt-4o-mini")),
            optimizer_timeout=float(opt_conf.get("optimizer_timeout", 15.0)),
            max_batch_count=int(opt_conf.get("max_batch_count", 0)),
            persona_name=str(persona_conf.get("persona_name", "默认助理")),
            persona_base_prompt=str(persona_conf.get("persona_base_prompt", "")),
            persona_ref_image=ref_path,
            allowed_users=allowed_users
        )

    def get_provider(self, provider_id: str) -> ProviderConfig:
        return next((p for p in self.providers if p.id == provider_id), None)
        
    def get_video_provider(self, provider_id: str) -> ProviderConfig:
        return next((p for p in self.video_providers if p.id == provider_id), None)
