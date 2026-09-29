# -*- coding: utf-8 -*-
"""平台适配器分发：按事件类型把平台事件转成 ChannelMessage / ChannelContext。"""
import os as _os
from typing import Optional

from nonebot import logger

from ..platform import ChannelContext, ChannelMessage


def platform_enabled(platform: str) -> bool:
    """AstroSwarm 平台开关：AI_PLATFORM_QQ=0 表示 AI 不处理 QQ 消息。

    未注入环境变量（例如脱离管理器直接运行机器人）时默认启用，避免行为回归。
    """
    val = _os.environ.get("AI_PLATFORM_" + (platform or "").upper())
    if val is None:
        return True
    return val == "1"


def detect_platform(event) -> str:
    """识别事件属于哪个平台（不依赖脆弱的顶层包导入）。

    优先按事件类所在模块名识别：AstroSwarm 部署的微信适配器
    实际模块名是 src.plugins.nonebot_adapter_ilink.*（顶层名不可导入）；
    QQ 走 OneBot V11 类型判断；最后用 context_token 兜底（微信事件独有字段）。
    """
    mod = type(event).__module__ or ""
    if "nonebot_adapter_ilink" in mod:
        return "wechat"
    try:
        from nonebot.adapters.onebot.v11 import MessageEvent as OneBotEvent

        if isinstance(event, OneBotEvent):
            return "qq"
    except Exception:  # noqa: BLE001
        pass
    try:
        from nonebot.adapters.qq import MessageEvent as QQOfficialEvent

        if isinstance(event, QQOfficialEvent):
            return "qq_official"
    except Exception:  # noqa: BLE001
        pass
    if hasattr(event, "context_token"):
        return "wechat"
    return ""


async def build_channel(chat_handler, bot, event) -> Optional[tuple[ChannelMessage, ChannelContext]]:
    """根据事件类型分发到对应平台适配器。"""
    platform = detect_platform(event)
    logger.info(f"[bridge] 事件 {type(event).__module__} -> 平台 {platform or '未知'}")
    if platform == "qq":
        if not platform_enabled("qq"):
            return None
        from .qq import build_channel_from_event

        return await build_channel_from_event(chat_handler, bot, event)

    if platform == "qq_official":
        # 官方 QQ 与 OneBot 共用“QQ”平台开关（AI 大脑的 QQ 总开关）
        if not platform_enabled("qq"):
            return None
        from .qq_official import build_channel_from_qq_official

        return await build_channel_from_qq_official(chat_handler, bot, event)

    if platform == "wechat":
        if not platform_enabled("wechat"):
            return None
        from .wechat import build_channel_from_wechat

        return await build_channel_from_wechat(chat_handler, bot, event)
    logger.warning(f"[bridge] 未识别的平台事件: {type(event).__module__}")
    return None
