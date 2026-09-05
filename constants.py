"""AstrBot 万象画卷插件常量。"""

# API 超时配置
API_TIMEOUT_DEFAULT = 60.0
API_TIMEOUT_SLOW = 120.0
MAX_IMAGE_BYTES = 20 * 1024 * 1024
DEFAULT_BATCH_LIMIT = 10
MAX_BATCH_LIMIT = DEFAULT_BATCH_LIMIT
DEFAULT_OPTIMIZER_MODEL = "gpt-4o-mini"
DEFAULT_OPTIMIZER_STYLE = "手机日常原生感"
OPTIMIZER_STYLE_OPTIONS = (
    DEFAULT_OPTIMIZER_STYLE,
    "自拍专用极致真实",
    "电影级光影大片",
    "日系插画大师",
    "3D 潮玩盲盒",
    "自定义模式",
)
DEFAULT_DRAW_PENDING_MESSAGE = "🎨 收到灵感，正在绘制..."
DEFAULT_SELFIE_PENDING_MESSAGE = "ℹ️ 正在为「{persona_name}」生成自拍，请稍候..."
DEFAULT_DRAW_ERROR_MESSAGE = "💥 绘制失败: {error}"
DEFAULT_SELFIE_ERROR_MESSAGE = "💥 自拍生成失败: {error}"
DEFAULT_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_GEMINI_MODEL = "gemini-3.1-flash-image"

class APIType:
    """接口类型枚举"""
    OPENAI_IMAGE = "openai_image"
    OPENAI_CHAT = "openai_chat"  # 新增 Chat 解析出图类型
    GEMINI_OFFICIAL = "gemini_official"
    CUSTOM_ENDPOINT = "custom_endpoint"

class MessageEmoji:
    """消息表情符号"""
    ERROR = "❌"
    SUCCESS = "✅"
    WARNING = "⚠️"
    INFO = "ℹ️"
    PAINTING = "🎨"
