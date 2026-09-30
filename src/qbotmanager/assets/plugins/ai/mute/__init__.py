"""
nonebot-plugin-mute-cat 插件入口

这个版本重构了命令识别、定时任务恢复、长期禁言计划和反馈文案
"""

from __future__ import annotations

import random
import time
from datetime import datetime, timedelta
from math import ceil
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import nonebot
from nonebot import get_driver, get_plugin_config, on_message, require
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message, MessageSegment
from nonebot.log import logger
from nonebot.matcher import Matcher
from nonebot.plugin import PluginMetadata
from nonebot.rule import Rule

from .config import Config

require("nonebot_plugin_apscheduler")
require("nonebot_plugin_localstore")

from nonebot_plugin_apscheduler import scheduler  # noqa: E402
import nonebot_plugin_localstore as store  # noqa: E402

from .storage import MuteStorage  # noqa: E402
from .utils import (  # noqa: E402
    BEIJING_TZ,
    LONG_MUTE_BUFFER_MINUTES,
    MAX_SINGLE_MUTE_MINUTES,
    ParsedCommand,
    STATUS_PAGE_SIZE,
    format_clock_minutes,
    format_datetime_display,
    format_duration_display,
    format_remaining_time,
    paginate_items,
    parse_user_command,
)

__version__ = "1.3.0"

__plugin_meta__ = PluginMetadata(
    name="The Betterest Mute Cat",
    description="极致的禁言猫猫，支持自然语言禁言、定时恢复、每日禁言、长期禁言和状态查看",
    usage=(
        "发送“帮助”查看基础说明，发送“使用细则”查看详细写法\n"
        "这个插件会尽量识别自然语言，但遇到歧义时会直接提示你换一种说法"
    ),
    type="application",
    homepage="https://github.com/binglang001/nonebot-plugin-mute-cat",
    config=Config,
    supported_adapters={"~onebot.v11"},
    extra={"author": "binglang", "version": __version__},
)

plugin_config = get_plugin_config(Config)
driver = get_driver()


def _migrate_mute_data() -> None:
    """把旧插件（nonebot_plugin_mute_cat）的禁言数据迁移到新插件目录（只迁移一次）"""
    try:
        for filename in ("at_overrides.json", "group_states.json"):
            new_file = store.get_plugin_data_file(filename)
            if new_file.exists():
                continue
            old = Path.cwd() / "data" / "nonebot_plugin_mute_cat" / filename
            if old.exists():
                new_file.parent.mkdir(parents=True, exist_ok=True)
                import shutil

                shutil.copy2(old, new_file)
                logger.info(f"已迁移禁言数据: {old} -> {new_file}")
    except Exception as e:
        logger.warning(f"迁移禁言数据失败: {e}")


_migrate_mute_data()
storage = MuteStorage()

group_states: Dict[int, Dict[str, Any]] = {}
at_overrides: Dict[int, bool] = {}

USER_TASK_TYPES = {"mute_start", "mute_refresh", "daily_user_mute"}
WHOLE_TASK_TYPES = {"whole_mute_start", "whole_unmute", "daily_whole_mute"}
DAILY_TASK_TYPES = {"daily_user_mute", "daily_whole_mute"}


def make_group_state() -> Dict[str, Any]:
    """创建默认群状态"""
    return {
        "whole_mute": {"enabled": False, "end_time": None, "duration": None},
        "individual_mutes": {},
        "tasks": {},
        "plans": {},
    }


def init_group_state(group_id: int) -> Dict[str, Any]:
    """确保群状态结构完整"""
    state = group_states.setdefault(group_id, make_group_state())
    state.setdefault("whole_mute", {"enabled": False, "end_time": None, "duration": None})
    state.setdefault("individual_mutes", {})
    state.setdefault("tasks", {})
    state.setdefault("plans", {})
    return state


def save_states() -> None:
    """统一保存状态"""
    storage.save_states(group_states)


def generate_record_id(group_id: int, prefix: str) -> str:
    """生成唯一记录标识"""
    timestamp = int(time.time() * 1000)
    random_suffix = random.randint(0, 9999)
    return f"{prefix}_{group_id}_{timestamp}_{random_suffix:04d}"


def get_need_at(group_id: int) -> bool:
    """获取当前群是否需要 @ 触发命令"""
    return at_overrides.get(group_id, plugin_config.mute_at_required)


def build_prefixed_message(title: str, lines: List[Message]) -> Message:
    """拼装带标题的多行消息"""
    message = Message(f"{title}\n")
    for index, line in enumerate(lines):
        message += line
        if index != len(lines) - 1:
            message += "\n"
    return message


def build_user_line(user_id: int, text: str) -> Message:
    """生成带 @ 的反馈行"""
    message = Message("• ")
    message += MessageSegment.at(user_id)
    message += f"：{text}"
    return message


def ensure_duration_minutes(duration_minutes: Optional[int]) -> int:
    """将空时长替换为默认值"""
    if duration_minutes is None:
        return plugin_config.mute_default_minutes
    return duration_minutes


def set_user_mute_state(
    group_id: int,
    user_id: int,
    end_time: datetime,
    duration_minutes: int,
    plan_id: Optional[str] = None,
) -> None:
    """写入当前生效的个人禁言状态"""
    state = init_group_state(group_id)
    state["individual_mutes"][user_id] = {
        "end_time": end_time,
        "duration": duration_minutes,
        "plan_id": plan_id,
    }
    save_states()


def remove_user_mute_state(group_id: int, user_id: int) -> Optional[Dict[str, Any]]:
    """移除个人禁言状态"""
    state = init_group_state(group_id)
    removed = state["individual_mutes"].pop(user_id, None)
    save_states()
    return removed


def set_whole_mute_state(
    group_id: int,
    enabled: bool,
    end_time: Optional[datetime],
    duration_minutes: Optional[int],
) -> None:
    """写入全员禁言状态"""
    state = init_group_state(group_id)
    state["whole_mute"] = {
        "enabled": enabled,
        "end_time": end_time,
        "duration": duration_minutes,
    }
    save_states()


def create_task_record(
    group_id: int,
    task_type: str,
    bot_id: str,
    execute_time: datetime,
    *,
    user_id: Optional[int] = None,
    end_time: Optional[datetime] = None,
    duration: Optional[int] = None,
    start_minutes: Optional[int] = None,
    plan_id: Optional[str] = None,
) -> str:
    """创建并保存定时任务记录"""
    state = init_group_state(group_id)
    task_id = generate_record_id(group_id, task_type)
    state["tasks"][task_id] = {
        "type": task_type,
        "bot_id": bot_id,
        "user_id": user_id,
        "execute_time": execute_time,
        "end_time": end_time,
        "duration": duration,
        "start_minutes": start_minutes,
        "plan_id": plan_id,
        "created_at": datetime.now(BEIJING_TZ),
    }
    save_states()
    return task_id


def remove_task_record(group_id: int, task_id: str) -> Optional[Dict[str, Any]]:
    """移除任务记录"""
    state = init_group_state(group_id)
    removed = state["tasks"].pop(task_id, None)
    save_states()
    return removed


def schedule_task_job(group_id: int, task_id: str, execute_time: datetime) -> None:
    """向 APScheduler 注册任务"""
    scheduler.add_job(
        func=scheduled_task_entry,
        trigger="date",
        run_date=execute_time,
        args=[group_id, task_id],
        id=task_id,
        replace_existing=True,
    )


def reschedule_task(group_id: int, task_id: str, execute_time: datetime) -> None:
    """更新任务执行时间并重新注册"""
    state = init_group_state(group_id)
    task = state["tasks"].get(task_id)
    if task is None:
        return

    task["execute_time"] = execute_time
    save_states()
    schedule_task_job(group_id, task_id, execute_time)


def create_long_plan(
    group_id: int,
    bot_id: str,
    user_id: int,
    final_end_time: datetime,
) -> str:
    """创建长期禁言计划"""
    state = init_group_state(group_id)
    plan_id = generate_record_id(group_id, "plan")
    state["plans"][plan_id] = {
        "bot_id": bot_id,
        "user_id": user_id,
        "end_time": final_end_time,
        "next_execute_time": None,
        "segment_end_time": None,
        "created_at": datetime.now(BEIJING_TZ),
        "last_execute_time": None,
    }
    save_states()
    return plan_id


def update_long_plan(
    group_id: int,
    plan_id: str,
    *,
    next_execute_time: Optional[datetime],
    segment_end_time: Optional[datetime],
    last_execute_time: Optional[datetime],
) -> None:
    """更新长期禁言计划"""
    state = init_group_state(group_id)
    plan = state["plans"].get(plan_id)
    if plan is None:
        return

    plan["next_execute_time"] = next_execute_time
    plan["segment_end_time"] = segment_end_time
    plan["last_execute_time"] = last_execute_time
    save_states()


def remove_long_plan(group_id: int, plan_id: str) -> Optional[Dict[str, Any]]:
    """移除长期禁言计划"""
    state = init_group_state(group_id)
    removed = state["plans"].pop(plan_id, None)
    for mute_state in state["individual_mutes"].values():
        if mute_state.get("plan_id") == plan_id:
            mute_state["plan_id"] = None
    save_states()
    return removed


@driver.on_startup
async def load_runtime_state() -> None:
    """插件启动时加载状态、清理过期记录并恢复调度"""
    global group_states, at_overrides
    group_states = storage.load_states()
    at_overrides = storage.load_at_overrides()
    for group_id in list(group_states):
        init_group_state(group_id)

    cleanup_finished_records()
    await restore_tasks()
    logger.opt(colors=True).success(
        f"<green>🐱 The Betterest Mute Cat 加载完成</green> | "
        f"群状态：{len(group_states)} | @ 覆盖：{len(at_overrides)}"
    )


async def is_group_admin(bot: Bot, group_id: int, user_id: int) -> bool:
    """检查用户是否为群管理员或群主"""
    try:
        info = await bot.get_group_member_info(
            group_id=group_id,
            user_id=user_id,
            no_cache=True,
        )
        return info.get("role", "member") in {"owner", "admin"}
    except Exception as exception:
        logger.opt(exception=exception).warning("获取群成员信息失败")
        return False


def is_superuser(user_id: str) -> bool:
    """判断用户是否为超级管理员"""
    return user_id in driver.config.superusers


async def check_admin_permission(bot: Bot, group_id: int, user_id: str) -> bool:
    """判断用户是否有管理权限"""
    if plugin_config.mute_superuser_only:
        return is_superuser(user_id)
    return is_superuser(user_id) or await is_group_admin(bot, group_id, int(user_id))


