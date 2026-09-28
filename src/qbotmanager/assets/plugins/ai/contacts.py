# -*- coding: utf-8 -*-
"""QQ 官方通道 openid 记录：主动聊天目标发现辅助。

QQ 官方接口只认 openid（不是 QQ 号）。程序在收到 QQ 官方消息时记录
最近活跃的私聊 / 群聊 openid，主动聊天可直接使用这些 openid；
若目标填的是 QQ 号，官方通道无法反查 openid，将无法发送。
"""
import time
from typing import Dict

_private: Dict[str, float] = {}
_groups: Dict[str, float] = {}


def remember(scene: str, room_id: str) -> None:
    """记录一次最近活跃的会话（私聊 room_id=openid，群聊 room_id=group_openid）。"""
    if scene == "group":
        _groups[room_id] = time.time()
    else:
        _private[room_id] = time.time()
