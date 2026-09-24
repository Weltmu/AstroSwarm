# -*- coding: utf-8 -*-
"""平台中立 AI 大脑：接收 ChannelMessage，输出回复（原 __init__.py 主处理器逻辑迁移）。

QQ 行为保持不回归；后续微信 ClawBot / 飞书 / 纸飞机接入时，
只需新增 adapters/<platform>.py，大脑无需改动。
"""
import asyncio
import json
import random
import time
from typing import Dict

from nonebot import logger

from .chat import get_chat_reply_with_tools, judge_user_continues, should_reply_in_group
from .context import add_message, clear_context, get_context
from . import identity as identity_store
from . import memory as memory_store
from .manager import chat_manager
from .platform import ChannelContext, ChannelMessage, SCENE_GROUP


# ===== 群聊免@会话状态（key: platform:room_id） =====
group_sessions: Dict[str, Dict[str, Dict[str, float]]] = {}
# key: platform:room_id -> 机器人最后一次回复的用户（原始平台 user_id）
last_reply_user: Dict[str, str] = {}


def session_is_active(group_key: str, user_key: str) -> bool:
    """检查用户是否处于免@会话有效期内（距上次机器人回复未超过设定秒数）"""
    session = group_sessions.get(group_key, {}).get(user_key)
    if not session:
        return False
    expire_seconds = chat_manager.get_session_expire_seconds()
    last = session.get("last_bot_reply", 0.0)
    if last <= 0 or (time.time() - last) >= expire_seconds:
        session_clear(group_key, user_key)
        return False
    return True


def session_activate(group_key: str, user_key: str) -> None:
    """激活/续期用户的免@会话，并清零无关消息计数"""
    session = group_sessions.setdefault(group_key, {}).setdefault(
        user_key, {"last_bot_reply": 0.0, "unrelated_count": 0}
    )
    session["last_bot_reply"] = time.time()
    session["unrelated_count"] = 0


def session_register_unrelated(group_key: str, user_key: str) -> bool:
    """记录一条与机器人无关的消息；达到上限结束免@会话。返回 True 表示会话已结束。"""
    session = group_sessions.get(group_key, {}).get(user_key)
    if not session:
        return False
    session["unrelated_count"] = int(session.get("unrelated_count", 0)) + 1
    limit = chat_manager.get_session_unrelated_limit()
    logger.info(f"用户{user_key} 连续无关消息 {session['unrelated_count']}/{limit}")
    if session["unrelated_count"] >= limit:
        session_clear(group_key, user_key)
        logger.info(f"用户{user_key} 连续 {limit} 条消息与机器人无关，免@会话已结束，下次需重新@")
        return True
    return False


def session_clear(group_key: str, user_key: str) -> None:
    """清除用户的免@会话"""
    sessions = group_sessions.get(group_key)
    if sessions and user_key in sessions:
        del sessions[user_key]


# ===== 群聊活跃度管理器（平台中立：key 为 platform:room_id） =====
group_timers: Dict[str, asyncio.Task] = {}
group_probability_states: Dict[str, float] = {}


class GroupProbabilityManager:
    """群聊智能参与管理器"""

    def __init__(self):
        self._shutting_down = False
        logger.info(
            f"活跃度管理器初始化完成，基础活跃度: {chat_manager.get_group_chat_probability()}"
        )

    async def _decay_task(self, group_key: str):
        try:
            while not self._shutting_down:
                await asyncio.sleep(60)
                if self._shutting_down:
                    break
                current_prob = group_probability_states.get(group_key, 0.0)
                new_prob = max(0, round(current_prob - 0.1, 2))
                group_probability_states[group_key] = new_prob
                logger.info(
                    f"群组 {group_key} 活跃度衰减: {current_prob:.2f} → {new_prob:.2f}"
                )
                if new_prob <= 0:
                    logger.info(f"群组 {group_key} 活跃度衰减结束")
                    if group_key in group_timers:
                        del group_timers[group_key]
                    if group_key in group_probability_states:
                        del group_probability_states[group_key]
                    break
        except asyncio.CancelledError:
            logger.info(f"群组 {group_key} 衰减任务被取消")
        except Exception as e:
            logger.error(f"群组 {group_key} 衰减任务异常: {e}")
            if group_key in group_timers:
                del group_timers[group_key]
            if group_key in group_probability_states:
                del group_probability_states[group_key]

    def renew_probability(self, group_key: str):
        if self._shutting_down:
            return False
        try:
            base_prob = chat_manager.get_group_chat_probability()
            group_probability_states[group_key] = round(base_prob, 2)
            if group_key in group_timers:
                task = group_timers[group_key]
                if not task.done():
                    task.cancel()
                del group_timers[group_key]
            task = asyncio.create_task(self._decay_task(group_key))
            group_timers[group_key] = task
            logger.info(f"群组 {group_key} 活跃度续租: {base_prob:.2f}")
            return True
        except Exception as e:
            logger.error(f"群组 {group_key} 续租失败: {e}")
            return False

    def get_probability(self, group_key: str) -> float:
        return group_probability_states.get(group_key, 0.0)

    def has_active_timer(self, group_key: str) -> bool:
        return group_key in group_timers and not group_timers[group_key].done()

    async def shutdown(self):
        self._shutting_down = True
        logger.info("开始关闭活跃度管理器...")
        for group_key, task in list(group_timers.items()):
            if not task.done():
                task.cancel()
        group_timers.clear()
        group_probability_states.clear()
        logger.info("活跃度管理器关闭完成")


group_manager: GroupProbabilityManager = GroupProbabilityManager()


