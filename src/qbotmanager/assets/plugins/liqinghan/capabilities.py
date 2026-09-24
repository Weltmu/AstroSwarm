# -*- coding: utf-8 -*-
"""李清菡插件侧通道能力矩阵（与程序侧 core/agent_profile.py 同步维护）。

source = "<channel>:<scope>"，如 qq:c2c / qq:group / wechat:private。
能力值：chat / memory / voice / image / image_gen / proactive /
        group_interject / group_admin / recall / tools。
官方 QQ 无 CQ 表情代码，因此 qq_face 能力不启用（send_face 工具会被裁剪）。
"""

CHANNEL_CAPABILITIES = {
    "qq:c2c": {"chat", "memory", "voice", "image", "image_gen",
               "proactive", "recall", "tools"},
    "qq:group": {"chat", "memory", "voice", "image", "image_gen",
                 "proactive", "group_interject", "group_admin",
                 "recall", "tools"},
    "wechat:private": {"chat", "memory", "tools"},
    "feishu:private": {"chat", "memory", "tools"},
    "telegram:private": {"chat", "memory", "tools"},
}

# 工具 → 所需能力（缺省按 chat，即任何聊天通道都可用）
TOOL_CAPABILITIES = {
    "mute_user": "group_admin",
    "mute_all": "group_admin",
    "set_reminder": "proactive",
    "describe_image": "image",
    "send_face": "qq_face",
    "generate_image": "image_gen",
    "remember": "memory",
    "recall": "memory",
    "recall_message": "recall",
}


def channel_capabilities(source: str) -> set:
    """返回指定来源的能力集合；未知通道一律空（全部禁用）。"""
    return set(CHANNEL_CAPABILITIES.get(source, ()))


def enabled_tools(source: str, tools: list) -> list:
    """按通道能力裁剪工具列表（保持原顺序）。"""
    caps = channel_capabilities(source)
    return [t for t in tools if TOOL_CAPABILITIES.get(t, "chat") in caps]