def parse_event_command(bot: Bot, event: GroupMessageEvent) -> Optional[ParsedCommand]:
    """重新解析命令，并排除机器人自身的 @"""
    exclude_user_ids: Set[int] = set()
    try:
        exclude_user_ids.add(int(str(bot.self_id)))
    except ValueError:
        pass

    return parse_user_command(
        event.message,
        event.get_plaintext().strip(),
        exclude_user_ids=exclude_user_ids,
    )


def is_supported_command(event: GroupMessageEvent) -> bool:
    """判断消息是否应由本插件接管"""
    exclude_user_ids: Set[int] = set()
    try:
        exclude_user_ids.add(int(str(event.self_id)))
    except (AttributeError, TypeError, ValueError):
        pass

    command = parse_user_command(
        event.message,
        event.get_plaintext().strip(),
        exclude_user_ids=exclude_user_ids,
    )
    if command is None:
        return False

    if get_need_at(event.group_id) and not event.is_tome():
        return False

    return True


command_rule = Rule(
    lambda event: isinstance(event, GroupMessageEvent) and is_supported_command(event),
)
command_matcher = on_message(
    rule=command_rule,
    priority=plugin_config.mute_command_priority,
    block=True,
)


def cleanup_finished_records() -> None:
    """清理已经结束的状态和无效任务"""
    now = datetime.now(BEIJING_TZ)
    changed = False

    for state in group_states.values():
        whole_mute = state["whole_mute"]
        if (
            whole_mute.get("enabled")
            and whole_mute.get("end_time") is not None
            and whole_mute["end_time"] <= now
        ):
            state["whole_mute"] = {"enabled": False, "end_time": None, "duration": None}
            changed = True

        expired_users = [
            user_id
            for user_id, info in state["individual_mutes"].items()
            if info.get("end_time") and info["end_time"] <= now
        ]
        for user_id in expired_users:
            plan_id = state["individual_mutes"][user_id].get("plan_id")
            state["individual_mutes"].pop(user_id, None)
            if plan_id:
                plan = state["plans"].get(plan_id)
                if plan and plan.get("end_time") and plan["end_time"] <= now:
                    state["plans"].pop(plan_id, None)
            changed = True

        expired_plans = [
            plan_id
            for plan_id, plan in state["plans"].items()
            if plan.get("end_time") and plan["end_time"] <= now
        ]
        for plan_id in expired_plans:
            state["plans"].pop(plan_id, None)
            changed = True

        expired_tasks: List[str] = []
        for task_id, task in state["tasks"].items():
            task_type = task.get("type")
            execute_time = task.get("execute_time")
            end_time = task.get("end_time")
            if execute_time is None:
                expired_tasks.append(task_id)
                continue

            if task_type in {"mute_start", "mute_refresh"} and end_time and end_time <= now:
                expired_tasks.append(task_id)
            elif task_type == "whole_mute_start" and end_time and end_time <= now:
                expired_tasks.append(task_id)
            elif task_type == "whole_unmute" and not state["whole_mute"].get("enabled"):
                expired_tasks.append(task_id)
            elif task_type in DAILY_TASK_TYPES:
                if task.get("start_minutes") is None or task.get("duration") is None:
                    expired_tasks.append(task_id)

        for task_id in expired_tasks:
            try:
                scheduler.remove_job(task_id)
            except Exception:
                pass
            state["tasks"].pop(task_id, None)
            changed = True

    if changed:
        save_states()


async def restore_tasks() -> None:
    """根据持久化状态重建调度任务"""
    now = datetime.now(BEIJING_TZ)
    delayed_execute_time = now + timedelta(seconds=5)

    for group_id, state in group_states.items():
        for task_id, task in list(state["tasks"].items()):
            task_type = task.get("type")
            execute_time = task.get("execute_time")
            end_time = task.get("end_time")

            if execute_time is None:
                remove_task_record(group_id, task_id)
                continue

            if task_type in {"mute_start", "mute_refresh"}:
                if end_time is not None and end_time <= now:
                    remove_task_record(group_id, task_id)
                    continue
                if execute_time <= now:
                    reschedule_task(group_id, task_id, delayed_execute_time)
                else:
                    schedule_task_job(group_id, task_id, execute_time)
                continue

            if task_type == "whole_mute_start":
                if end_time is not None and end_time <= now:
                    remove_task_record(group_id, task_id)
                    continue
                if execute_time <= now:
                    reschedule_task(group_id, task_id, delayed_execute_time)
                else:
                    schedule_task_job(group_id, task_id, execute_time)
                continue

            if task_type == "whole_unmute":
                if execute_time <= now:
                    reschedule_task(group_id, task_id, delayed_execute_time)
                else:
                    schedule_task_job(group_id, task_id, execute_time)
                continue

            if task_type in DAILY_TASK_TYPES:
                normalized_task = normalize_daily_task_record(
                    group_id,
                    task_id,
                    now=now,
                )
                if normalized_task is None:
                    continue

                execute_time = normalized_task.get("execute_time")
                daily_end_time = get_daily_task_end_time(normalized_task)
                if execute_time is None or daily_end_time is None:
                    remove_task_record(group_id, task_id)
                    continue

                if execute_time <= now < daily_end_time:
                    schedule_task_job(group_id, task_id, delayed_execute_time)
                else:
                    schedule_task_job(group_id, task_id, execute_time)
                continue

            remove_task_record(group_id, task_id)

def classify_ban_exception(user_id: int, exception: Exception) -> str:
    """将平台异常转成可读反馈"""
    del user_id
    message = str(exception)
    if "1200" in message or "1287" in message:
        return "机器人权限不够喵~"
    if "1202" in message:
        return "这个人已经不在群里啦喵~"
    if "1203" in message:
        return "群主不能这样处理喵~"
    if "1204" in message:
        return "管理员不能这样处理喵~"
    return message


async def retry_task_later(group_id: int, task_id: str) -> None:
    """当机器人暂时不在线时，延后重试任务"""
    state = init_group_state(group_id)
    task = state["tasks"].get(task_id)
    if task is None:
        return

    if task.get("type") in DAILY_TASK_TYPES:
        normalized_task = normalize_daily_task_record(group_id, task_id)
        if normalized_task is None:
            return

        daily_end_time = get_daily_task_end_time(normalized_task)
        if daily_end_time is None:
            remove_task_record(group_id, task_id)
            return
        if daily_end_time <= datetime.now(BEIJING_TZ):
            advance_daily_task_to_next_run(group_id, task_id)
            return

        schedule_task_job(group_id, task_id, datetime.now(BEIJING_TZ) + timedelta(minutes=1))
        return

    end_time = task.get("end_time")
    if end_time and end_time <= datetime.now(BEIJING_TZ):
        remove_task_record(group_id, task_id)
        return

    reschedule_task(group_id, task_id, datetime.now(BEIJING_TZ) + timedelta(minutes=1))


async def scheduled_task_entry(group_id: int, task_id: str) -> None:
    """定时任务统一入口"""
    state = init_group_state(group_id)
    task = state["tasks"].get(task_id)
    if task is None:
        return

    bot_id = str(task.get("bot_id", ""))
    try:
        bot = nonebot.get_bot(bot_id)
    except KeyError:
        logger.warning(f"Bot {bot_id} 当前不在线，任务 {task_id} 稍后重试")
        await retry_task_later(group_id, task_id)
        return

    task_type = task.get("type")
    if task_type == "mute_start":
        await execute_scheduled_user_mute(bot, group_id, task_id)
        return
    if task_type == "mute_refresh":
        await execute_long_plan_refresh(bot, group_id, task_id)
        return
    if task_type == "whole_mute_start":
        await execute_scheduled_whole_mute(bot, group_id, task_id)
        return
    if task_type == "whole_unmute":
        await execute_whole_unmute(bot, group_id, task_id=task_id, announce=True)
        return
    if task_type == "daily_user_mute":
        await execute_daily_user_mute(bot, group_id, task_id)
        return
    if task_type == "daily_whole_mute":
        await execute_daily_whole_mute(bot, group_id, task_id)
        return

    remove_task_record(group_id, task_id)


def clear_user_scheduled_state(group_id: int, user_id: int) -> Tuple[int, int]:
    """清除用户未来禁言任务、每日任务与长期计划"""
    state = init_group_state(group_id)
    task_ids = [
        task_id
        for task_id, task in state["tasks"].items()
        if task.get("user_id") == user_id
        and task.get("type") in USER_TASK_TYPES
    ]
    plan_ids = [
        plan_id for plan_id, plan in state["plans"].items() if plan.get("user_id") == user_id
    ]

    for task_id in task_ids:
        try:
            scheduler.remove_job(task_id)
        except Exception:
            pass
        state["tasks"].pop(task_id, None)

    for plan_id in plan_ids:
        state["plans"].pop(plan_id, None)

    mute_state = state["individual_mutes"].get(user_id)
    if mute_state and mute_state.get("plan_id") in plan_ids:
        mute_state["plan_id"] = None

    save_states()
    return len(task_ids), len(plan_ids)


def remove_task_records(group_id: int, task_ids: List[str]) -> int:
    """批量移除任务记录并注销调度器任务"""
    if not task_ids:
        return 0

    state = init_group_state(group_id)
    removed_count = 0
    for task_id in task_ids:
        try:
            scheduler.remove_job(task_id)
        except Exception:
            pass
        if state["tasks"].pop(task_id, None) is not None:
            removed_count += 1

    if removed_count:
        save_states()
    return removed_count


def clear_user_long_plan_runtime(group_id: int, user_id: int) -> Tuple[int, int]:
    """清除用户当前长期禁言运行态，但保留普通定时任务"""
    state = init_group_state(group_id)
    task_ids = [
        task_id
        for task_id, task in state["tasks"].items()
        if task.get("user_id") == user_id and task.get("type") == "mute_refresh"
    ]
    plan_ids = [
        plan_id
        for plan_id, plan in state["plans"].items()
        if plan.get("user_id") == user_id
    ]

    for task_id in task_ids:
        try:
            scheduler.remove_job(task_id)
        except Exception:
            pass
        state["tasks"].pop(task_id, None)

    for plan_id in plan_ids:
        state["plans"].pop(plan_id, None)

    mute_state = state["individual_mutes"].get(user_id)
    if mute_state and mute_state.get("plan_id") in plan_ids:
        mute_state["plan_id"] = None

    if task_ids or plan_ids:
        save_states()
    return len(task_ids), len(plan_ids)


