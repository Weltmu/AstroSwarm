"""早晚午安定时问候模块（魔改新增，beta）

- 仅群聊发送，内容由 AI 按人设生成
- 群号、时间均由超级用户在 QQ 端通过指令配置（可固定时间或范围随机时间）
"""
import asyncio
import json
import random
from datetime import datetime, time as dtime
from typing import Dict, Optional

import nonebot_plugin_localstore as store
from nonebot import on_command, get_bot, logger, require
from nonebot.adapters.onebot.v11 import MessageEvent, Message
from nonebot.params import CommandArg
from nonebot.rule import to_me

require("nonebot_plugin_apscheduler")
from nonebot_plugin_apscheduler import scheduler  # noqa: E402

from .chat import get_short_ai_text
from .commands import check_super_user

__all__ = []

CONFIG_FILE = store.get_plugin_config_file("greeting_config.json")

GREETING_TYPES = {
    "morning": "早安",
    "noon": "午安",
    "evening": "晚安",
}

TYPE_KEYS = {
    "早安": "morning",
    "午安": "noon",
    "晚安": "evening",
}

DEFAULT_TIMES = {
    "morning": {"start": "07:00", "end": "08:30"},
    "noon": {"start": "11:30", "end": "13:00"},
    "evening": {"start": "21:30", "end": "23:00"},
}

JOB_PREFIX = "aichat_greet_"


def _load_config() -> Dict:
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except Exception as e:
            logger.error(f"加载问候配置失败: {e}")
    return {"groups": [], "times": DEFAULT_TIMES, "enabled": True}


def _save_config(data: Dict) -> None:
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _parse_hhmm(text: str) -> Optional[dtime]:
    try:
        h, m = text.strip().split(":")
        return dtime(int(h), int(m))
    except Exception:
        return None


def _reschedule() -> None:
    """根据配置重建所有问候定时任务"""
    try:
        for job in list(scheduler.get_jobs()):
            if job.id.startswith(JOB_PREFIX):
                scheduler.remove_job(job.id)
        data = _load_config()
        if not data.get("enabled", True):
            return
        groups = data.get("groups", [])
        times = data.get("times", DEFAULT_TIMES)
        for gid in groups:
            for key in GREETING_TYPES:
                t = times.get(key, DEFAULT_TIMES[key])
                start = _parse_hhmm(t.get("start", DEFAULT_TIMES[key]["start"])) or dtime(7, 0)
                end = _parse_hhmm(t.get("end", DEFAULT_TIMES[key]["end"])) or dtime(8, 30)
                if end <= start:
                    end = start
                scheduler.add_job(
                    _greet_job,
                    trigger="cron",
                    hour=start.hour,
                    minute=start.minute,
                    args=[gid, key, start.strftime("%H:%M"), end.strftime("%H:%M")],
                    id=f"{JOB_PREFIX}{key}_{gid}",
                    misfire_grace_time=3600,
                    coalesce=True,
                )
        logger.info(f"问候定时任务已重建: {len(groups) * len(GREETING_TYPES)} 个")
    except Exception as e:
        logger.error(f"重建问候定时任务失败: {e}")


async def _greet_job(gid: str, key: str, start_str: str, end_str: str) -> None:
    """窗口开始触发，随机延迟到窗口内某个时间后发送 AI 问候"""
    try:
        start = _parse_hhmm(start_str)
        end = _parse_hhmm(end_str)
        if start and end:
            max_delay = (end.hour * 3600 + end.minute * 60) - (start.hour * 3600 + start.minute * 60)
            if max_delay > 0:
                await asyncio.sleep(random.randint(0, max_delay))
        text = await _generate_greeting(key)
        if not text:
            return
        bot = get_bot()
        await bot.send_group_msg(group_id=int(gid), message=text)
        logger.info(f"已发送{GREETING_TYPES[key]}问候到群 {gid}: {text[:40]}")
    except Exception as e:
        logger.error(f"问候任务失败（群 {gid} {key}）: {e}")


async def _generate_greeting(key: str) -> str:
    label = GREETING_TYPES[key]
    now = datetime.now().strftime("%H:%M")
    prompt = (
        f"现在是 {now}，到了发{label}问候的时候了。"
        f"请用一句符合你人设的话向群友们说{label}，俏皮自然，不超过30个字，"
        "不要用markdown，不要输出JSON，直接输出这句话。"
    )
    return await get_short_ai_text(prompt, max_tokens=200)


