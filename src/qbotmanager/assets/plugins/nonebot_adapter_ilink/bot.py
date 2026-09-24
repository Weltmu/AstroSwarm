# -*- coding: utf-8 -*-
from nonebot.adapters import Bot as BaseBot
from nonebot.message import handle_event as _dispatch_event

from .client import IlinkClient
from .event import Event


class Bot(BaseBot):
    def __init__(self, adapter, self_id: str, client: IlinkClient):
        super().__init__(adapter, self_id)
        self.client = client

    async def handle_event(self, event: Event) -> None:
        """把收到的 iLink 事件送入 NoneBot 消息管线（匹配器分发）。"""
        await _dispatch_event(self, event)

    async def send(self, event, message, **kwargs):
        text = message.extract_plain_text() if hasattr(message, "extract_plain_text") else str(message)
        ctx = getattr(event, "context_token", "") or ""
        return await self.client.send_text(event.get_user_id(), ctx, text)

    async def call_api(self, api: str, **data):
        if api in ("send_msg", "send_message", "sendmessage"):
            event = data.get("event")
            message = data.get("message", "")
            ctx = data.get("context_token", "")
            to = data.get("user_id")
            if event is not None:
                if not to:
                    to = event.get_user_id()
                if not ctx:
                    ctx = getattr(event, "context_token", "")
            if to:
                return await self.client.send_text(str(to), ctx, str(message))
            raise ValueError("缺少 user_id")
        raise NotImplementedError(f"iLink Bot 暂不支持 API: {api}")
