"""戳一戳 AI 回复模块（整合原 pokepoke_miss，回复内容由 AI 生成）"""

import time
from typing import Dict

from nonebot import logger, on_notice
from nonebot.adapters.onebot.v11 import PokeNotifyEvent

from .chat import get_poke_reply
from .config import config


def _poke_check(event: PokeNotifyEvent) -> bool:
    return event.target_id == event.self_id


poke = on_notice(rule=_poke_check, priority=100)

# 冷却记录：key = 群号:QQ号（私聊戳为 0:QQ号）
_last_poke_time: Dict[str, float] = {}


def _who_poked(event: PokeNotifyEvent) -> str:
    """戳你那个人的称呼：优先群名片，其次昵称；取不到就空串（AI 会当成熟人处理）。"""
    sender = getattr(event, "sender", None)
    if sender is None:
        return ""
    card = str(getattr(sender, "card", "") or "").strip()
    nickname = str(getattr(sender, "nickname", "") or "").strip()
    return card or nickname


@poke.handle()
async def handle_poke(bot, event: PokeNotifyEvent):
    if not config.aichat_poke_enabled:
        return

    cooldown = config.aichat_poke_cooldown
    key = f"{getattr(event, 'group_id', 0) or 0}:{event.user_id}"
    now = time.time()
    last = _last_poke_time.get(key, 0.0)
    if cooldown > 0 and now - last < cooldown:
        return

    try:
        # 把「谁戳的」一起交给 AI，回复才知道在对谁说话
        reply = await get_poke_reply(_who_poked(event))
        if not reply or not reply.strip():
            # AI 没生成出内容（或没配 AI）：这一次就不理人，不用任何固定话术顶上
            logger.info("戳一戳：本次没有生成回复，跳过发送")
            return
        _last_poke_time[key] = now
        await poke.send(reply.strip())
    except Exception as e:
        logger.error(f"戳一戳回复失败: {e}")
