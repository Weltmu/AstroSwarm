# -*- coding: utf-8 -*-
"""微信 ClawBot 通道适配器（nonebot-adapter-ilink 事件 → 平台中立模型）。"""
from nonebot import logger

from ..platform import (
    ChannelContext,
    ChannelMessage,
    PLATFORM_WECHAT,
    SCENE_PRIVATE,
)


async def build_channel_from_wechat(chat_handler, bot, event):
    """iLink 事件 → ChannelMessage + ChannelContext（私聊个人助手，天然 to_me）。"""
    user_id = event.get_user_id()
    raw = getattr(event, "raw_message", "") or event.get_plaintext()
    msg = ChannelMessage(
        platform=PLATFORM_WECHAT,
        scene=SCENE_PRIVATE,
        user_id=user_id,
        room_id=user_id,
        text=raw,
        is_at_me=True,
        nickname="微信用户",
        plain_text=raw,
        raw=event,
        extra={"context_token": getattr(event, "context_token", "")},
        is_superuser=True,  # ClawBot 私密通道：扫码绑定微信账号即为机器人唯一管理员
    )

    async def send_text(t: str) -> None:
        ok = await bot.send(event, t)
        logger.info(f"[wechat] 发送回复 {'成功' if ok else '失败'}: {t[:80]}")

    async def send_text_at(t: str) -> None:
        ok = await bot.send(event, t)
        logger.info(f"[wechat] 发送回复 {'成功' if ok else '失败'}: {t[:80]}")

    async def notify_error(err: str) -> None:
        logger.error(f"[wechat] {err}")

    ctx = ChannelContext(
        platform=PLATFORM_WECHAT,
        scene=SCENE_PRIVATE,
        send_text=send_text,
        send_text_at=send_text_at,
        notify_error=notify_error,
    )
    return msg, ctx
