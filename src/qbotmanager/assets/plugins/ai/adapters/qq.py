# -*- coding: utf-8 -*-
"""QQ 通道适配器（OneBot V11 → 平台中立模型）。"""
from nonebot import logger
from nonebot.adapters.onebot.v11 import Bot, Message, MessageEvent

from ..image2txt import recognize_image
from ..manager import chat_manager
from ..platform import (
    ChannelContext,
    ChannelMessage,
    PLATFORM_QQ,
    SCENE_GROUP,
    SCENE_PRIVATE,
)
from ..send2root import send_error_to_super_users


async def _extract_text(event: MessageEvent) -> str:
    """原 event_proc：纯文本 + 图片识别结果。"""
    user_text = event.get_plaintext().strip()
    recognition_msg = f"{user_text}\n"
    if chat_manager.is_image_recognition_enabled():
        image_urls = []
        for seg in event.message:
            if seg.type == "image":
                image_urls.append(seg.data.get("url"))
        if image_urls:
            try:
                recognition_list = []
                for i, image_url in enumerate(image_urls):
                    result = await recognize_image(image_url)
                    recognition_list.append(f"[图片{i + 1}的识别结果]{result}")
                recognition_msg += "\n".join(recognition_list)
                logger.info(f"识别结果: {recognition_msg}")
            except Exception as e:
                error_msg = f"图片识别失败: {str(e)}"
                logger.info(error_msg)
                await send_error_to_super_users(error_msg, event)
                recognition_msg += "\n[图片识别失败](你现在还没有图片识别的能力)"
    return recognition_msg


async def build_channel_from_event(
    chat_handler, bot: Bot, event: MessageEvent
) -> tuple[ChannelMessage, ChannelContext]:
    """OneBot V11 事件 → ChannelMessage + ChannelContext。"""
    group_id = getattr(event, "group_id", None)
    scene = SCENE_GROUP if group_id else SCENE_PRIVATE
    user_id = str(event.user_id)
    room_id = str(group_id) if group_id else user_id
    nickname = event.sender.nickname if event.sender else ""
    plain = event.get_plaintext().strip()
    text = await _extract_text(event)
    is_at = bool(getattr(event, "is_tome", lambda: False)())
    at_others = False
    if scene == SCENE_GROUP:
        at_others = any(
            seg.type == "at" and str(seg.data.get("qq", "")) != str(bot.self_id)
            for seg in event.message
        )
    msg = ChannelMessage(
        platform=PLATFORM_QQ,
        scene=scene,
        user_id=user_id,
        room_id=room_id,
        text=text,
        is_at_me=is_at,
        nickname=nickname,
        plain_text=plain,
        raw=event,
        extra={"at_others": at_others},
    )

    async def send_text(t: str) -> None:
        await chat_handler.send(t)

    async def send_text_at(t: str) -> None:
        await chat_handler.send(Message(f"[CQ:at,qq={user_id}] {t}"))

    async def notify_error(err: str) -> None:
        await send_error_to_super_users(err, event)

    ctx = ChannelContext(
        platform=PLATFORM_QQ,
        scene=scene,
        send_text=send_text,
        send_text_at=send_text_at,
        notify_error=notify_error,
    )
    return msg, ctx