# ===== 回复分段 =====
def _parse_reply_json(raw: str):
    try:
        return json.loads(raw)
    except Exception:
        pass
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`").strip()
        if text.lower().startswith("json"):
            text = text[4:].strip()
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except Exception:
            return None
    return None


async def _reply_in_segments(ctx: ChannelContext, raw: str, at_user: bool):
    """分段发送回复；群聊被@时第一段带@。"""
    if not raw:
        return
    data = _parse_reply_json(raw)
    if isinstance(data, dict) and "reply" in data and isinstance(data["reply"], list):
        segments = [s for s in data["reply"] if s and s.strip()]
    else:
        await ctx.notify_error("处理聊天请求时发生异常:\n AI 回复不是有效的 JSON 格式")
        return
    if not segments:
        return
    for i, segment in enumerate(segments):
        if i == 0 and at_user:
            await ctx.send_text_at(segment)
        else:
            await ctx.send_text(segment)
        if i < len(segments) - 1:
            await asyncio.sleep(random.uniform(0.4, 0.7))


# ===== 大脑主入口 =====
async def handle_message(msg: ChannelMessage, ctx: ChannelContext) -> None:
    """平台中立的聊天大脑：原 __init__.py 主处理器逻辑迁移而来。"""
    logger.info(f"[brain] 收到 {msg.platform} 消息 user={msg.user_id} text={msg.plain_text[:80]}")
    if not chat_manager.is_chat_enabled():
        logger.info("[brain] 聊天总开关已关闭，忽略")
        return

    is_group = msg.scene == SCENE_GROUP
    key = msg.context_key
    room = msg.session_key

    if is_group and not chat_manager.is_group_enabled(msg.room_id):
        return

    user_msg2 = msg.plain_text.strip()
    if user_msg2.startswith("ac "):
        return
    if user_msg2 in ("清除对话", "重置对话"):
        clear_context(key)
        if is_group:
            session_clear(room, msg.user_key)
        await ctx.send_text("已清除对话历史")
        return

    user_msg = msg.text
    context = get_context(key)

    if is_group:
        user_info = f"用户{msg.user_id}({msg.nickname or '未知用户'})说："
        add_message(key, "user", f"{user_info}: {user_msg}")

        should_reply = False
        if msg.is_at_me:
            should_reply = True
            logger.info("群聊中被@，准备回复")
            group_manager.renew_probability(room)
            session_activate(room, msg.user_key)
        elif session_is_active(room, msg.user_key):
            nickname = msg.nickname or "该用户"
            at_others = msg.extra.get("at_others", False)
            if at_others:
                should_reply = False
                logger.info(f"用户{msg.user_id}的消息@了其他人，视为与机器人无关，不回复")
                session_register_unrelated(room, msg.user_key)
            elif (
                last_reply_user.get(room) == msg.user_id
                and len(get_context(key)) >= 2
                and get_context(key)[-2]["role"] == "assistant"
            ):
                should_reply = True
                logger.info(f"用户{msg.user_id}直接延续对话（机器人上一条回复对象就是该用户），免AI判断")
                session_activate(room, msg.user_key)
            else:
                try:
                    should_reply = await judge_user_continues(
                        get_context(key),
                        msg.user_id,
                        nickname,
                        last_reply_to=last_reply_user.get(room, ""),
                    )
                except Exception as e:
                    error_msg = f"免@会话消息判断异常:\n {str(e)}"
                    await ctx.notify_error(error_msg)
                    should_reply = False
                if should_reply:
                    logger.info(f"AI判断用户{msg.user_id}在继续和机器人聊天，回复")
                    session_activate(room, msg.user_key)
                else:
                    logger.info(f"AI判断用户{msg.user_id}的消息与机器人无关，不回复")
                    session_register_unrelated(room, msg.user_key)
        elif chat_manager.is_group_auto_participate_enabled():
            dynamic_probability = group_manager.get_probability(room)
            if random.random() < dynamic_probability:
                try:
                    should_reply = await should_reply_in_group(get_context(key))
                except Exception as e:
                    error_msg = f"群聊对话判断异常:\n {str(e)}"
                    await ctx.notify_error(error_msg)
                    should_reply = False
                if should_reply:
                    logger.info("AI判断需要参与群聊讨论")
                    group_manager.renew_probability(room)
                else:
                    logger.info("AI判断不需要参与群聊讨论")
        else:
            should_reply = False

        if not should_reply:
            return
    else:
        add_message(key, "user", user_msg)

    try:
        # 注入长期记忆：全局 + 该用户（含绑定身份）的记忆
        ctx_messages = get_context(key)
        mem_text = ""
        if chat_manager.is_memory_enabled():
            mem_text = memory_store.format_memory_text(identity_store.resolve(msg.user_key))
        ai_messages = ctx_messages
        if mem_text:
            ai_messages = [
                {"role": "system", "content": "以下是长期记忆（如与当前对话无关可忽略）：\n" + mem_text}
            ] + ctx_messages
        reply = await get_chat_reply_with_tools(ai_messages, is_group)
        logger.info(f"[brain] AI 回复 {len(reply)} 字")
        add_message(key, "assistant", reply)
        if is_group:
            session_activate(room, msg.user_key)
            last_reply_user[room] = msg.user_id
        await _reply_in_segments(ctx, reply, at_user=msg.is_at_me and is_group)
    except Exception as e:
        error_msg = f"处理聊天请求时发生异常:\n {str(e)}"
        logger.error(f"[brain] 聊天异常: {e}")
        clear_context(key)
        await ctx.notify_error(error_msg)
        await ctx.send_text("抱歉，处理消息时出现了问题，已通知管理员")