greeting_cmd = on_command("ac 问候", rule=to_me(), priority=10, block=True)


@greeting_cmd.handle()
async def handle_greeting(event: MessageEvent, args: Message = CommandArg()):
    if not await check_super_user(event):
        await greeting_cmd.finish("没有权限")
    parts = args.extract_plain_text().strip().split()
    if not parts:
        data = _load_config()
        status = "开启" if data.get("enabled", True) else "关闭"
        groups = data.get("groups", []) or ["（无）"]
        groups_text = ", ".join(groups)
        lines = ["问候配置："]
        lines.append(f"状态: {status}")
        lines.append(f"启用群: {groups_text}")
        for key, label in GREETING_TYPES.items():
            t = data.get("times", DEFAULT_TIMES).get(key, DEFAULT_TIMES[key])
            s = t.get("start", "")
            e = t.get("end", "")
            lines.append(f"{label}: {s} - {e}")
        await greeting_cmd.finish(chr(10).join(lines))
    action = parts[0]
    data = _load_config()
    if action == "开":
        data["enabled"] = True
        _save_config(data)
        _reschedule()
        await greeting_cmd.finish("问候功能已开启")
    elif action == "关":
        data["enabled"] = False
        _save_config(data)
        _reschedule()
        await greeting_cmd.finish("问候功能已关闭")
    elif action == "列表":
        groups = data.get("groups", []) or ["（无）"]
        await greeting_cmd.finish("启用问候的群：" + chr(10) + chr(10).join(groups))
    elif action in ("添加群", "加群"):
        ids = parts[1:]
        if not ids and getattr(event, "group_id", None):
            ids = [str(event.group_id)]
        if not ids:
            await greeting_cmd.finish("用法：ac 问候 添加群 <群号> [群号...]")
        groups = data.setdefault("groups", [])
        added = []
        for gid in ids:
            if gid not in groups:
                groups.append(gid)
                added.append(gid)
        _save_config(data)
        _reschedule()
        if added:
            added_text = ", ".join(added)
            await greeting_cmd.finish(f"已添加群: {added_text}")
        else:
            await greeting_cmd.finish("无新群")
    elif action in ("删除群", "删群"):
        ids = parts[1:]
        if not ids and getattr(event, "group_id", None):
            ids = [str(event.group_id)]
        if not ids:
            await greeting_cmd.finish("用法：ac 问候 删除群 <群号>")
        groups = data.setdefault("groups", [])
        removed = [gid for gid in ids if gid in groups]
        data["groups"] = [gid for gid in groups if gid not in ids]
        _save_config(data)
        _reschedule()
        if removed:
            removed_text = ", ".join(removed)
            await greeting_cmd.finish(f"已删除群: {removed_text}")
        else:
            await greeting_cmd.finish("无")
    elif action == "时间":
        if len(parts) < 3 or parts[1] not in TYPE_KEYS:
            await greeting_cmd.finish("用法：ac 问候 时间 <早安|午安|晚安> <HH:MM> [HH:MM]")
        key = TYPE_KEYS[parts[1]]
        t1 = _parse_hhmm(parts[2])
        if not t1:
            await greeting_cmd.finish("时间格式错误，示例：07:00")
        t2 = _parse_hhmm(parts[3]) if len(parts) > 3 else t1
        if not t2:
            await greeting_cmd.finish("结束时间格式错误，示例：08:30")
        times = data.setdefault("times", DEFAULT_TIMES)
        times[key] = {"start": parts[2], "end": parts[3] if len(parts) > 3 else parts[2]}
        _save_config(data)
        _reschedule()
        label = GREETING_TYPES[key]
        if len(parts) > 3:
            await greeting_cmd.finish(f"{label}时间已设置: {parts[2]} - {parts[3]}（范围内随机）")
        else:
            await greeting_cmd.finish(f"{label}时间已设置: {parts[2]}（固定时间）")
    else:
        await greeting_cmd.finish("子命令：开 / 关 / 列表 / 添加群 <群号> / 删除群 <群号> / 时间 <早安|午安|晚安> <HH:MM> [HH:MM]")


_reschedule()
