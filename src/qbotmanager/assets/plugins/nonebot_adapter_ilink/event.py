# -*- coding: utf-8 -*-
"""iLink 事件定义。"""
from collections.abc import Iterable
from typing import Any

from nonebot.adapters import Event as BaseEvent
from nonebot.adapters import Message as BaseMessage
from nonebot.adapters import MessageSegment as BaseMessageSegment


class TextSegment(BaseMessageSegment["Message"]):
    """iLink 纯文本消息段（ClawBot 消息只有文本）。"""

    @classmethod
    def get_message_class(cls):
        return Message

    def __str__(self) -> str:
        return str(self.data.get("text", ""))

    def is_text(self) -> bool:
        return True


class Message(BaseMessage[TextSegment]):
    """iLink 消息：纯文本，满足 NoneBot 命令解析/消息管线要求。"""

    @classmethod
    def get_segment_class(cls):
        return TextSegment

    @staticmethod
    def _construct(msg: str) -> Iterable[TextSegment]:
        return [TextSegment(type="text", data={"text": str(msg or "")})]


class Event(BaseEvent):
    """微信 ClawBot 私聊消息事件。"""

    type: str = "message"
    self_id: str
    time: float
    message_id: str
    from_user_id: str
    to_user_id: str
    message_type: str = "private"
    raw_message: str = ""
    context_token: str = ""
    group_id: str = ""
    raw: Any = None

    def get_type(self) -> str:
        return "message"

    def get_event_name(self) -> str:
        return "wechat.private.message" if self.message_type == "private" else "wechat.group.message"

    def get_event_description(self) -> str:
        return f"Message {self.message_id} from {self.from_user_id}: {self.raw_message}"

    def get_user_id(self) -> str:
        return self.from_user_id

    def get_session_id(self) -> str:
        if self.message_type == "group" and self.group_id:
            return f"group_{self.group_id}_{self.from_user_id}"
        return self.from_user_id

    def get_message(self) -> Message:
        return Message(self.raw_message)

    def get_plaintext(self) -> str:
        return self.raw_message

    def is_tome(self) -> bool:
        # ClawBot 是私密通道，消息天然都是发给机器人的
        return True