def calculate_interval_minutes(start_time: datetime, end_time: datetime) -> int:
    """计算两个时间点之间对应的分钟数"""
    return max(1, ceil((end_time - start_time).total_seconds() / 60))


def build_daily_execute_time(now: datetime, start_minutes: int) -> datetime:
    """根据当天分钟数计算下一次每日任务执行时间"""
    hours, minutes = divmod(start_minutes, 60)
    execute_time = now.replace(hour=hours, minute=minutes, second=0, microsecond=0)
    if execute_time <= now:
        execute_time += timedelta(days=1)
    return execute_time


def get_next_daily_execute_time(execute_time: datetime, start_minutes: int) -> datetime:
    """根据上一轮执行时间计算下一次每日任务时间"""
    hours, minutes = divmod(start_minutes, 60)
    next_time = execute_time + timedelta(days=1)
    return next_time.replace(hour=hours, minute=minutes, second=0, microsecond=0)


def get_daily_task_end_time(task: Dict[str, Any]) -> Optional[datetime]:
    """计算每日任务这一轮对应的结束时间"""
    execute_time = task.get("execute_time")
    duration = task.get("duration")
    if execute_time is None or duration is None:
        return None
    return execute_time + timedelta(minutes=duration)


def format_daily_task_window(start_minutes: int, duration_minutes: int) -> str:
    """格式化每日任务的时间区间"""
    end_minutes = start_minutes + duration_minutes
    start_text = format_clock_minutes(start_minutes)
    end_text = format_clock_minutes(end_minutes)
    if duration_minutes >= 24 * 60:
        return f"每天 {start_text} 开始，持续 24 小时"
    if end_minutes >= 24 * 60:
        return f"每天 {start_text} 开始，到次日 {end_text} 结束"
    return f"每天 {start_text} 开始，到 {end_text} 结束"


def normalize_daily_task_record(
    group_id: int,
    task_id: str,
    *,
    now: Optional[datetime] = None,
) -> Optional[Dict[str, Any]]:
    """将错过执行窗口的每日任务推进到仍有效的下一轮"""
    state = init_group_state(group_id)
    task = state["tasks"].get(task_id)
    if task is None:
        return None

    execute_time = task.get("execute_time")
    start_minutes = task.get("start_minutes")
    duration = task.get("duration")
    if execute_time is None or start_minutes is None or duration is None or duration <= 0:
        remove_task_record(group_id, task_id)
        return None

    now = now or datetime.now(BEIJING_TZ)
    changed = False
    while execute_time + timedelta(minutes=duration) <= now:
        execute_time = get_next_daily_execute_time(execute_time, start_minutes)
        task["execute_time"] = execute_time
        changed = True

    if changed:
        save_states()
    return task


def advance_daily_task_to_next_run(group_id: int, task_id: str) -> Optional[datetime]:
    """将每日任务推进到下一次执行时间并重新注册调度"""
    state = init_group_state(group_id)
    task = state["tasks"].get(task_id)
    if task is None:
        return None

    execute_time = task.get("execute_time")
    start_minutes = task.get("start_minutes")
    if execute_time is None or start_minutes is None:
        remove_task_record(group_id, task_id)
        return None

    next_execute_time = get_next_daily_execute_time(execute_time, start_minutes)
    task["execute_time"] = next_execute_time
    save_states()
    schedule_task_job(group_id, task_id, next_execute_time)
    return next_execute_time


def collect_conflicting_daily_tasks(
    group_id: int,
    task_type: str,
    start_minutes: int,
    duration_minutes: int,
    *,
    user_id: Optional[int] = None,
) -> Tuple[int, int, List[str]]:
    """收集与目标每日区间冲突的每日任务，并自动合并时间范围"""
    state = init_group_state(group_id)
    merged_start = start_minutes
    merged_end = start_minutes + duration_minutes
    merged_task_ids: Set[str] = set()

    changed = True
    while changed:
        changed = False
        for task_id, task in state["tasks"].items():
            if task_id in merged_task_ids or task.get("type") != task_type:
                continue
            if user_id is not None and task.get("user_id") != user_id:
                continue

            task_start = task.get("start_minutes")
            task_duration = task.get("duration")
            if task_start is None or task_duration is None or task_duration <= 0:
                continue

            for offset in (-24 * 60, 0, 24 * 60):
                shifted_start = task_start + offset
                shifted_end = shifted_start + task_duration
                if shifted_start < merged_end and merged_start < shifted_end:
                    merged_start = min(merged_start, shifted_start)
                    merged_end = max(merged_end, shifted_end)
                    merged_task_ids.add(task_id)
                    changed = True
                    break

    merged_duration = min(24 * 60, merged_end - merged_start)
    normalized_start = 0 if merged_duration >= 24 * 60 else merged_start % (24 * 60)
    return normalized_start, merged_duration, list(merged_task_ids)


def create_or_merge_daily_user_mute_task(
    group_id: int,
    bot_id: str,
    user_id: int,
    start_minutes: int,
    duration_minutes: int,
) -> Tuple[datetime, int, int, int]:
    """创建每日个人禁言任务，若冲突则自动合并"""
    merged_start, merged_duration, conflict_task_ids = collect_conflicting_daily_tasks(
        group_id,
        "daily_user_mute",
        start_minutes,
        duration_minutes,
        user_id=user_id,
    )
    removed_task_count = remove_task_records(group_id, conflict_task_ids)
    execute_time = build_daily_execute_time(datetime.now(BEIJING_TZ), merged_start)
    task_id = create_task_record(
        group_id,
        "daily_user_mute",
        bot_id,
        execute_time,
        user_id=user_id,
        duration=merged_duration,
        start_minutes=merged_start,
    )
    schedule_task_job(group_id, task_id, execute_time)
    return execute_time, merged_start, merged_duration, removed_task_count


def create_or_merge_daily_whole_mute_task(
    group_id: int,
    bot_id: str,
    start_minutes: int,
    duration_minutes: int,
) -> Tuple[datetime, int, int, int]:
    """创建每日全员禁言任务，若冲突则自动合并"""
    merged_start, merged_duration, conflict_task_ids = collect_conflicting_daily_tasks(
        group_id,
        "daily_whole_mute",
        start_minutes,
        duration_minutes,
    )
    removed_task_count = remove_task_records(group_id, conflict_task_ids)
    execute_time = build_daily_execute_time(datetime.now(BEIJING_TZ), merged_start)
    task_id = create_task_record(
        group_id,
        "daily_whole_mute",
        bot_id,
        execute_time,
        duration=merged_duration,
        start_minutes=merged_start,
    )
    schedule_task_job(group_id, task_id, execute_time)
    return execute_time, merged_start, merged_duration, removed_task_count


def get_user_current_final_end(
    group_id: int,
    user_id: int,
    *,
    now: Optional[datetime] = None,
) -> Optional[datetime]:
    """获取用户当前正在生效禁言的最终结束时间"""
    state = init_group_state(group_id)
    now = now or datetime.now(BEIJING_TZ)
    mute_state = state["individual_mutes"].get(user_id)
    if (
        mute_state is None
        or mute_state.get("end_time") is None
        or mute_state["end_time"] <= now
    ):
        return None

    final_end_time = mute_state["end_time"]
    plan_id = mute_state.get("plan_id")
    if plan_id:
        plan = state["plans"].get(plan_id)
        if plan and plan.get("end_time") and plan["end_time"] > final_end_time:
            final_end_time = plan["end_time"]
    return final_end_time


def collect_conflicting_user_mute_tasks(
    group_id: int,
    user_id: int,
    start_time: datetime,
    end_time: datetime,
) -> Tuple[datetime, datetime, List[str]]:
    """收集与目标区间冲突的未来个人定时任务，并合并时间范围"""
    state = init_group_state(group_id)
    merged_start = start_time
    merged_end = end_time
    merged_task_ids: Set[str] = set()

    changed = True
    while changed:
        changed = False
        for task_id, task in state["tasks"].items():
            if task_id in merged_task_ids:
                continue
            if task.get("user_id") != user_id or task.get("type") != "mute_start":
                continue

            task_start = task.get("execute_time")
            task_end = task.get("end_time")
            if task_start is None or task_end is None:
                continue

            if task_start < merged_end and merged_start < task_end:
                merged_start = min(merged_start, task_start)
                merged_end = max(merged_end, task_end)
                merged_task_ids.add(task_id)
                changed = True

    return merged_start, merged_end, list(merged_task_ids)


async def apply_merged_current_user_mute(
    bot: Bot,
    group_id: int,
    user_id: int,
    final_end_time: datetime,
) -> Tuple[bool, Optional[str], Optional[datetime], datetime, int, bool]:
    """将当前禁言与冲突任务合并后立即执行"""
    now = datetime.now(BEIJING_TZ)
    current_final_end = get_user_current_final_end(group_id, user_id, now=now)
    current_extended = bool(current_final_end and current_final_end > now)
    merged_end_time = max(final_end_time, current_final_end or final_end_time)

    _, merged_end_time, conflict_task_ids = collect_conflicting_user_mute_tasks(
        group_id,
        user_id,
        now,
        merged_end_time,
    )
    removed_task_count = remove_task_records(group_id, conflict_task_ids)
    clear_user_long_plan_runtime(group_id, user_id)

    success, error_message, segment_end_time = await apply_user_mute_segment(
        bot,
        group_id,
        user_id,
        merged_end_time,
        plan_id=None,
        reset_first=True,
    )
    return (
        success,
        error_message,
        segment_end_time,
        merged_end_time,
        removed_task_count,
        current_extended,
    )


def create_or_merge_future_user_mute_task(
    group_id: int,
    bot_id: str,
    user_id: int,
    start_time: datetime,
    end_time: datetime,
) -> Tuple[datetime, datetime, int]:
    """创建未来个人定时禁言任务，若冲突则自动合并"""
    merged_start, merged_end, conflict_task_ids = collect_conflicting_user_mute_tasks(
        group_id,
        user_id,
        start_time,
        end_time,
    )
    removed_task_count = remove_task_records(group_id, conflict_task_ids)

    task_id = create_task_record(
        group_id,
        "mute_start",
        bot_id,
        merged_start,
        user_id=user_id,
        end_time=merged_end,
        duration=calculate_interval_minutes(merged_start, merged_end),
    )
    schedule_task_job(group_id, task_id, merged_start)
    return merged_start, merged_end, removed_task_count


