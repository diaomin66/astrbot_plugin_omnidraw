"""
AstrBot 万象画卷插件 v1.0.0

功能描述：
- 兜底链路调度器

作者: your_name
版本: 1.0.0
日期: 2026-04-25
"""

import aiohttp
from typing import Any
from astrbot.api import logger
from ..models import PluginConfig
from ..providers import create_provider

class ChainManager:
    """负责管理 Provider 的流转和失败重试逻辑"""
    
    def __init__(self, config: PluginConfig, session: aiohttp.ClientSession):
        self.config = config
        self.session = session

    async def run_chain(self, chain_name: str, prompt: str, **kwargs: Any) -> str:
        """按照配置好的链路顺序执行画图任务"""
        chain = self.config.chains.get(chain_name)
        if not chain:
            raise ValueError(f"未找到对应的链路配置: {chain_name}，请在 WebUI 中配置。")

        last_error = None
        
        for provider_id in chain:
            provider_config = self.config.get_provider_by_id(provider_id)
            if not provider_config:
                logger.warning(f"链路 [{chain_name}] 中节点 [{provider_id}] 不存在，已跳过。")
                continue

            logger.info(f"🎨 尝试使用节点 [{provider_id}] 进行创作...")
            try:
                # 工厂实例化 Provider
                provider = create_provider(provider_config, self.session)
                
                # 执行请求并添加超时控制
                result = await provider.generate_image(prompt, **kwargs)
                
                logger.info(f"✅ 节点 [{provider_id}] 创作成功！")
                return result
                
            except Exception as e:
                last_error = e
                logger.error(f"❌ 节点 [{provider_id}] 失败: {str(e)}。切换下一个...")
                continue

        raise RuntimeError(f"链路 [{chain_name}] 所有节点均失败！最后错误: {last_error}")