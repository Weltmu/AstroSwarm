# -*- coding: utf-8 -*-
"""ac 指令系统已移除（设置改为 AstroSwarm 程序内完成），仅保留平台管理员判定。"""
from .manager import chat_manager


async def check_super_user(event) -> bool:
    """检查用户是否为管理员。

    微信 ClawBot 是扫码者私有的个人助手通道，扫码绑定账号天然是管理员；
    QQ 侧仍按配置的 super_users 判断。
    """
    if hasattr(event, "context_token"):
        return True
    user_id = str(event.get_user_id() if hasattr(event, "get_user_id") else getattr(event, "user_id", ""))
    return chat_manager.is_super_user(user_id)
