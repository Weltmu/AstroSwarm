"""
主动聊天模块（魔改新增）

功能：机器人会在随机（不定时）的时间间隔内，主动给配置好的目标用户发送
一条随机内容的消息，像朋友一样主动找用户聊天。

- 优先使用已配置的 AI 大模型生成一句自然的开场白（保持插件人设）
- AI 不可用或调用失败时，自动使用本地随机开场白池
- 同一用户有冷却时间，避免频繁打扰
- 支持设置免打扰时段（默认 00:00 - 08:00 不主动发消息）
"""

import asyncio
import random
from datetime import datetime
from typing import Dict, List, Optional

from nonebot import get_bots, get_driver, logger

from .manager import chat_manager

# 本模块只负责在导入时注册后台任务，不向外面导出任何名字
__all__ = []

# 本地随机开场白池（AI 不可用或调用失败时的备用内容，可自行增删）
DEFAULT_OPENERS = [
    "在吗？今天过得怎么样呀",
    "嘿，突然想找你聊聊天，不忙吧？",
    "今天有什么有趣的事发生吗？说来听听",
    "我刚刚想到一个好玩的话题，你要不要猜猜是什么",
    "最近有没有看什么好看的剧或者电影呀",
    "如果现在给你一张任意门门票，你最想去哪里",
    "今天天气好像不错，你那边呢",
    "我有点无聊，你来陪我聊两句呗",
    "你平时周末都做些什么呀",
    "假如明天是假期，你最想干什么",
    "你最近有没有遇到什么开心的小事",
    "我发现自己越来越喜欢跟你聊天了",
    "问你个问题：你觉得晚饭吃什么最幸福",
    "刚看到一条很有意思的新闻，你想听听吗",
    "好久没跟你聊了，最近在忙什么呀",
    "突然想问问你，今天午饭吃的什么呀",
    "如果给你一次重新选择的机会，你想改掉什么事",
    "你相信缘分吗，反正我现在信了",
    "工作学习累不累呀，记得多休息",
    "我刚刚听了一首超好听的歌，下次分享给你",
]

# 记录每个用户上次发送时间（做冷却用）和上次的开场白（避免重复）
_last_send_time: Dict[str, float] = {}
_last_opener: Dict[str, str] = {}
_seq_counters: Dict[str, int] = {}

# 后台任务句柄
_proactive_task: Optional[asyncio.Task] = None

# ===== 魔改新增：群聊搭话 =====
_last_interject_time: Dict[str, float] = {}
_interject_task: Optional[asyncio.Task] = None


def _qq_bot():
    """返回当前连接的 QQ 官方机器人（主动消息只能走官方通道）。"""
    try:
        from nonebot.adapters.qq import Bot as QQBot
        for bot in get_bots().values():
            if isinstance(bot, QQBot):
                return bot
    except Exception:  # noqa: BLE001
        return None
    return None


# ===== 微信（iLink）主动消息 =====
_WX_PROACTIVE_MAX_AGE = 1800      # 秒：用户最近说过话才主动发，超过就不发（token 会失效）
_WX_DIR_CACHE = None


def _wx_dir():
    """适配器约定的目录：<bot>/data/nonebot_adapter_ilink（机器人 cwd 就是 bot 目录）。"""
    global _WX_DIR_CACHE
    if _WX_DIR_CACHE is None:
        from pathlib import Path as _P

        _WX_DIR_CACHE = _P.cwd() / "data" / "nonebot_adapter_ilink"
    return _WX_DIR_CACHE


