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

# 仅用于已知 OpenAI 图像模型的比例换算；Chat 中转站继续透传 aspect_ratio。
# 下表自定义尺寸适用于 GPT Image 2 等模型，不适用于固定尺寸模型。
# https://developers.openai.com/api/reference/resources/images/methods/generate
ASPECT_RATIO_TO_SIZE = {
    "1:1": "1024x1024",
    "4:3": "1536x1152",
    "3:4": "1152x1536",
    "3:2": "1536x1024",
    "2:3": "1024x1536",
    "16:9": "1536x864",
    "9:16": "864x1536",
    "21:9": "1680x720",
    "9:21": "720x1680",
}

OPENAI_FIXED_SIZE_IMAGE_MODELS = frozenset({
    "gpt-image-1",
    "gpt-image-1-mini",
    "gpt-image-1.5",
    "gpt-image-1.5-2025-12-16",
})
OPENAI_CUSTOM_SIZE_IMAGE_MODELS = frozenset({
    "gpt-image-2",
    "gpt-image-2-2026-04-21",
    "gpt-image-2.5-sunburst",
    "gpt-image-2.5-sunburst-2026-09-08",
    "gpt-image-2.5-flare",
    "gpt-image-2.5-flare-2026-09-08",
})


def aspect_ratio_to_size(aspect_ratio: str, model: str) -> str:
    """按模型能力把已知比例换算成 size，兼容全角冒号和首尾空格。

    固定尺寸模型按横图、竖图、方图选择支持的尺寸；自定义尺寸模型保留比例。
    未知模型或比例返回空字符串，由调用方保留原参数及节点默认尺寸逻辑。
    """
    key = str(aspect_ratio or "").strip().replace("：", ":")
    size = ASPECT_RATIO_TO_SIZE.get(key, "")
    if not size:
        return ""

    model_name = str(model or "").strip().lower()
    if model_name in OPENAI_CUSTOM_SIZE_IMAGE_MODELS:
        return size
    if model_name in OPENAI_FIXED_SIZE_IMAGE_MODELS:
        width, height = (int(value) for value in key.split(":"))
        if width == height:
            return "1024x1024"
        return "1536x1024" if width > height else "1024x1536"
    return ""


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
