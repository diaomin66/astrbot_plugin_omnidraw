"""
AstrBot 万象画卷插件 v1.0.0

功能描述：
- 常量定义模块

作者: your_name
版本: 1.0.0
日期: 2026-04-25
"""

# API 超时配置
API_TIMEOUT_DEFAULT = 60.0
API_TIMEOUT_SLOW = 120.0

class APIType:
    """接口类型枚举"""
    OPENAI_IMAGE = "openai_image"

class MessageEmoji:
    """消息表情符号"""
    ERROR = "❌"
    SUCCESS = "✅"
    WARNING = "⚠️"
    INFO = "ℹ️"
    PAINTING = "🎨"