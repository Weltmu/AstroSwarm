from pydantic import BaseModel
from nonebot import get_plugin_config
from typing import Set, List


class PluginConfig(BaseModel):
    """AstroSwarm 内置 AI 插件配置"""

    # 超级用户列表
    aichat_super_users: Set[str] = set()

    # ---- 群聊免@会话 ----
    # 与机器人聊天后，多少秒内不需要再@；超过后需重新@
    aichat_session_expire_seconds: int = 30
    # 连续多少条与机器人无关的消息后结束免@会话（需重新@）
    aichat_session_unrelated_limit: int = 5

    # ---- 主动聊天（私聊 + 群聊）----
    # 主动聊天的群聊群号列表
    aichat_proactive_groups: List[str] = []
    # 主动聊天的个人QQ号列表
    aichat_proactive_users: List[str] = []
    # 随机间隔范围（分钟）
    aichat_proactive_interval_min: int = 30
    aichat_proactive_interval_max: int = 90
    # 同一目标最短发送间隔（分钟）
    aichat_proactive_cooldown: int = 30
    # 免打扰时段（24小时制，支持跨天如 23-7）
    aichat_proactive_quiet_start: int = 0
    aichat_proactive_quiet_end: int = 8

    # ---- 群聊搭话（随机找话题）----
    aichat_interject_enabled: bool = False
    # 每次触发时机的搭话概率（0.0-1.0）
    aichat_interject_probability: float = 0.3
    # 搭话随机间隔范围（分钟）
    aichat_interject_interval_min: int = 30
    aichat_interject_interval_max: int = 90
    # 读聊天记录搭话时，查看最近消息数量（默认前十条）
    aichat_interject_history_count: int = 10

    # ---- 戳一戳（AI回复）----
    aichat_poke_enabled: bool = True
    # 同一人戳一戳回复冷却（秒），避免刷屏消耗token
    aichat_poke_cooldown: int = 30

    # ---- 旧版群聊随机参与（默认关闭，由新免@会话机制替代）----
    aichat_group_auto_participate: bool = False


config = get_plugin_config(PluginConfig)
