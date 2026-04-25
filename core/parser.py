"""
AstrBot 万象画卷插件 v1.0.0

功能描述：
- 指令参数解析器

作者: your_name
版本: 1.0.0
日期: 2026-04-25
"""

import re
from typing import Tuple, Dict, Any

class CommandParser:
    """指令参数解析器类"""

    def __init__(self):
        # 编译正则表达式（只编译一次）
        self.param_pattern = re.compile(r'--([a-zA-Z0-9_-]+)\s+([^\s]+)')

    def parse(self, raw_input: str) -> Tuple[str, Dict[str, Any]]:
        """解析用户输入，分离提示词和高级参数"""
        kwargs: Dict[str, Any] = {}
        
        matches = self.param_pattern.findall(raw_input)
        for key, value in matches:
            kwargs[key] = value

        clean_prompt = self.param_pattern.sub('', raw_input).strip()
        
        if 'seed' in kwargs and kwargs['seed'].isdigit():
            kwargs['seed'] = int(kwargs['seed'])
            
        return clean_prompt, kwargs