def _wx_tokens() -> dict:
    """微信用户 -> {context_token, ts}，由 ilink 适配器每收到一条消息就写。"""
    import json as _json

    try:
        data = _json.loads((_wx_dir() / "ilink_tokens.json").read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _wx_state() -> dict:
    import json as _json

    try:
        data = _json.loads((_wx_dir() / "ilink_state.json").read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _wx_available() -> bool:
    """微信通道可用 = 有登录 token + 至少有一个用户会话 token。"""
    st = _wx_state()
    return bool(st.get("token")) and bool(_wx_tokens())


def _wx_client():
    """构造一个独立的 IlinkClient（运行期在 NoneBot 进程里，直接 import 包是安全的）。"""
    mod = None
    for name in ("src.plugins.nonebot_adapter_ilink.client", "nonebot_adapter_ilink.client"):
        try:
            mod = __import__(name, fromlist=["IlinkClient"])
            break
        except Exception:  # noqa: BLE001
            mod = None
    if mod is None:
        return None
    st = _wx_state()
    c = mod.IlinkClient(
        base_url=st.get("baseurl") or "https://ilinkai.weixin.qq.com",
        state_file=str(_wx_dir() / "ilink_state.json"),
        bot_type="3",
    )
    c.token = st.get("token", "")
    c.bot_id = st.get("bot_id", "")
    c.user_id = st.get("user_id", "")
    return c


async def _send_proactive_wechat(user_id: str) -> None:
    """给微信用户发主动消息（必须带缓存的 context_token，且会话不能太旧）。"""
    import time as _t

    info = _wx_tokens().get(user_id) or {}
    token = str(info.get("context_token") or "")
    if not token:
        logger.info(f"微信主动消息跳过：没有 {user_id} 的会话 token（让他先跟机器人说一句话）")
        return
    age = _t.time() - float(info.get("ts") or 0)
    if age > _WX_PROACTIVE_MAX_AGE:
        logger.info(
            f"微信主动消息跳过：{user_id} 已经 {age / 60:.0f} 分钟没说话，会话 token 多半失效了")
        return
    client = _wx_client()
    if client is None:
        logger.error("微信主动消息失败：拿不到 IlinkClient")
        return
    try:
        segments = await _build_opener_messages(user_id)
        for i, seg in enumerate(segments):
            ok = await client.send_text(user_id, token, seg)
            logger.info(f"微信主动消息 -> {user_id}: {'成功' if ok else '失败'} | {seg[:40]}")
            if i < len(segments) - 1:
                await asyncio.sleep(random.uniform(1.5, 3.0))
        _last_send_time[user_id] = datetime.now().timestamp()
    finally:
        try:
            await client.close()
        except Exception:  # noqa: BLE001
            pass


# ===== 能力包参数（proactive 包 1.1.0 起）=====
_PACK_DEFAULTS = {"enabled": True, "outreach_chance": 0.5, "min_interval_h": 24, "reply_window_h": 24, "max_unanswered": 3, "greeting_chance": 0.3, "quiet_start": 23, "quiet_end": 8, "rate_per_hour": 20, "platforms": ["qq", "wechat"]}
_PACK_CFG_CACHE = {"at": 0.0, "cfg": None}


def _pack_dir():
    from pathlib import Path as _P

    # bot 的 cwd 就是 bot 目录，data_home 是它的上一级
    return _P.cwd().parent / "tool_packs" / "proactive"


def _pack_cfg() -> dict:
    """读能力包参数：config.json（用户改的）> behavior.json（包默认）> 代码默认。"""
    import time as _t

    now = _t.time()
    if _PACK_CFG_CACHE["cfg"] is not None and now - _PACK_CFG_CACHE["at"] < 30:
        return _PACK_CFG_CACHE["cfg"]
    cfg = dict(_PACK_DEFAULTS)
    d = _pack_dir()
    for name in ("behavior.json", "config.json"):      # 后者优先级更高
        try:
            raw = (d / name).read_text(encoding="utf-8")
            data = json.loads(raw)
            if isinstance(data, dict):
                # 允许 {"proactive": {...}} 或直接 {...}
                merged = data.get("proactive") if isinstance(data.get("proactive"), dict) else data
                for k, v in (merged or {}).items():
                    if k in cfg:
                        cfg[k] = v
        except Exception:  # noqa: BLE001
            pass
    _PACK_CFG_CACHE.update({"at": now, "cfg": cfg})
    return cfg


def _state_path():
    from pathlib import Path as _P

    try:
        return _pack_dir() / "state.json"
    except Exception:  # noqa: BLE001
        return _P.cwd().parent / "tool_packs" / "proactive" / "state.json"


def _state() -> dict:
    import json as _json

    try:
        return _json.loads(_state_path().read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001
        return {}


def _state_save(st: dict) -> None:
    import json as _json

    try:
        p = _state_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(_json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def _unanswered(user_id: str) -> int:
    """连着几条没回（用户在下一次说话后会清零）。"""
    st = _state()
    return int((st.get(user_id) or {}).get("unanswered") or 0)


def _note_sent(user_id: str, replied_since: bool) -> None:
    st = _state()
    rec = st.get(user_id) or {}
    rec["unanswered"] = 0 if replied_since else int(rec.get("unanswered") or 0) + 1
    rec["last_sent"] = datetime.now().timestamp()
    st[user_id] = rec
    _state_save(st)


def _sends_last_hour(user_id: str) -> int:
    st = _state()
    marks = (st.get(user_id) or {}).get("marks") or []
    now = datetime.now().timestamp()
    return len([m for m in marks if now - float(m) < 3600])


def _note_mark(user_id: str) -> None:
    st = _state()
    rec = st.get(user_id) or {}
    now = datetime.now().timestamp()
    marks = [m for m in (rec.get("marks") or []) if now - float(m) < 3600]
    marks.append(now)
    rec["marks"] = marks
    st[user_id] = rec
    _state_save(st)


def _in_quiet(cfg: dict) -> bool:
    import datetime as _dt

    try:
        h = _dt.datetime.now().hour
    except Exception:  # noqa: BLE001
        return False
    qs, qe = int(cfg.get("quiet_start", 23)), int(cfg.get("quiet_end", 8))
    if qs == qe:
        return False
    return (qs <= h or h < qe) if qs > qe else (qs <= h < qe)


def _next_seq(key: str) -> int:
    """QQ 官方主动消息要求 msg_seq 递增，按目标维护计数器。"""
    _seq_counters[key] = _seq_counters.get(key, 0) + 1
    return _seq_counters[key]


def _is_quiet_hour() -> bool:
    """判断当前时间是否处于免打扰时段（支持跨天，如 23-7）"""
    start, end = chat_manager.get_proactive_quiet_hours()
    hour = datetime.now().hour
    if start == end:
        return False
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


def _is_in_cooldown(user_id: str) -> bool:
    """检查某个用户是否还在冷却时间内（刚聊过）"""
    cooldown = chat_manager.get_proactive_cooldown()
    if cooldown <= 0:
        return False
    last_time = _last_send_time.get(user_id)
    if last_time is None:
        return False
    return (datetime.now().timestamp() - last_time) < cooldown * 60


def _pick_local_opener(user_id: str) -> str:
    """从本地开场白池随机挑一句，尽量不与上次重复"""
    pool = [opener for opener in DEFAULT_OPENERS if opener != _last_opener.get(user_id)]
    if not pool:
        pool = DEFAULT_OPENERS
    opener = random.choice(pool)
    _last_opener[user_id] = opener
    return opener


async def _build_opener_messages(user_id: str) -> List[str]:
    """
    生成主动聊天的开场白分段列表

    优先调用 AI 生成（保持人设），失败则用本地随机开场白。
    同时把这条主动消息写入该用户的上下文，这样用户回复时机器人
    能记得这次主动聊天。
    """
    try:
        from .chat import get_chat_reply
        from .context import add_message, get_context

        key = str(user_id)
        context = get_context(key)
        context = context + [
            {
                "role": "user",
                "content": (
                    "（系统提示：现在轮到你主动找用户聊天了。"
                    "请根据上面的聊天背景，像老朋友一样自然开口，主动开启一个新话题，"
                    "不要提这是系统提示）"
                ),
            }
        ]
        reply = await get_chat_reply(context, is_group=False)

        import json

        data = json.loads(reply)
        segments = [
            segment
            for segment in data.get("reply", [])
            if segment and segment.strip()
        ]
        if not segments:
            raise ValueError("AI 返回的回复为空")

        # 把 AI 回复写入该用户的上下文（保持和正常聊天一致的存储格式）
        add_message(key, "assistant", reply)
        return segments

    except Exception as e:
        logger.warning(f"AI 生成开场白失败，改用本地随机开场白: {e}")
        from .context import add_message

        text = _pick_local_opener(user_id)
        add_message(str(user_id), "assistant", text)
        return [text]


async def _send_proactive_message(bot, user_id: str) -> None:
    """给指定 openid 发送主动聊天消息（QQ 官方 send_to_c2c，分段发送）。"""
    segments = await _build_opener_messages(user_id)
    for i, segment in enumerate(segments):
        await bot.send_to_c2c(
            openid=user_id, message=segment, msg_seq=_next_seq(user_id))
        if i < len(segments) - 1:
            await asyncio.sleep(random.uniform(1.5, 3.0))

    _last_send_time[user_id] = datetime.now().timestamp()
    logger.info(f"已主动给用户 {user_id} 发送消息: {segments[0][:50]}")


async def _try_send_one() -> None:
    """尝试给一个随机目标用户发送一条主动消息（带开关/免打扰/冷却检查）"""
    if not chat_manager.is_proactive_enabled():
        return

    cfg = _pack_cfg()
    if not cfg.get("enabled", True):
        logger.info("主动聊天：能力包参数里 enabled=false，跳过")
        return

    bot = _qq_bot()
    wx_ok = False if bot is not None else _wx_available()
    if bot is None and not wx_ok:
        logger.info("主动聊天跳过：既没有 QQ 官方机器人，也没有可用的微信会话")
        return

    if _is_quiet_hour() or _in_quiet(cfg):
        logger.info("当前处于免打扰时段（本地 23:00-08:00 或能力包参数），跳过本轮主动聊天")
        return

    targets = chat_manager.get_proactive_targets()
    if not targets:
        logger.info("没有配置主动聊天目标用户，请先使用 ac proactive add <QQ号> 添加")
        return

    eligible = [target for target in targets if not _is_in_cooldown(target)]
    if not eligible:
        logger.info("所有目标用户都在冷却时间内，跳过本轮")
        return

    target = random.choice(eligible)
    if bot is not None and target.isdigit():
        logger.info(
            f"主动聊天目标 {target} 是 QQ 号；QQ 官方主动消息需要 openid，"
            "请先用该账号与机器人对话（程序会自动记录 openid）或直接填写 openid，本轮跳过")
        return
    # ---- 能力包参数：概率 / 最小间隔 / 互动窗口 / 未回上限 / 限速 ----
    import time as _time

    if random.random() > float(cfg.get("outreach_chance", 0.5)):
        logger.info("主动聊天：本轮概率未命中，跳过")
        return
    last_sent = float((_state().get(target) or {}).get("last_sent") or 0)
    need_gap = float(cfg.get("min_interval_h", 24)) * 3600
    if last_sent and _time.time() - last_sent < need_gap:
        logger.info(
            f"主动聊天：距上次只过了 {(_time.time() - last_sent) / 3600:.1f} 小时"
            f"（下限 {cfg.get('min_interval_h')} 小时），跳过")
        return
    rate = int(cfg.get("rate_per_hour", 20))
    if rate > 0 and _sends_last_hour(target) >= rate:
        logger.info(f"主动聊天：{target} 本小时已达上限 {rate} 条，跳过")
        return
    un = _unanswered(target)
    if un >= int(cfg.get("max_unanswered", 3)):
        logger.info(f"主动聊天：{target} 已连续 {un} 条没回（上限 {cfg.get('max_unanswered')}），跳过")
        return
    try:
        if bot is not None:
            await _send_proactive_message(bot, target)
        else:
            await _send_proactive_wechat(target)      # 走微信（iLink）通道
    except Exception as e:
        logger.error(f"主动发送消息给 {target} 失败: {e}")
        return
    # 用户上次说话的时间晚于我们上次发送 = 中间回过话 → 未回计数清零
    wx_ts = float((_wx_tokens().get(target) or {}).get("ts") or 0)
    replied_since = bool(wx_ts and wx_ts > last_sent)
    _note_sent(target, replied_since)
    _note_mark(target)


async def _proactive_loop() -> None:
    """主动聊天主循环：每次随机等待一段时间后发一条消息"""
    logger.info("主动聊天后台任务已启动（不定时随机找用户聊天）")
    while True:
        try:
            interval_min, interval_max = chat_manager.get_proactive_interval()
            interval_seconds = random.uniform(interval_min, interval_max) * 60
            await asyncio.sleep(interval_seconds)
            await _try_send_one()
        except asyncio.CancelledError:
            logger.info("主动聊天后台任务已停止")
            break
        except Exception as e:
            logger.error(f"主动聊天任务发生异常: {e}")
            await asyncio.sleep(60)


def _is_in_group_cooldown(group_id: str) -> bool:
    """检查某个群是否还在搭话冷却时间内"""
    cooldown = chat_manager.get_proactive_cooldown()
    if cooldown <= 0:
        return False
    last_time = _last_interject_time.get(group_id)
    if last_time is None:
        return False
    return (datetime.now().timestamp() - last_time) < cooldown * 60


async def _build_interject_content(group_id: str) -> str:
    """生成群聊搭话内容：随机选一种构思（读记录搭话 / 不读记录找话题）"""
    from .chat import get_interject_reply
    from .context import get_context

    mode = "history" if random.random() < 0.5 else "random"
    history = []
    try:
        if mode == "history":
            context = get_context(f"group_{group_id}")
            history = context[-chat_manager.get_interject_history_count():]
            if not history:
                mode = "random"
        text = await get_interject_reply(history, mode)
        return text
    except Exception as e:
        logger.warning(f"AI生成搭话内容失败，改用本地开场白: {e}")
        return _pick_local_opener(group_id)


async def _send_interject(bot, group_id: str) -> None:
    """向指定群发送搭话消息（QQ 官方 send_to_group，group_openid）。"""
    text = await _build_interject_content(group_id)
    await bot.send_to_group(
        group_openid=group_id, message=text, msg_seq=_next_seq(group_id))
    _last_interject_time[group_id] = datetime.now().timestamp()
    logger.info(f"已向群 {group_id} 搭话: {text[:50]}")


async def _try_interject_one() -> None:
    """按概率尝试向配置的群聊搭话"""
    if not chat_manager.is_interject_enabled():
        return

    bot = _qq_bot()
    if bot is None:
        logger.info("群聊搭话跳过：当前没有 QQ 官方机器人连接（iLink 不支持主动推送）")
        return

    if _is_quiet_hour():
        logger.info("当前处于免打扰时段，跳过群聊搭话")
        return

    groups = chat_manager.get_proactive_groups()
    if not groups:
        logger.info("没有配置搭话群聊，请设置 aichat_proactive_groups 或使用 ac proactive group add")
        return

    probability = chat_manager.get_interject_probability()
    for group_id in groups:
        if group_id.isdigit():
            logger.info(
                f"群聊搭话目标 {group_id} 是 QQ 群号；QQ 官方需要 group_openid，"
                "请先在群内 @ 机器人一次（程序会自动记录）或直接填写 openid，跳过")
            continue
        if _is_in_group_cooldown(group_id):
            continue
        if random.random() >= probability:
            continue
        try:
            await _send_interject(bot, group_id)
        except Exception as e:
            logger.error(f"向群 {group_id} 搭话失败: {e}")


async def _interject_loop() -> None:
    """群聊搭话主循环：随机间隔触发，按概率决定是否搭话"""
    logger.info("群聊搭话后台任务已启动（随机不定时，按概率触发）")
    while True:
        try:
            interval_min, interval_max = chat_manager.get_interject_interval()
            await asyncio.sleep(random.uniform(interval_min, interval_max) * 60)
            await _try_interject_one()
        except asyncio.CancelledError:
            logger.info("群聊搭话后台任务已停止")
            break
        except Exception as e:
            logger.error(f"群聊搭话任务发生异常: {e}")
            await asyncio.sleep(60)


@get_driver().on_startup
async def _start_proactive_task() -> None:
    """机器人启动时启动主动聊天后台任务"""
    global _proactive_task
    if _proactive_task is None or _proactive_task.done():
        _proactive_task = asyncio.create_task(_proactive_loop())

    global _interject_task
    if _interject_task is None or _interject_task.done():
        _interject_task = asyncio.create_task(_interject_loop())


@get_driver().on_shutdown
async def _stop_proactive_task() -> None:
    """机器人关闭时停止主动聊天后台任务"""
    global _proactive_task
    if _proactive_task:
        _proactive_task.cancel()
        try:
            await _proactive_task
        except (asyncio.CancelledError, Exception):
            pass
        _proactive_task = None

    global _interject_task
    if _interject_task:
        _interject_task.cancel()
        try:
            await _interject_task
        except (asyncio.CancelledError, Exception):
            pass
        _interject_task = None
