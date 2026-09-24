# -*- coding: utf-8 -*-
"""QQ 官方机器人通道适配器（nonebot-adapter-qq 事件 → 平台中立模型）。

platform 使用 qq_official，session_key 天然带平台前缀，与微信等通道会话隔离。
"""
from nonebot import logger

from ..contacts import remember as remember_contact
from ..image2txt import recognize_image
from ..manager import chat_manager
from ..platform import (
    ChannelContext,
    ChannelMessage,
    PLATFORM_QQ_OFFICIAL,
    SCENE_GROUP,
    SCENE_PRIVATE,
)


def _is_group_event(event) -> bool:
    try:
        from nonebot.adapters.qq import GroupMessageCreateEvent

        return isinstance(event, GroupMessageCreateEvent)
    except Exception:  # noqa: BLE001
        return bool(getattr(event, "group_openid", None))


async def _extract_text(event) -> str:
    """官方事件 → 纯文本 + 图片识别结果（与 OneBot 侧行为对齐）。"""
    user_text = event.get_plaintext().strip()
    recognition_msg = f"{user_text}\n"
    if not chat_manager.is_image_recognition_enabled():
        return recognition_msg
    image_urls = []
    try:
        for seg in event.get_message():
            if seg.type == "image":
                url = (seg.data or {}).get("url")
                if url:
                    image_urls.append(url)
    except Exception:  # noqa: BLE001
        image_urls = []
    if not image_urls:
        return recognition_msg
    try:
        parts = []
        for i, url in enumerate(image_urls):
            result = await recognize_image(url)
            parts.append(f"[图片{i + 1}的识别结果]{result}")
        recognition_msg += "\n".join(parts)
        logger.info(f"[qq_official] 图片识别结果: {recognition_msg}")
    except Exception as e:  # noqa: BLE001
        logger.info(f"[qq_official] 图片识别失败: {str(e)}")
        recognition_msg += "\n[图片识别失败](你现在还没有图片识别的能力)"
    return recognition_msg


async def build_channel_from_qq_official(chat_handler, bot, event):
    """官方 QQ 事件 → ChannelMessage + ChannelContext。"""
    group = _is_group_event(event)
    scene = SCENE_GROUP if group else SCENE_PRIVATE
    user_id = event.get_user_id()
    room_id = str(getattr(event, "group_openid", "") or user_id)
    remember_contact(scene, room_id)
    plain = event.get_plaintext().strip()
    text = await _extract_text(event)
    is_at = bool(getattr(event, "to_me", False))
    nickname = ""
    author = getattr(event, "author", None)
    if author is not None:
        nickname = str(getattr(author, "username", "") or "")
    msg = ChannelMessage(
        platform=PLATFORM_QQ_OFFICIAL,
        scene=scene,
        user_id=user_id,
        room_id=room_id,
        text=text,
        is_at_me=is_at,
        nickname=nickname,
        plain_text=plain,
        raw=event,
        extra={"group_openid": str(getattr(event, "group_openid", "") or "")},
    )

    async def send_text(t: str) -> None:
        await bot.send(event, t)

    async def send_text_at(t: str) -> None:
        # 官方接口按 msg_id 被动回复即可，不需要手动拼接 @
        await bot.send(event, t)

    async def notify_error(err: str) -> None:
        logger.error(f"[qq_official] {err}")

    ctx = ChannelContext(
        platform=PLATFORM_QQ_OFFICIAL,
        scene=scene,
        send_text=send_text,
        send_text_at=send_text_at,
        notify_error=notify_error,
    )
    return msg, ctx
