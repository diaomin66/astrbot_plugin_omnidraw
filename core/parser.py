import re
from typing import Tuple, Dict, Any

class CommandParser:
    def parse(self, message: str) -> Tuple[str, Dict[str, Any]]:
        """
        高级多模态参数解析器 (兼容 gptimage2 / Gemini Image 等高阶代理模型)
        精准切分提示词与 --key value 参数
        """
        kwargs = {}
        # 以空格紧接 -- 作为分割前瞻，防止截断普通文本里的普通连字符 (如 mid-journey)
        parts = re.split(r'(?=\s--[a-zA-Z0-9_-]+)', " " + message)
        
        prompt = parts[0].strip()
        
        for part in parts[1:]:
            part = part.strip()
            if not part.startswith('--'):
                prompt += " " + part
                continue
                
            # 剔除 '--'
            part = part[2:]
            
            # 分离 key 和 value
            kv = part.split(maxsplit=1)
            if not kv:
                continue
                
            key = kv[0]
            # 如果没有值（例如单纯的 --hd），则赋值为 True 
            value = kv[1].strip() if len(kv) > 1 else True
            
            kwargs[key] = value
            
        return prompt, kwargs
