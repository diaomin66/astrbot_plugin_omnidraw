"""
AstrBot 万象画卷插件 v1.1.0
功能描述：兜底链路调度器
"""

import aiohttp
from typing import Any
from astrbot.api import logger
from ..models import PluginConfig
from ..providers import create_provider

class ChainManager:
    def __init__(self, config: PluginConfig, session: aiohttp.ClientSession):
        self.config = config
        self.session = session

    async def run_chain(self, chain_name: str, prompt: str, **kwargs: Any) -> str:
        chain = self.config.chains.get(chain_name)
        if not chain:
            raise ValueError(f"未找到链路配置: {chain_name}")

        last_error = None
        
        for provider_id in chain:
            # 【关键修复】把 get_provider_by_id 改成了 get_provider
            provider_config = self.config.get_provider(provider_id)
            if not provider_config:
                logger.warning(f"⚠️ 链路 [{chain_name}] 中的节点 [{provider_id}] 不存在。")
                continue

            logger.info(f"🚀 [Chain] 正在将任务交由节点 [{provider_id}] 处理...")
            try:
                provider = create_provider(provider_config, self.session)
                result = await provider.generate_image(prompt, **kwargs)
                logger.info(f"✅ [Chain] 节点 [{provider_id}] 创作成功！")
                return result
                
            except Exception as e:
                # 增强日志捕获
                error_detail = repr(e)
                last_error = error_detail
                logger.error(f"❌ [Chain] 节点 [{provider_id}] 发生异常: {error_detail}", exc_info=True)
                logger.warning(f"🔄 正在尝试切换到下一个备用节点...")
                continue

        raise RuntimeError(f"所有节点均已阵亡！最后一次报错内容: {last_error}")