def clear_whole_scheduled_state(
    group_id: int,
    *,
    preserve_current_unmute: bool = False,
    include_daily: bool = False,
) -> int:
    """清除全员禁言相关任务，可按需保留当前自动解禁任务"""
    state = init_group_state(group_id)
    current_end_time = None
    if preserve_current_unmute and state["whole_mute"].get("enabled"):
        current_end_time = state["whole_mute"].get("end_time")

    allowed_types = {"whole_mute_start", "whole_unmute"}
    if include_daily:
        allowed_types.add("daily_whole_mute")

    task_ids = []
    for task_id, task in state["tasks"].items():
        if task.get("type") not in allowed_types:
            continue
        if (
            current_end_time is not None
            and task.get("type") == "whole_unmute"
            and task.get("execute_time") == current_end_time
        ):
            continue
        task_ids.append(task_id)

    for task_id in task_ids:
        try:
            scheduler.remove_job(task_id)
        except Exception:
            pass
        state["tasks"].pop(task_id, None)

    save_states()
    return len(task_ids)


def clear_active_whole_unmute_task(group_id: int) -> int:
    """只移除当前生效中的全员禁言自动解禁任务"""
    state = init_group_state(group_id)
    whole_mute = state["whole_mute"]
    current_end_time = whole_mute.get("end_time")
    if not whole_mute.get("enabled") or current_end_time is None:
        return 0

    task_ids = [
        task_id
        for task_id, task in state["tasks"].items()
        if task.get("type") == "whole_unmute"
        and task.get("execute_time") == current_end_time
    ]
    for task_id in task_ids:
        try:
            scheduler.remove_job(task_id)
        except Exception:
            pass
        state["tasks"].pop(task_id, None)

    save_states()
    return len(task_ids)


