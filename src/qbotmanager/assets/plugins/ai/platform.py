# -*- coding: utf-8 -*-
"""平台中立事件层：让 AI 大脑不感知具体平台（QQ / 微信 ClawBot / 飞书 / 纸飞机）。

设计目标：
- 大脑（brain.py）只依赖 ChannelMessage 与 ChannelContext；
- 各平台适配器（adapters/）负责把平台事件转成 ChannelMessage，并实现发送；
- 老平台（QQ）行为不回归：会话记忆 key 沿用旧格式。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

PLATFORM_QQ = "qq"
PLATFORM_QQ_OFFICIAL = "qq_official"
PLATFORM_WECHAT = "wechat"
PLATFORM_FEISHU = "feishu"
PLATFORM_TELEGRAM = "telegram"

SCENE_PRIVATE = "private"
SCENE_GROUP = "group"


async def _noop(*args, **kwargs):
    return None


@dataclass
class ChannelMessage:
    """归一化入站消息。"""

    platform: str                 # PLATFORM_*
    scene: str                    # SCENE_PRIVATE / SCENE_GROUP
    user_id: str                  # 平台内用户 id（QQ 号 / wechat im id / ...）
    room_id: str                  # 会话 id：群=群号，私聊=user_id
    text: str                     # 归一化文本（QQ 侧已含图片识别结果）
    is_at_me: bool = False        # 是否 @ 机器人（群聊）
    nickname: str = ""            # 发送者昵称
    plain_text: str = ""          # 纯文本（用于命令过滤，不含图片识别等附加内容）
    raw: Any = None               # 原始平台事件（适配器内部用）
    extra: dict = field(default_factory=dict)  # 平台附加数据（如 at_others、wechat context_token）
    is_superuser: bool = False    # 该消息发送者是否为机器人管理员（微信 ClawBot 扫码者默认是）

    @property
    def context_key(self) -> str:
        """会话记忆 key。QQ 沿用旧格式，保证老客户历史上下文不失效。"""
        if self.platform == PLATFORM_QQ:
            return f"group_{self.room_id}" if self.scene == SCENE_GROUP else self.user_id
        return f"{self.platform}:{self.scene}:{self.room_id}"

    @property
    def session_key(self) -> str:
        """免@会话 / 群活跃度 key（平台+会话）。"""
        return f"{self.platform}:{self.room_id}"

    @property
    def user_key(self) -> str:
        """跨平台用户 key（平台+用户）。"""
        return f"{self.platform}:{self.user_id}"


@dataclass
class ChannelContext:
    """发送/通知抽象：大脑只调用这三个方法，不感知平台。"""

    platform: str
    scene: str
    send_text: Callable[[str], Awaitable[None]]          # 发一段普通文本
    send_text_at: Callable[[str], Awaitable[None]]       # 发一段 @触发者 的文本（群聊）
    notify_error: Callable[[str], Awaitable[None]] = _noop  # 通知管理员（平台错误上报）