async def apply_user_mute_segment(
    bot: Bot,
    group_id: int,
    user_id: int,
    final_end_time: datetime,
    *,
    plan_id: Optional[str] = None,
    reset_first: bool = False,
) -> Tuple[bool, Optional[str], Optional[datetime]]:
    """执行一段个人禁言，并按需安排长期禁言续期"""
    now = datetime.now(BEIJING_TZ)
    remaining_seconds = int((final_end_time - now).total_seconds())
    if remaining_seconds <= 0:
        return False, "结束时间已经过去啦，猫猫就不再补禁言了喵~", None
    remaining_minutes = max(1, (remaining_seconds + 59) // 60)

    if await is_group_admin(bot, group_id, user_id):
        return False, "目标是群管理或群主，猫猫没法动手喵~", None

    segment_minutes = min(remaining_minutes, MAX_SINGLE_MUTE_MINUTES)
    segment_end_time = now + timedelta(minutes=segment_minutes)

    try:
        if reset_first:
            await bot.set_group_ban(group_id=group_id, user_id=user_id, duration=0)
        await bot.set_group_ban(
            group_id=group_id,
            user_id=user_id,
            duration=segment_minutes * 60,
        )
    except Exception as exception:
        return False, classify_ban_exception(user_id, exception), None

    current_plan_id = plan_id
    if remaining_minutes > MAX_SINGLE_MUTE_MINUTES:
        if current_plan_id is None:
            current_plan_id = create_long_plan(
                group_id,
                str(bot.self_id),
                user_id,
                final_end_time,
            )

        next_execute_time = segment_end_time - timedelta(
            minutes=LONG_MUTE_BUFFER_MINUTES
        )
        if next_execute_time <= now:
            next_execute_time = now + timedelta(minutes=1)

        task_id = create_task_record(
            group_id,
            "mute_refresh",
            str(bot.self_id),
            next_execute_time,
            user_id=user_id,
            end_time=final_end_time,
            plan_id=current_plan_id,
        )
        schedule_task_job(group_id, task_id, next_execute_time)
        update_long_plan(
            group_id,
            current_plan_id,
            next_execute_time=next_execute_time,
            segment_end_time=segment_end_time,
            last_execute_time=now,
        )
    elif current_plan_id is not None:
        update_long_plan(
            group_id,
            current_plan_id,
            next_execute_time=None,
            segment_end_time=segment_end_time,
            last_execute_time=now,
        )

    set_user_mute_state(
        group_id,
        user_id,
        segment_end_time,
        remaining_minutes,
        current_plan_id,
    )
    return True, None, segment_end_time


async def execute_direct_user_mute(
    bot: Bot,
    group_id: int,
    user_id: int,
    duration_minutes: int,
) -> Tuple[bool, str]:
    """执行即时个人禁言"""
    final_end_time = datetime.now(BEIJING_TZ) + timedelta(minutes=duration_minutes)
    success, error_message, segment_end_time, merged_final_end, merged_task_count, current_extended = (
        await apply_merged_current_user_mute(
            bot,
            group_id,
            user_id,
            final_end_time,
        )
    )
    if not success or segment_end_time is None:
        return False, error_message or "执行失败了喵~"

    merged_duration_minutes = calculate_interval_minutes(
        datetime.now(BEIJING_TZ),
        merged_final_end,
    )
    parts: List[str] = []
    if merged_duration_minutes > MAX_SINGLE_MUTE_MINUTES:
        parts.append(
            "已经开始长期禁言啦，"
            f"当前这一段会持续到 {format_datetime_display(segment_end_time)}，"
            f"最终会在 {format_datetime_display(merged_final_end)} 自动结束喵~"
        )
    else:
        parts.append(
            f"已经禁言到 {format_datetime_display(merged_final_end)} 啦，"
            f"共 {format_duration_display(merged_duration_minutes)} 喵~"
        )

    if current_extended:
        parts.append("原本已经生效的禁言也一起并到这次结果里了喵~")
    if merged_task_count:
        parts.append(f"另外顺手把 {merged_task_count} 条冲突的定时任务合并掉啦喵~")

    return True, " ".join(parts)


async def execute_scheduled_user_mute(bot: Bot, group_id: int, task_id: str) -> None:
    """执行定时个人禁言任务"""
    state = init_group_state(group_id)
    task = state["tasks"].get(task_id)
    if task is None:
        return

    user_id = task.get("user_id")
    end_time = task.get("end_time")
    if user_id is None or end_time is None:
        remove_task_record(group_id, task_id)
        return

    if end_time <= datetime.now(BEIJING_TZ):
        remove_task_record(group_id, task_id)
        return

    remove_task_record(group_id, task_id)
    success, error_message, segment_end_time, merged_final_end, merged_task_count, current_extended = (
        await apply_merged_current_user_mute(
            bot,
            group_id,
            user_id,
            end_time,
        )
    )
    if not success or segment_end_time is None:
        await bot.send_group_msg(
            group_id=group_id,
            message=build_prefixed_message(
                "猫猫按时去执行定时禁言了喵，不过出了点问题：",
                [build_user_line(user_id, error_message or "执行失败了喵~")],
            ),
        )
        return

    details: List[str] = []
    if merged_final_end > segment_end_time:
        details.append(
            f"定时禁言已经生效啦，当前这一段先到 {format_datetime_display(segment_end_time)}，"
            f"最终会在 {format_datetime_display(merged_final_end)} 结束喵~"
        )
    else:
        details.append(f"定时禁言已经生效啦，会持续到 {format_datetime_display(merged_final_end)} 喵~")

    if current_extended:
        details.append("它和当前已经生效的禁言撞上了，所以猫猫已经自动合并啦喵~")
    if merged_task_count:
        details.append(f"另外还把 {merged_task_count} 条后续冲突任务一并合并掉啦喵~")

    await bot.send_group_msg(
        group_id=group_id,
        message=build_prefixed_message(
            "猫猫按约定时间把禁言挂上去啦：",
            [build_user_line(user_id, " ".join(details))],
        ),
    )


async def execute_long_plan_refresh(bot: Bot, group_id: int, task_id: str) -> None:
    """执行长期禁言续期任务"""
    state = init_group_state(group_id)
    task = state["tasks"].get(task_id)
    if task is None:
        return

    end_time = task.get("end_time")
    user_id = task.get("user_id")
    if end_time is None or user_id is None:
        remove_task_record(group_id, task_id)
        return

    remove_task_record(group_id, task_id)
    success, error_message, segment_end_time = await apply_user_mute_segment(
        bot,
        group_id,
        user_id,
        end_time,
        plan_id=task.get("plan_id"),
        reset_first=True,
    )
    if not success or segment_end_time is None:
        await bot.send_group_msg(
            group_id=group_id,
            message=build_prefixed_message(
                "猫猫去续上长期禁言时出了点问题喵：",
                [build_user_line(user_id, error_message or "续期失败了喵~")],
            ),
        )
        return

    if end_time > segment_end_time:
        detail = (
            f"长期禁言已经续上啦，当前这一段到 {format_datetime_display(segment_end_time)}，"
            f"最终结束时间还是 {format_datetime_display(end_time)} 喵~"
        )
    else:
        detail = f"长期禁言已经进入最后一段啦，会在 {format_datetime_display(end_time)} 结束喵~"

    await bot.send_group_msg(
        group_id=group_id,
        message=build_prefixed_message(
            "猫猫已经把长期禁言继续接上啦：",
            [build_user_line(user_id, detail)],
        ),
    )


async def execute_whole_mute(
    bot: Bot,
    group_id: int,
    duration_minutes: Optional[int],
    *,
    announce: bool,
) -> Tuple[bool, str]:
    """执行即时全员禁言"""
    clear_whole_scheduled_state(group_id)
    now = datetime.now(BEIJING_TZ)
    end_time = None
    if duration_minutes is not None:
        end_time = now + timedelta(minutes=duration_minutes)

    try:
        await bot.set_group_whole_ban(group_id=group_id, enable=True)
    except Exception as exception:
        return False, f"全员禁言失败了喵：{exception}"

    set_whole_mute_state(group_id, True, end_time, duration_minutes)

    if end_time is not None:
        task_id = create_task_record(
            group_id,
            "whole_unmute",
            str(bot.self_id),
            end_time,
            end_time=end_time,
            duration=duration_minutes,
        )
        schedule_task_job(group_id, task_id, end_time)
        detail = (
            f"全员禁言已经生效啦，会持续到 {format_datetime_display(end_time)}，"
            f"共 {format_duration_display(duration_minutes)} 喵~"
        )
    else:
        detail = "全员禁言已经生效啦，没有单独写时长的话，就会一直保持到有人手动解除喵~"

    if announce:
        await bot.send_group_msg(
            group_id=group_id,
            message=build_prefixed_message("猫猫已经把全员禁言挂上去啦：", [Message(detail)]),
        )

    return True, detail


async def execute_scheduled_whole_mute(bot: Bot, group_id: int, task_id: str) -> None:
    """执行定时全员禁言"""
    state = init_group_state(group_id)
    task = state["tasks"].get(task_id)
    if task is None:
        return

    duration_minutes = task.get("duration")
    end_time = task.get("end_time")
    if end_time and end_time <= datetime.now(BEIJING_TZ):
        remove_task_record(group_id, task_id)
        return

    remove_task_record(group_id, task_id)
    await execute_whole_mute(bot, group_id, duration_minutes, announce=True)


async def execute_daily_user_mute(bot: Bot, group_id: int, task_id: str) -> None:
    """执行每日个人禁言任务"""
    task = normalize_daily_task_record(group_id, task_id)
    if task is None:
        return

    user_id = task.get("user_id")
    daily_end_time = get_daily_task_end_time(task)
    if user_id is None or daily_end_time is None:
        remove_task_record(group_id, task_id)
        return

    if daily_end_time <= datetime.now(BEIJING_TZ):
        advance_daily_task_to_next_run(group_id, task_id)
        return

    success, error_message, segment_end_time, merged_final_end, merged_task_count, current_extended = (
        await apply_merged_current_user_mute(
            bot,
            group_id,
            user_id,
            daily_end_time,
        )
    )
    next_execute_time = advance_daily_task_to_next_run(group_id, task_id)

    if not success or segment_end_time is None:
        next_text = (
            f"下一轮会在 {format_datetime_display(next_execute_time)} 再试一次喵~"
            if next_execute_time is not None
            else "不过这条每日任务已经没法继续保留了喵~"
        )
        await bot.send_group_msg(
            group_id=group_id,
            message=build_prefixed_message(
                "猫猫去执行今天这轮每日禁言时出了点问题喵：",
                [build_user_line(user_id, f"{error_message or '执行失败了喵~'} {next_text}")],
            ),
        )
        return

    details: List[str] = [
        f"今天这轮每日禁言已经生效啦，当前会持续到 {format_datetime_display(merged_final_end)} 喵~",
    ]
    if merged_final_end > daily_end_time:
        details.append("因为它和已经生效的禁言撞上了，所以猫猫按合并后的更晚结束时间处理啦喵~")
    if current_extended:
        details.append("当前已生效的禁言也一起并进结果里啦喵~")
    if merged_task_count:
        details.append(f"另外还顺手合并了 {merged_task_count} 条冲突的一次性定时任务喵~")
    if next_execute_time is not None:
        details.append(f"下一轮会在 {format_datetime_display(next_execute_time)} 再来喵~")

    await bot.send_group_msg(
        group_id=group_id,
        message=build_prefixed_message(
            "猫猫已经按每日约定把禁言挂上去啦：",
            [build_user_line(user_id, " ".join(details))],
        ),
    )


async def execute_daily_whole_mute(bot: Bot, group_id: int, task_id: str) -> None:
    """执行每日全员禁言任务"""
    task = normalize_daily_task_record(group_id, task_id)
    if task is None:
        return

    daily_end_time = get_daily_task_end_time(task)
    duration_minutes = task.get("duration")
    if daily_end_time is None or duration_minutes is None:
        remove_task_record(group_id, task_id)
        return

    if daily_end_time <= datetime.now(BEIJING_TZ):
        advance_daily_task_to_next_run(group_id, task_id)
        return

    success, detail = await execute_whole_mute(
        bot,
        group_id,
        duration_minutes,
        announce=False,
    )
    next_execute_time = advance_daily_task_to_next_run(group_id, task_id)

    next_text = (
        f"下一轮会在 {format_datetime_display(next_execute_time)} 再开启喵~"
        if next_execute_time is not None
        else "不过这条每日全员任务已经没法继续保留了喵~"
    )
    title = "猫猫已经把今天这轮每日全员禁言挂上去啦：" if success else "猫猫去执行今天这轮每日全员禁言时出了点问题喵："
    await bot.send_group_msg(
        group_id=group_id,
        message=build_prefixed_message(title, [Message(f"{detail} {next_text}")]),
    )


async def execute_whole_unmute(
    bot: Bot,
    group_id: int,
    *,
    task_id: Optional[str],
    announce: bool,
) -> Tuple[bool, str]:
    """执行全员解禁"""
    try:
        await bot.set_group_whole_ban(group_id=group_id, enable=False)
    except Exception as exception:
        return False, f"解除全员禁言失败了喵：{exception}"

    set_whole_mute_state(group_id, False, None, None)
    if task_id:
        remove_task_record(group_id, task_id)

    if announce:
        await bot.send_group_msg(
            group_id=group_id,
            message="猫猫已经把全员禁言解除啦，大家现在都能说话了喵~",
        )

    return True, "全员禁言已解除喵~"


async def cancel_user_current_mute(
    bot: Bot,
    group_id: int,
    user_id: int,
    *,
    report_future_state: bool = True,
) -> Tuple[bool, str]:
    """只取消当前正在生效的个人禁言"""
    state = init_group_state(group_id)
    mute_state = state["individual_mutes"].get(user_id)
    if mute_state is None:
        return False, "当前没有正在生效的禁言喵~"

    next_task_time: Optional[datetime] = None
    if report_future_state:
        future_tasks = sorted(
            (
                task.get("execute_time")
                for task in state["tasks"].values()
                if task.get("user_id") == user_id
                and task.get("type") in USER_TASK_TYPES
                and task.get("execute_time") is not None
                and task["execute_time"] > datetime.now(BEIJING_TZ)
            ),
        )
        if future_tasks:
            next_task_time = future_tasks[0]

    try:
        await bot.set_group_ban(group_id=group_id, user_id=user_id, duration=0)
    except Exception as exception:
        return False, classify_ban_exception(user_id, exception)

    plan_id = mute_state.get("plan_id")
    remove_user_mute_state(group_id, user_id)
    if plan_id:
        plan = state["plans"].get(plan_id)
        if plan and plan.get("next_execute_time") is None:
            remove_long_plan(group_id, plan_id)

    if next_task_time is not None:
        return (
            True,
            "当前禁言已经解除啦喵~"
            f"不过未来任务还保留着，会在 {format_datetime_display(next_task_time)} 再次生效喵~",
        )
    return True, "当前禁言已经解除啦喵~"


def cancel_user_future_mute(group_id: int, user_id: int) -> Tuple[bool, str]:
    """只取消未来禁言任务与每日任务"""
    state = init_group_state(group_id)
    mute_state = state["individual_mutes"].get(user_id)
    has_current_mute = bool(
        mute_state
        and mute_state.get("end_time") is not None
        and mute_state["end_time"] > datetime.now(BEIJING_TZ)
    )
    one_time_task_count = sum(
        1
        for task in state["tasks"].values()
        if task.get("user_id") == user_id and task.get("type") in {"mute_start", "mute_refresh"}
    )
    daily_task_count = sum(
        1
        for task in state["tasks"].values()
        if task.get("user_id") == user_id and task.get("type") == "daily_user_mute"
    )
    plan_count = sum(1 for plan in state["plans"].values() if plan.get("user_id") == user_id)
    task_count, plan_count = clear_user_scheduled_state(group_id, user_id)
    if task_count == 0 and plan_count == 0:
        return False, "未来没有挂着的定时禁言或长期计划喵~"

    parts: List[str] = []
    if one_time_task_count:
        parts.append(f"取消了 {one_time_task_count} 条一次性未来任务")
    if daily_task_count:
        parts.append(f"取消了 {daily_task_count} 条每日任务")
    if plan_count:
        parts.append(f"移除了 {plan_count} 个长期计划")
    if has_current_mute:
        parts.append("当前正在生效的禁言保持不变")
    return True, "，".join(parts) + " 喵~"


async def cancel_user_all_mute(
    bot: Bot,
    group_id: int,
    user_id: int,
) -> Tuple[bool, str]:
    """同时取消当前禁言与未来禁言任务"""
    current_success, current_message = await cancel_user_current_mute(
        bot,
        group_id,
        user_id,
        report_future_state=False,
    )
    future_success, future_message = cancel_user_future_mute(group_id, user_id)

    if not current_success and not future_success:
        return False, "当前没有禁言，未来也没有计划要取消喵~"

    parts: List[str] = []
    if current_success:
        parts.append(current_message)
    if future_success:
        parts.append(future_message)
    return True, "；".join(parts)


def collect_group_user_cancel_targets(
    group_id: int,
    cancel_scope: str,
) -> List[int]:
    """收集群内需要批量处理的成员禁言目标"""
    state = init_group_state(group_id)
    now = datetime.now(BEIJING_TZ)

    current_user_ids = {
        user_id
        for user_id, info in state["individual_mutes"].items()
        if info.get("end_time") and info["end_time"] > now
    }
    future_user_ids = {
        int(task["user_id"])
        for task in state["tasks"].values()
        if task.get("user_id") is not None and task.get("type") in USER_TASK_TYPES
    }
    future_user_ids.update(
        int(plan["user_id"])
        for plan in state["plans"].values()
        if plan.get("user_id") is not None
    )

    if cancel_scope == "current":
        return sorted(current_user_ids)
    if cancel_scope == "scheduled":
        return sorted(future_user_ids)
    return sorted(current_user_ids | future_user_ids)


async def cancel_all_users_current_mute(
    bot: Bot,
    group_id: int,
) -> Tuple[bool, List[Message]]:
    """批量取消所有成员当前禁言"""
    target_user_ids = collect_group_user_cancel_targets(group_id, "current")
    if not target_user_ids:
        return False, [Message("当前没有任何成员的个人禁言可解除喵~")]

    future_user_ids = set(collect_group_user_cancel_targets(group_id, "scheduled"))
    success_count = 0
    failed: List[Tuple[int, str]] = []

    for user_id in target_user_ids:
        success, message = await cancel_user_current_mute(
            bot,
            group_id,
            user_id,
            report_future_state=False,
        )
        if success:
            success_count += 1
        else:
            failed.append((user_id, message))

    lines: List[Message] = []
    if success_count:
        lines.append(Message(f"已解除 {success_count} 名成员当前生效中的个人禁言喵~"))
    preserved_future_count = len(set(target_user_ids) & future_user_ids)
    if preserved_future_count:
        lines.append(Message(f"其中 {preserved_future_count} 名成员的个人未来任务保持不变喵~"))
    for user_id, message in failed[:STATUS_PAGE_SIZE]:
        lines.append(build_user_line(user_id, message))
    if len(failed) > STATUS_PAGE_SIZE:
        lines.append(Message(f"还有 {len(failed) - STATUS_PAGE_SIZE} 名成员处理失败，猫猫先不刷屏啦喵~"))
    if not lines:
        lines.append(Message("这次没有成功解除任何成员当前生效中的个人禁言喵~"))
    return success_count > 0, lines


def cancel_all_users_future_mute(group_id: int) -> Tuple[bool, List[Message]]:
    """批量取消所有成员未来禁言任务"""
    target_user_ids = collect_group_user_cancel_targets(group_id, "scheduled")
    if not target_user_ids:
        return False, [Message("未来没有任何成员的定时禁言、每日任务或长期计划喵~")]

    current_user_ids = set(collect_group_user_cancel_targets(group_id, "current"))
    success_count = 0
    failed: List[Tuple[int, str]] = []

    for user_id in target_user_ids:
        success, message = cancel_user_future_mute(group_id, user_id)
        if success:
            success_count += 1
        else:
            failed.append((user_id, message))

    lines: List[Message] = []
    if success_count:
        lines.append(Message(f"已清掉 {success_count} 名成员的个人未来禁言计划喵~"))
    unchanged_current_count = len(set(target_user_ids) & current_user_ids)
    if unchanged_current_count:
        lines.append(Message(f"其中 {unchanged_current_count} 名成员当前生效中的个人禁言保持不变喵~"))
    for user_id, message in failed[:STATUS_PAGE_SIZE]:
        lines.append(build_user_line(user_id, message))
    if len(failed) > STATUS_PAGE_SIZE:
        lines.append(Message(f"还有 {len(failed) - STATUS_PAGE_SIZE} 名成员处理失败，猫猫先不刷屏啦喵~"))
    if not lines:
        lines.append(Message("这次没有成功清掉任何成员的个人未来计划喵~"))
    return success_count > 0, lines


async def cancel_all_users_all_mute(
    bot: Bot,
    group_id: int,
) -> Tuple[bool, List[Message]]:
    """批量取消所有成员当前与未来禁言状态"""
    current_user_ids = set(collect_group_user_cancel_targets(group_id, "current"))
    future_user_ids = set(collect_group_user_cancel_targets(group_id, "scheduled"))
    target_user_ids = sorted(current_user_ids | future_user_ids)
    if not target_user_ids:
        return False, [Message("当前和未来都没有任何成员的个人禁言状态喵~")]

    success_count = 0
    failed: List[Tuple[int, str]] = []
    for user_id in target_user_ids:
        success, message = await cancel_user_all_mute(bot, group_id, user_id)
        if success:
            success_count += 1
        else:
            failed.append((user_id, message))

    lines: List[Message] = []
    if success_count:
        lines.append(Message(f"已整理 {success_count} 名成员的个人禁言状态喵~"))
        if current_user_ids:
            lines.append(Message(f"涉及当前个人禁言的成员有 {len(current_user_ids)} 名喵~"))
        if future_user_ids:
            lines.append(Message(f"涉及个人未来计划的成员有 {len(future_user_ids)} 名喵~"))
    for user_id, message in failed[:STATUS_PAGE_SIZE]:
        lines.append(build_user_line(user_id, message))
    if len(failed) > STATUS_PAGE_SIZE:
        lines.append(Message(f"还有 {len(failed) - STATUS_PAGE_SIZE} 名成员处理失败，猫猫先不刷屏啦喵~"))
    if not lines:
        lines.append(Message("这次没有成功整理任何成员的个人禁言状态喵~"))
    return success_count > 0, lines


async def cancel_whole_current(
    bot: Bot,
    group_id: int,
    *,
    report_future_state: bool = True,
) -> Tuple[bool, str]:
    """只解除当前全员禁言"""
    state = init_group_state(group_id)
    if not state["whole_mute"].get("enabled"):
        return False, "当前没有生效中的全员禁言喵~"

    next_task_time: Optional[datetime] = None
    if report_future_state:
        future_task_times = sorted(
            (
                task.get("execute_time")
                for task in state["tasks"].values()
                if task.get("type") in {"whole_mute_start", "daily_whole_mute"}
                and task.get("execute_time") is not None
                and task["execute_time"] > datetime.now(BEIJING_TZ)
            ),
        )
        if future_task_times:
            next_task_time = future_task_times[0]

    clear_active_whole_unmute_task(group_id)
    success, message = await execute_whole_unmute(bot, group_id, task_id=None, announce=False)
    if not success:
        return success, message
    if next_task_time is not None:
        return (
            True,
            "当前全员禁言已经解除啦喵~"
            f"不过未来计划还保留着，会在 {format_datetime_display(next_task_time)} 再次开启喵~",
        )
    return True, message


def cancel_whole_future(group_id: int) -> Tuple[bool, str]:
    """只取消未来全员禁言任务与每日任务"""
    state = init_group_state(group_id)
    has_current_whole = bool(state["whole_mute"].get("enabled"))
    one_time_count = sum(
        1 for task in state["tasks"].values() if task.get("type") == "whole_mute_start"
    )
    daily_count = sum(
        1 for task in state["tasks"].values() if task.get("type") == "daily_whole_mute"
    )
    count = clear_whole_scheduled_state(
        group_id,
        preserve_current_unmute=True,
        include_daily=True,
    )
    if count == 0:
        return False, "未来没有挂着的全员禁言任务喵~"

    parts: List[str] = []
    if one_time_count:
        parts.append(f"取消了 {one_time_count} 条一次性全员任务")
    if daily_count:
        parts.append(f"取消了 {daily_count} 条每日全员任务")
    if has_current_whole:
        parts.append("当前生效中的全员禁言保持不变")
    return True, "，".join(parts) + " 喵~"


async def cancel_whole_all(bot: Bot, group_id: int) -> Tuple[bool, str]:
    """同时取消当前和未来的全员禁言"""
    current_success, current_message = await cancel_whole_current(
        bot,
        group_id,
        report_future_state=False,
    )
    future_success, future_message = cancel_whole_future(group_id)

    if not current_success and not future_success:
        return False, "当前没有全员禁言，未来也没有相关任务喵~"

    parts: List[str] = []
    if current_success:
        parts.append(current_message)
    if future_success:
        parts.append(future_message)
    return True, "；".join(parts)


async def execute_self_mute(bot: Bot, group_id: int, user_id: int) -> None:
    """执行禁我"""
    if await is_group_admin(bot, group_id, user_id):
        await bot.send_group_msg(
            group_id=group_id,
            message="你是群管理喵，猫猫可不敢对你下手~",
        )
        return

    duration_minutes = random.choice(plugin_config.mute_self_options)
    if duration_minutes <= 0:
        await bot.send_group_msg(
            group_id=group_id,
            message="今天心情好，这次就先放过你喵~",
        )
        return

    success, message = await execute_direct_user_mute(
        bot,
        group_id,
        user_id,
        duration_minutes,
    )
    title = "猫猫满足你啦：" if success else "禁我失败了喵："
    await bot.send_group_msg(
        group_id=group_id,
        message=build_prefixed_message(title, [build_user_line(user_id, message)]),
    )


def build_task_preview(task: Dict[str, Any]) -> Message:
    """构建定时任务预览消息"""
    execute_time = task.get("execute_time")
    if execute_time is None:
        return Message("• 有一条无效任务，猫猫稍后会清理掉喵~")

    if task.get("type") == "mute_start":
        user_id = task.get("user_id")
        if user_id is None:
            return Message("• 有一条缺少目标成员的定时禁言任务，猫猫稍后会清理掉喵~")
        return build_user_line(
            user_id,
            f"将在 {format_datetime_display(execute_time)} 开始定时禁言，"
            f"最终到 {format_datetime_display(task['end_time'])} 结束喵~",
        )
    if task.get("type") == "mute_refresh":
        user_id = task.get("user_id")
        if user_id is None:
            return Message("• 有一条缺少目标成员的长期续期任务，猫猫稍后会清理掉喵~")
        return build_user_line(
            user_id,
            f"将在 {format_datetime_display(execute_time)} 续上长期禁言，"
            f"最终到 {format_datetime_display(task['end_time'])} 结束喵~",
        )
    if task.get("type") == "whole_mute_start":
        if task.get("end_time"):
            return Message(
                f"• {format_datetime_display(execute_time)} 开始全员禁言，"
                f"到 {format_datetime_display(task['end_time'])} 结束喵~"
            )
        return Message(f"• {format_datetime_display(execute_time)} 开始全员禁言，不单独设置结束时间喵~")
    return Message(f"• {format_datetime_display(execute_time)} 自动解除全员禁言喵~")


def build_daily_task_preview(task: Dict[str, Any]) -> Message:
    """构建每日任务预览消息"""
    execute_time = task.get("execute_time")
    start_minutes = task.get("start_minutes")
    duration = task.get("duration")
    if execute_time is None or start_minutes is None or duration is None:
        return Message("• 有一条每日任务数据不完整，猫猫稍后会清理掉喵~")

    window_text = format_daily_task_window(start_minutes, duration)
    if task.get("type") == "daily_user_mute":
        user_id = task.get("user_id")
        if user_id is None:
            return Message("• 有一条缺少目标成员的每日禁言任务，猫猫稍后会清理掉喵~")
        return build_user_line(
            user_id,
            f"{window_text}，下一轮会在 {format_datetime_display(execute_time)} 开始喵~",
        )

    return Message(f"• {window_text}，下一轮会在 {format_datetime_display(execute_time)} 开始喵~")


def build_help_message(group_id: int) -> Message:
    """构建简要帮助"""
    at_text = "需要先 @ 猫猫" if get_need_at(group_id) else "可以直接发命令"
    lines = [
        Message(f"当前触发方式：{at_text}"),
        Message("猫猫现在能识别比较自然的说法啦，你可以直接描述你想做什么"),
        Message("问句、闲聊和容易误伤正常聊天的说法，猫猫会尽量避开，不会乱执行喵~"),
        Message("常见例子："),
        Message("• 禁言 @某人 10分钟"),
        Message("• 5分钟后禁言 @某人 到9点"),
        Message("• 今晚八点禁言 @某人 到明早八点半"),
        Message("• 下周一上午九点禁言 @某人 2天"),
        Message("• 每天10点禁言 @某人 10分钟 / 每天10点全员禁言"),
        Message("• 取消定时禁言 @某人"),
        Message("• 解除所有人的禁言 / 解除所有人的定时禁言"),
        Message("• 取消所有禁言 @某人"),
        Message("• 全员禁言 2小时 / 解禁全员"),
        Message("• 查看状态 / 展开当前禁言 / 展开定时任务 / 展开每日任务 / 展开长期禁言"),
        Message("想看更完整的细则，请发送“使用细则”喵~"),
    ]
    return build_prefixed_message("猫猫来教你用新版禁言系统啦：", lines)


def build_usage_message() -> Message:
    """构建详细使用细则"""
    lines = [
        Message("一、基础动作"),
        Message("• 禁言：禁言 @某人 10分钟 / 明晚八点禁言 @某人 到下周一上午九点"),
        Message("• 取消当前禁言：取消 @某人 / 解禁 @某人 / 解除 @某人"),
        Message("• 取消未来计划：取消定时禁言 @某人 / 取消 @某人 的定时任务"),
        Message("• 全部取消：取消所有禁言 @某人 / 取消 @某人 的所有禁言状态"),
        Message("• 批量处理成员禁言：解除所有人的禁言 / 解除所有人的定时禁言 / 解除所有人的所有禁言"),
        Message("• 全员禁言：全员禁言 30分钟 / 始终禁言 10分钟 / 禁言 @全体成员 2小时"),
        Message("• 每日禁言：每天10点禁言 @某人 10分钟 / 禁言 @某人 每天10点 / 每天10点全员禁言"),
        Message("二、时间写法"),
        Message("• 时长支持：秒、分、分钟、小时、天、月、s、m、h、d、day、days、mon、month、months"),
        Message("• 其中 m 始终表示分钟，月份请写月 / mon / month / months"),
        Message("• 月按 30 天计算，最多支持 12 个月"),
        Message("• 时间支持：14:30、今晚八点、明早八点半、下周一上午九点"),
        Message("• 纯数字时间按 24 小时理解：8点是 08:00，20点是 20:00；晚上8点这类写法按带前缀的 12 小时习惯理解"),
        Message("• 也支持多久后开始：5分钟后禁言 @某人 / 2小时后禁言 @某人 到明早八点"),
        Message("• 时间区间支持：14:30 到 15:30 / 今晚八点到明早八点半"),
        Message("• 只写结束时间也行：禁言 @某人 到明早八点"),
        Message("• 只写开始时间也行：下周一上午九点禁言 @某人，没写时长时会按默认时长处理"),
        Message("• 同一成员可以挂多条不冲突的定时任务；冲突任务会自动合并"),
        Message("• 每日禁言支持写时长或结束时刻，比如每天10点禁言 @某人 10分钟 / 每天10点禁言 @某人 到11点"),
        Message("三、歧义处理"),
        Message("• 猫猫会尽量理解自然语言，但像“要不要禁言 @某人”这种问句不会执行"),
        Message("• 同时 @ 全体成员和普通成员会被视为歧义，猫猫会拒绝执行"),
        Message("四、状态查看"),
        Message("• 查看状态：看概要，默认每类先展示 5 条"),
        Message("• 展开当前禁言 / 展开定时任务 / 展开每日任务 / 展开长期禁言 / 展开全部状态"),
        Message("• 翻页写法：展开当前禁言第2页 / 展开定时任务第3页 / 展开每日任务第2页"),
    ]
    return build_prefixed_message("猫猫把使用细则整理好啦：", lines)


def build_status_summary(group_id: int) -> Message:
    """构建状态摘要"""
    state = init_group_state(group_id)
    now = datetime.now(BEIJING_TZ)

    current_users = [
        (user_id, info)
        for user_id, info in state["individual_mutes"].items()
        if info.get("end_time") and info["end_time"] > now
    ]
    current_users.sort(key=lambda item: item[1]["end_time"])

    scheduled_tasks = [
        (task_id, task)
        for task_id, task in state["tasks"].items()
        if task.get("type") not in DAILY_TASK_TYPES
        and task.get("execute_time")
        and task["execute_time"] > now
    ]
    scheduled_tasks.sort(key=lambda item: item[1]["execute_time"])

    daily_tasks = [
        (task_id, task)
        for task_id, task in state["tasks"].items()
        if task.get("type") in DAILY_TASK_TYPES and task.get("execute_time") is not None
    ]
    daily_tasks.sort(key=lambda item: item[1]["execute_time"])

    long_plans = [
        (plan_id, plan)
        for plan_id, plan in state["plans"].items()
        if plan.get("end_time") and plan["end_time"] > now
    ]
    long_plans.sort(key=lambda item: item[1]["end_time"])

    lines: List[Message] = []
    trigger_mode = "需要先 @ 猫猫" if get_need_at(group_id) else "可以直接发命令"
    lines.append(Message(f"触发方式：{trigger_mode}"))

    whole_mute = state["whole_mute"]
    if whole_mute.get("enabled"):
        if whole_mute.get("end_time"):
            lines.append(
                Message(
                    "全员禁言：进行中，"
                    f"还剩 {format_remaining_time(whole_mute['end_time'], now)}，"
                    f"预计到 {format_datetime_display(whole_mute['end_time'])} 结束喵~"
                )
            )
        else:
            lines.append(Message("全员禁言：进行中，当前是未写时长的持续模式喵~"))
    else:
        lines.append(Message("全员禁言：当前没有开启喵~"))

    current_preview, _ = paginate_items(current_users, 1, STATUS_PAGE_SIZE)
    lines.append(Message(f"当前禁言：{len(current_users)} 人"))
    if current_preview:
        for user_id, info in current_preview:
            lines.append(
                build_user_line(
                    user_id,
                    f"还剩 {format_remaining_time(info['end_time'], now)}，到 {format_datetime_display(info['end_time'])} 结束喵~",
                )
            )
        if len(current_users) > STATUS_PAGE_SIZE:
            lines.append(Message("想看完整列表的话，发送“展开当前禁言”喵~"))
    else:
        lines.append(Message("• 当前没有人被禁言喵~"))

    scheduled_preview, _ = paginate_items(scheduled_tasks, 1, STATUS_PAGE_SIZE)
    lines.append(Message(f"定时任务：{len(scheduled_tasks)} 条"))
    if scheduled_preview:
        for _, task in scheduled_preview:
            lines.append(build_task_preview(task))
        if len(scheduled_tasks) > STATUS_PAGE_SIZE:
            lines.append(Message("想看完整任务的话，发送“展开定时任务”喵~"))
    else:
        lines.append(Message("• 当前没有未来定时任务喵~"))

    daily_preview, _ = paginate_items(daily_tasks, 1, STATUS_PAGE_SIZE)
    lines.append(Message(f"每日任务：{len(daily_tasks)} 条"))
    if daily_preview:
        for _, task in daily_preview:
            lines.append(build_daily_task_preview(task))
        if len(daily_tasks) > STATUS_PAGE_SIZE:
            lines.append(Message("想看完整每日任务的话，发送“展开每日任务”喵~"))
    else:
        lines.append(Message("• 当前没有每日禁言任务喵~"))

    plan_preview, _ = paginate_items(long_plans, 1, STATUS_PAGE_SIZE)
    lines.append(Message(f"长期禁言计划：{len(long_plans)} 条"))
    if plan_preview:
        for _, plan in plan_preview:
            lines.append(
                build_user_line(
                    plan["user_id"],
                    f"最终到 {format_datetime_display(plan['end_time'])} 结束，"
                    + (
                        f"下一次续期在 {format_datetime_display(plan['next_execute_time'])} 喵~"
                        if plan.get("next_execute_time")
                        else "当前已经进入最后一段喵~"
                    ),
                )
            )
        if len(long_plans) > STATUS_PAGE_SIZE:
            lines.append(Message("想看完整长期计划的话，发送“展开长期禁言”喵~"))
    else:
        lines.append(Message("• 当前没有长期禁言计划喵~"))

    lines.append(Message("如果想一次看全量信息，也可以发送“展开全部状态”喵~"))
    return build_prefixed_message("猫猫把当前状态整理好啦：", lines)


def build_status_detail(group_id: int, section: str, page: int) -> Message:
    """构建详细状态页"""
    state = init_group_state(group_id)
    now = datetime.now(BEIJING_TZ)
    lines: List[Message] = []

    if section in {"current", "all"}:
        current_users = [
            (user_id, info)
            for user_id, info in state["individual_mutes"].items()
            if info.get("end_time") and info["end_time"] > now
        ]
        current_users.sort(key=lambda item: item[1]["end_time"])
        page_items, total_pages = paginate_items(current_users, page, STATUS_PAGE_SIZE)
        lines.append(Message(f"【当前禁言】第 {min(page, total_pages)}/{total_pages} 页，共 {len(current_users)} 人"))
        if page_items:
            for user_id, info in page_items:
                lines.append(
                    build_user_line(
                        user_id,
                        f"结束时间：{format_datetime_display(info['end_time'])}，剩余：{format_remaining_time(info['end_time'], now)}",
                    )
                )
        else:
            lines.append(Message("• 这里现在是空的喵~"))

    if section in {"scheduled", "all"}:
        scheduled_tasks = [
            (task_id, task)
            for task_id, task in state["tasks"].items()
            if task.get("type") not in DAILY_TASK_TYPES
            and task.get("execute_time")
            and task["execute_time"] > now
        ]
        scheduled_tasks.sort(key=lambda item: item[1]["execute_time"])
        page_items, total_pages = paginate_items(scheduled_tasks, page, STATUS_PAGE_SIZE)
        lines.append(Message(f"【定时任务】第 {min(page, total_pages)}/{total_pages} 页，共 {len(scheduled_tasks)} 条"))
        if page_items:
            for _, task in page_items:
                lines.append(build_task_preview(task))
        else:
            lines.append(Message("• 这里现在是空的喵~"))

    if section in {"daily", "all"}:
        daily_tasks = [
            (task_id, task)
            for task_id, task in state["tasks"].items()
            if task.get("type") in DAILY_TASK_TYPES and task.get("execute_time") is not None
        ]
        daily_tasks.sort(key=lambda item: item[1]["execute_time"])
        page_items, total_pages = paginate_items(daily_tasks, page, STATUS_PAGE_SIZE)
        lines.append(Message(f"【每日任务】第 {min(page, total_pages)}/{total_pages} 页，共 {len(daily_tasks)} 条"))
        if page_items:
            for _, task in page_items:
                lines.append(build_daily_task_preview(task))
        else:
            lines.append(Message("• 这里现在是空的喵~"))

    if section in {"long", "all"}:
        plans = [
            (plan_id, plan)
            for plan_id, plan in state["plans"].items()
            if plan.get("end_time") and plan["end_time"] > now
        ]
        plans.sort(key=lambda item: item[1]["end_time"])
        page_items, total_pages = paginate_items(plans, page, STATUS_PAGE_SIZE)
        lines.append(Message(f"【长期禁言】第 {min(page, total_pages)}/{total_pages} 页，共 {len(plans)} 条"))
        if page_items:
            for _, plan in page_items:
                lines.append(
                    build_user_line(
                        plan["user_id"],
                        f"最终结束：{format_datetime_display(plan['end_time'])}，"
                        + (
                            f"下一次续期：{format_datetime_display(plan['next_execute_time'])}"
                            if plan.get("next_execute_time")
                            else "当前已进入最后一段"
                        ),
                    )
                )
        else:
            lines.append(Message("• 这里现在是空的喵~"))

    lines.append(Message("如果想翻页，可以发送“展开当前禁言第2页”或“展开每日任务第2页”这类命令喵~"))
    return build_prefixed_message("猫猫把详细状态展开给你看啦：", lines)


async def handle_cancel_command(bot: Bot, group_id: int, command: ParsedCommand) -> None:
    """处理取消类命令"""
    lines: List[Message] = []
    if command.target_scope == "all_users":
        if command.cancel_scope == "current":
            success, lines = await cancel_all_users_current_mute(bot, group_id)
        elif command.cancel_scope == "scheduled":
            success, lines = cancel_all_users_future_mute(group_id)
        else:
            success, lines = await cancel_all_users_all_mute(bot, group_id)

        title = {
            "current": "猫猫已经把所有成员当前的个人禁言整理好啦：",
            "scheduled": "猫猫已经把所有成员的个人未来计划整理好啦：",
            "all": "猫猫已经把所有成员的个人禁言状态一起整理好啦：",
        }[command.cancel_scope]
        if not success:
            title = "猫猫这次没找到能处理的成员个人禁言状态喵："
        await bot.send_group_msg(group_id=group_id, message=build_prefixed_message(title, lines))
        return

    if command.target_scope == "whole":
        if command.cancel_scope == "current":
            success, message = await cancel_whole_current(bot, group_id)
        elif command.cancel_scope == "scheduled":
            success, message = cancel_whole_future(group_id)
        else:
            success, message = await cancel_whole_all(bot, group_id)

        title = "猫猫已经处理全员禁言啦：" if success else "猫猫这次没找到能取消的全员状态喵："
        lines.append(Message(message))
        await bot.send_group_msg(group_id=group_id, message=build_prefixed_message(title, lines))
        return

    for user_id in command.user_ids:
        if command.cancel_scope == "current":
            success, message = await cancel_user_current_mute(bot, group_id, user_id)
        elif command.cancel_scope == "scheduled":
            success, message = cancel_user_future_mute(group_id, user_id)
        else:
            success, message = await cancel_user_all_mute(bot, group_id, user_id)
        del success
        lines.append(build_user_line(user_id, message))

    title = {
        "current": "猫猫已经去处理当前禁言啦：",
        "scheduled": "猫猫已经去处理未来计划啦：",
        "all": "猫猫已经把相关禁言状态一起整理啦：",
    }[command.cancel_scope]
    await bot.send_group_msg(group_id=group_id, message=build_prefixed_message(title, lines))


async def handle_mute_command(bot: Bot, group_id: int, command: ParsedCommand) -> None:
    """处理禁言类命令"""
    now = datetime.now(BEIJING_TZ)
    duration_minutes = ensure_duration_minutes(command.duration_minutes)
    if command.repeat_kind == "daily" and command.daily_start_minutes is not None:
        if command.target_scope == "whole":
            execute_time, merged_start, merged_duration, merged_task_count = (
                create_or_merge_daily_whole_mute_task(
                    group_id,
                    str(bot.self_id),
                    command.daily_start_minutes,
                    duration_minutes,
                )
            )
            lines = [
                Message(format_daily_task_window(merged_start, merged_duration) + "喵~"),
                Message(f"下一轮会在 {format_datetime_display(execute_time)} 开始喵~"),
            ]
            if merged_task_count:
                lines.append(Message(f"另外还顺手合并了 {merged_task_count} 条冲突的每日全员任务喵~"))
            await bot.send_group_msg(
                group_id=group_id,
                message=build_prefixed_message("猫猫已经把每日全员禁言记进作息表啦：", lines),
            )
            return

        lines: List[Message] = []
        for user_id in command.user_ids:
            execute_time, merged_start, merged_duration, merged_task_count = (
                create_or_merge_daily_user_mute_task(
                    group_id,
                    str(bot.self_id),
                    user_id,
                    command.daily_start_minutes,
                    duration_minutes,
                )
            )
            detail_parts = [
                format_daily_task_window(merged_start, merged_duration),
                f"下一轮会在 {format_datetime_display(execute_time)} 开始",
            ]
            if merged_task_count:
                detail_parts.append(f"已和 {merged_task_count} 条冲突的每日任务合并")
            lines.append(build_user_line(user_id, "，".join(detail_parts) + "喵~"))

        await bot.send_group_msg(
            group_id=group_id,
            message=build_prefixed_message("猫猫已经把每日禁言记进作息表啦：", lines),
        )
        return

    if command.start_time and command.start_time > now:
        if command.target_scope == "whole":
            clear_whole_scheduled_state(group_id, preserve_current_unmute=True)
            end_time = command.end_time
            if end_time is None and command.duration_minutes is not None:
                end_time = command.start_time + timedelta(minutes=duration_minutes)
            task_id = create_task_record(
                group_id,
                "whole_mute_start",
                str(bot.self_id),
                command.start_time,
                end_time=end_time,
                duration=duration_minutes if command.duration_minutes is not None else None,
            )
            schedule_task_job(group_id, task_id, command.start_time)
            lines = [Message(f"开始时间：{format_datetime_display(command.start_time)}")]
            if end_time is not None:
                lines.append(Message(f"结束时间：{format_datetime_display(end_time)}，持续 {format_duration_display(duration_minutes)}"))
            else:
                lines.append(Message("结束时间：未单独设置，届时会一直保持喵~"))
            await bot.send_group_msg(group_id=group_id, message=build_prefixed_message("猫猫已经记下全员禁言计划啦：", lines))
            return

        lines: List[Message] = []
        for user_id in command.user_ids:
            planned_end_time = command.end_time or (
                command.start_time + timedelta(minutes=duration_minutes)
            )
            current_final_end = get_user_current_final_end(group_id, user_id, now=now)

            if current_final_end and current_final_end > command.start_time:
                (
                    success,
                    error_message,
                    _segment_end_time,
                    merged_final_end,
                    merged_task_count,
                    _current_extended,
                ) = await apply_merged_current_user_mute(
                    bot,
                    group_id,
                    user_id,
                    max(planned_end_time, current_final_end),
                )
                if not success:
                    lines.append(
                        build_user_line(user_id, error_message or "合并冲突任务时失败了喵~")
                    )
                    continue

                detail_parts = [
                    "这条定时任务和当前已经生效的禁言撞上了，猫猫已经直接并进当前禁言里啦喵~",
                    f"现在会一直持续到 {format_datetime_display(merged_final_end)}",
                ]
                if merged_task_count:
                    detail_parts.append(f"还顺手合并了 {merged_task_count} 条冲突的未来任务")
                lines.append(build_user_line(user_id, "，".join(detail_parts) + "喵~"))
                continue

            merged_start, merged_end, merged_task_count = create_or_merge_future_user_mute_task(
                group_id,
                str(bot.self_id),
                user_id,
                command.start_time,
                planned_end_time,
            )
            detail_parts = [
                f"开始时间：{format_datetime_display(merged_start)}",
                f"结束时间：{format_datetime_display(merged_end)}",
            ]
            if merged_task_count:
                detail_parts.append(f"已和 {merged_task_count} 条冲突定时任务合并")
            lines.append(build_user_line(user_id, "，".join(detail_parts) + "喵~"))
        await bot.send_group_msg(group_id=group_id, message=build_prefixed_message("猫猫已经把定时禁言记进小本本啦：", lines))
        return

    if command.target_scope == "whole":
        await execute_whole_mute(bot, group_id, command.duration_minutes, announce=True)
        return

    lines: List[Message] = []
    for user_id in command.user_ids:
        success, message = await execute_direct_user_mute(bot, group_id, user_id, duration_minutes)
        del success
        lines.append(build_user_line(user_id, message))
    await bot.send_group_msg(group_id=group_id, message=build_prefixed_message("猫猫已经去执行禁言啦：", lines))


@command_matcher.handle()
async def handle_command(bot: Bot, event: GroupMessageEvent, matcher: Matcher) -> None:
    """统一处理所有命令"""
    command = parse_event_command(bot, event)
    if command is None:
        return

    if command.kind == "invalid":
        await matcher.finish(command.error_message or "这句话有点歧义，猫猫不敢乱执行喵~")

    group_id = event.group_id
    user_id = str(event.get_user_id())

    if command.kind == "at_toggle":
        if not event.is_tome():
            await matcher.finish("设置 at 开关时要先 @ 猫猫一下喵~")
        if not await check_admin_permission(bot, group_id, user_id):
            await matcher.finish("只有管理员或超级用户才能改这个开关喵~")
        at_overrides[group_id] = bool(command.at_toggle_enabled)
        storage.save_at_overrides(at_overrides)
        if command.at_toggle_enabled:
            await matcher.finish("好啦，这个群以后需要先 @ 猫猫才会执行命令喵~")
        await matcher.finish("记住啦，这个群现在可以直接发命令，不用先 @ 猫猫喵~")

    if command.kind == "help":
        await matcher.finish(build_help_message(group_id))
    if command.kind == "usage":
        await matcher.finish(build_usage_message())
    if command.kind == "status":
        await matcher.finish(build_status_summary(group_id))
    if command.kind == "status_detail":
        await matcher.finish(build_status_detail(group_id, command.detail_section or "all", command.page))
    if command.kind == "self_mute":
        await execute_self_mute(bot, group_id, int(user_id))
        return

    if not await check_admin_permission(bot, group_id, user_id):
        await matcher.finish("这个命令只有群管理或超级用户能用喵~")

    if command.kind == "cancel":
        await handle_cancel_command(bot, group_id, command)
        return

    if command.kind == "mute":
        await handle_mute_command(bot, group_id, command)
        return
