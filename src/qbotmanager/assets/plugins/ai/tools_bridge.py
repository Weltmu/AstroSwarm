# -*- coding: utf-8 -*-
"""AI 大脑 ↔ 工具运行时桥（2026-09-27 插件工坊地基）。

解决的两个短板（第三个"查重/版本/回滚"在 core/workshop 里）：
1. 工具执行以前只传权限集合 —— 禁言/撤回/提醒/记忆类工具实际是空操作；
   现在把当前通道、发送回调、记忆、提醒、数据、联网都接进 ToolContext。
2. 工具以前不按通道裁剪 —— 微信里也会看到 QQ 专属工具；现在
   runtime.schemas(platform) 按 manifest.adapters 裁剪，动作执行时再验一次。

工坊生成的插件跑在沙箱里（core/agent/sandbox.py），它们做事的唯一出口是
本文件的 ``do_action``：动作白名单 + 权限 + 通道能力三重校验，失败把回执
写回结果，模型据此如实告诉用户 —— 不允许"工具说成功、其实没做成"。
"""
import asyncio
import json
import re
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from nonebot import get_bots, logger

from qbotmanager.core.agent.tool import ToolContext
from qbotmanager.core.agent_profile import channel_capabilities

from . import memory as memory_store
from .identity import canonical as identity_canonical, resolve as identity_resolve

# ---- 权限：按通道给最小集合（旧调用方不传 platform 时 registry 不裁剪）----


def source_of(msg) -> str:
    platform = str(getattr(msg, "platform", "") or "")
    scene = str(getattr(msg, "scene", "") or "")
    if platform == "qq":
        return f"qq:{'group' if scene == 'group' else 'c2c'}"
    return f"{platform}:{scene or 'private'}"


def user_key_of(msg) -> str:
    platform = str(getattr(msg, "platform", "") or "")
    uid = str(getattr(msg, "user_id", "") or "")
    return f"{platform}:{uid}" if platform and uid else ""


def permissions_for(msg) -> set:
    """按通道能力表给权限：微信只有聊天/记忆/定时，群管理只在 QQ。"""
    caps = channel_capabilities(source_of(msg))
    perms = {"send_message", "memory", "network", "timer"}
    if "group_admin" in caps:
        perms.add("group_admin")
    if "image" in caps or "voice" in caps:
        perms.add("media")
    return perms


# ---- 提醒：落盘 + 后台循环投递（发消息由适配器负责）----

_loop_task = None
_seq = 0


def _reminder_file() -> Path:
    return Path.cwd() / "data" / "ai" / "aichat_reminders.json"


def _load_reminders() -> list:
    try:
        data = json.loads(_reminder_file().read_text(encoding="utf-8"))
        return list(data) if isinstance(data, list) else []
    except Exception:  # noqa: BLE001 —— 文件不存在/损坏都当空
        return []


def _save_reminders(items: list) -> None:
    path = _reminder_file()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(items, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        logger.error(f"[tools] 保存提醒失败: {exc}")


def _next_seq(key: str) -> int:
    global _seq
    _seq = (_seq + 1) % 100000
    return _seq


def add_reminder(minutes: int, text: str, target: str, ctx) -> str:
    """写一条提醒（tool 侧同步调用），返回提醒 id。"""
    minutes = max(1, min(int(minutes), 43200))
    rid = uuid.uuid4().hex[:12]
    item = {
        "id": rid,
        "due": time.time() + minutes * 60,
        "text": str(text or "").strip()[:500],
        "target": str(target or "")[:80],
        "platform": str(getattr(ctx, "platform", "") or ""),
        "scene": str(getattr(ctx, "scene", "") or ""),
        "room_id": str(getattr(ctx, "extra", {}).get("room_id")
                       or getattr(ctx, "group_id", "") or ""),
        "user_id": str(getattr(ctx, "user_id", "") or ""),
        "nickname": str(getattr(ctx, "nickname", "") or ""),
        "created": time.time(),
        "attempts": 0,
    }
    items = _load_reminders()
    items.append(item)
    _save_reminders(items[-200:])
    logger.info(f"[tools] 已登记提醒 {rid}（{minutes} 分钟后，{item['platform']}:{item['scene']}）")
    return rid


def _qq_bot():
    try:
        from nonebot.adapters.qq import Bot as QQBot

        for bot in get_bots().values():
            if isinstance(bot, QQBot):
                return bot
    except Exception:  # noqa: BLE001
        return None
    return None


async def _send_wechat(user_id: str, text: str) -> tuple:
    """微信主动消息：token 失效/太旧就如实失败（iLink 的硬限制）。"""
    base = Path.cwd() / "data" / "nonebot_adapter_ilink"
    try:
        tokens = json.loads((base / "ilink_tokens.json").read_text(encoding="utf-8"))
        state = json.loads((base / "ilink_state.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return False, "wechat_state_missing"
    info = (tokens or {}).get(user_id) or {}
    token = str(info.get("context_token") or "")
    if not token:
        return False, "wechat_no_session_token"
    if time.time() - float(info.get("ts") or 0) > 1800:
        return False, "wechat_token_expired"
    mod = None
    for name in ("src.plugins.nonebot_adapter_ilink.client",
                 "nonebot_adapter_ilink.client"):
        try:
            mod = __import__(name, fromlist=["IlinkClient"])
            break
        except Exception:  # noqa: BLE001
            mod = None
    if mod is None:
        return False, "wechat_client_missing"
    client = mod.IlinkClient(
        base_url=str((state or {}).get("baseurl") or "https://ilinkai.weixin.qq.com"),
        state_file=str(base / "ilink_state.json"),
        bot_type="3",
    )
    client.token = str((state or {}).get("token") or "")
    client.bot_id = str((state or {}).get("bot_id") or "")
    client.user_id = str((state or {}).get("user_id") or "")
    try:
        ok = await client.send_text(user_id, token, text)
        return bool(ok), "" if ok else "wechat_send_failed"
    except Exception as exc:  # noqa: BLE001
        return False, f"wechat_error:{exc}"[:120]
    finally:
        try:
            await client.close()
        except Exception:  # noqa: BLE001
            pass


async def _deliver(item: dict) -> tuple:
    platform = str(item.get("platform") or "")
    scene = str(item.get("scene") or "")
    nickname = str(item.get("nickname") or "")
    text = str(item.get("text") or "")
    if scene == "group" and nickname:
        text = f"{nickname}，[提醒] {text}"
    else:
        text = f"[提醒] {text}"
    if platform == "qq_official":
        bot = _qq_bot()
        if bot is None:
            return False, "no_bot"
        if scene == "group" and item.get("room_id"):
            await bot.send_to_group(group_openid=str(item["room_id"]),
                                    message=text, msg_seq=_next_seq("g"))
            return True, ""
        openid = str(item.get("user_id") or item.get("room_id") or "")
        if not openid:
            return False, "missing_openid"
        await bot.send_to_c2c(openid=openid, message=text,
                              msg_seq=_next_seq("c"))
        return True, ""
    if platform == "wechat":
        return await _send_wechat(str(item.get("user_id") or ""), text)
    if platform == "qq":  # 旧 OneBot 通道
        try:
            from nonebot.adapters.onebot.v11 import Bot as OB11
        except Exception:  # noqa: BLE001
            OB11 = None
        for bot in get_bots().values():
            if OB11 is not None and isinstance(bot, OB11):
                if scene == "group" and item.get("room_id"):
                    await bot.send_group_msg(group_id=int(item["room_id"]),
                                             message=text)
                else:
                    await bot.send_private_msg(user_id=int(item["user_id"]),
                                               message=text)
                return True, ""
        return False, "no_bot"
    return False, "unsupported_platform"


async def _reminder_loop() -> None:
    logger.info("[tools] 提醒投递循环已启动")
    while True:
        try:
            await asyncio.sleep(20)
            now = time.time()
            items = _load_reminders()
            if not items:
                continue
            keep = []
            changed = False
            for item in items:
                if float(item.get("due") or 0) > now:
                    keep.append(item)
                    continue
                changed = True
                try:
                    ok, err = await _deliver(item)
                except Exception as exc:  # noqa: BLE001
                    ok, err = False, str(exc)[:160]
                if ok:
                    logger.info(f"[tools] 提醒已送达 {item.get('id')}")
                    continue
                item["attempts"] = int(item.get("attempts") or 0) + 1
                if item["attempts"] < 3:
                    item["due"] = now + 60
                    keep.append(item)
                logger.warning(
                    f"[tools] 提醒 {item.get('id')} 投递失败（{err}），"
                    f"第 {item['attempts']} 次")
            if changed:
                _save_reminders(keep)
        except asyncio.CancelledError:
            logger.info("[tools] 提醒投递循环已停止")
            break
        except Exception as exc:  # noqa: BLE001
            logger.error(f"[tools] 提醒循环异常: {exc}")


def ensure_reminder_loop() -> None:
    """第一次用到工具时挂上提醒循环（拿不到事件循环就跳过）。"""
    global _loop_task
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    if _loop_task is None or _loop_task.done():
        _loop_task = loop.create_task(_reminder_loop())


# ---- 记忆：读写真实 aichat_memory.json（按身份组）----


def memory_write(fact: str, ctx) -> dict:
    fact = str(fact or "").strip()[:500]
    if not fact:
        return {"ok": False, "error": "empty_fact"}
    key = f"{getattr(ctx, 'platform', '')}:{getattr(ctx, 'user_id', '')}"
    if not key or key == ":":
        return {"ok": False, "error": "no_identity"}
    target = identity_canonical(key)
    memory_store.add_user_memory(target, fact)
    return {"ok": True, "action": "memory_write", "user": target}


def memory_read(user: str, ctx) -> dict:
    key = f"{getattr(ctx, 'platform', '')}:{getattr(ctx, 'user_id', '')}"
    keys = identity_resolve(key) if key != ":" else []
    text = memory_store.format_memory_text(keys) if keys else ""
    requested = str(user or "").strip()
    nick = str(getattr(ctx, "nickname", "") or "")
    same = (not requested) or requested == nick or requested == str(
        getattr(ctx, "user_id", "") or "")
    return {
        "ok": True,
        "memory": text,
        "scope": "current_user" if same else "current_user_only",
        "requested": requested,
    }


# ---- 通用动作执行（工具与沙箱插件唯一出口）----

_NAME_RE = re.compile(r"[^A-Za-z0-9_.-]")


def _data_dir(ctx) -> Path:
    pack = _NAME_RE.sub("_", str(getattr(ctx, "extra", {}).get("pack_id")
                                 or "shared"))[:40] or "shared"
    return Path.cwd() / "data" / "workshop_data" / pack


def _is_private_host(host: str) -> bool:
    host = (host or "").strip().lower()
    if not host or host in ("localhost", "::1", "[::1]"):
        return True
    if host.startswith(("127.", "10.", "192.168.", "169.254.", "0.")):
        return True
    if host.startswith("172."):
        try:
            second = int(host.split(".")[1])
            return 16 <= second <= 31
        except Exception:  # noqa: BLE001
            return True
    return False


async def _act_send_message(params, ctx) -> dict:
    text = str(params.get("text") or "").strip()
    if not text:
        return {"ok": False, "error": "empty_text"}
    channel = getattr(ctx, "channel", None)
    if channel is None:
        return {"ok": False, "error": "channel_unavailable"}
    if params.get("at_user") and str(getattr(ctx, "scene", "")) == "group":
        await channel.send_text_at(text)
    else:
        await channel.send_text(text)
    return {"ok": True, "action": "send_message"}


async def _act_recall_message(params, ctx) -> dict:
    message_id = str(params.get("message_id") or "").strip()
    if not message_id:
        return {"ok": False, "error": "missing_message_id"}
    bot = _qq_bot()
    if bot is None:
        return {"ok": False, "error": "unsupported_by_channel",
                "channel": str(getattr(ctx, "platform", ""))}
    group = str(params.get("group_id") or "").strip()
    try:
        if group:
            fn = getattr(bot, "delete_group_message", None)
            if fn is None:
                return {"ok": False, "error": "unsupported_by_channel"}
            await fn(group_openid=group, message_id=message_id)
        else:
            fn = getattr(bot, "delete_c2c_message", None)
            if fn is None:
                return {"ok": False, "error": "unsupported_by_channel"}
            await fn(openid=str(getattr(ctx, "user_id", "")), message_id=message_id)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": "recall_failed", "detail": str(exc)[:160]}
    return {"ok": True, "action": "recall_message"}


async def _act_mute(params, ctx, all_users: bool) -> dict:
    bot = _qq_bot()
    if bot is None:
        return {"ok": False, "error": "unsupported_by_channel",
                "channel": str(getattr(ctx, "platform", ""))}
    try:
        minutes = max(1, min(int(params.get("minutes") or 1), 43200))
    except (TypeError, ValueError):
        return {"ok": False, "error": "invalid_minutes"}
    group = str(params.get("group_id") or getattr(ctx, "group_id", "") or "")
    if not group:
        return {"ok": False, "error": "missing_group_id"}
    if all_users:
        fn = getattr(bot, "set_group_mute_all", None)
        if fn is None:
            return {"ok": False, "error": "unsupported_by_channel",
                    "detail": "QQ 官方接口没有全员禁言能力"}
        try:
            await fn(group_openid=group, mute_seconds=minutes * 60)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": "mute_failed", "detail": str(exc)[:160]}
        return {"ok": True, "action": "mute_all", "minutes": minutes}
    user = str(params.get("user_id") or "").strip()
    if not user:
        return {"ok": False, "error": "missing_target"}
    fn = getattr(bot, "set_group_member_mute", None)
    if fn is None:
        return {"ok": False, "error": "unsupported_by_channel",
                "detail": "QQ 官方接口没有群成员禁言能力"}
    try:
        await fn(group_openid=group, user_openid=user, mute_seconds=minutes * 60)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": "mute_failed", "detail": str(exc)[:160]}
    return {"ok": True, "action": "mute_user", "minutes": minutes}


async def _act_http_request(params, ctx) -> dict:
    url = str(params.get("url") or "").strip()
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return {"ok": False, "error": "bad_url"}
    if _is_private_host(parsed.hostname):
        return {"ok": False, "error": "blocked_host", "host": parsed.hostname}
    method = str(params.get("method") or "GET").upper()
    if method not in ("GET", "POST"):
        return {"ok": False, "error": "bad_method"}
    body = params.get("body")
    data = body.encode("utf-8") if isinstance(body, str) and body else None
    headers = {"User-Agent": "AstroSwarm-Plugin/1.0"}
    raw_headers = params.get("headers") or {}
    if isinstance(raw_headers, dict):
        for key in ("Content-Type", "Accept", "Authorization", "X-API-Key"):
            value = raw_headers.get(key)
            if isinstance(value, str) and value:
                headers[key] = value[:300]
    try:
        timeout = max(1, min(int(params.get("timeout") or 10), 20))
    except (TypeError, ValueError):
        timeout = 10
    if not url.lower().startswith("https://") and "Authorization" in headers:
        headers.pop("Authorization")   # 明文传输不带凭证

    def _do():
        req = Request(url, data=data, method=method, headers=headers)
        with urlopen(req, timeout=timeout) as resp:  # noqa: S310 —— 已校验协议与内网
            raw = resp.read(400_000)
            return int(getattr(resp, "status", 200)), raw.decode("utf-8", "replace")

    try:
        status, text = await asyncio.get_running_loop().run_in_executor(None, _do)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": "http_failed", "detail": str(exc)[:200]}
    truncated = len(text) > 20000
    return {"ok": True, "status": status, "text": text[:20000], "truncated": truncated}


async def _act_data_write(params, ctx) -> dict:
    name = _NAME_RE.sub("_", str(params.get("name") or "data"))[:40] or "data"
    text = str(params.get("text") or "")
    if len(text) > 200_000:
        return {"ok": False, "error": "too_large"}
    path = _data_dir(ctx) / f"{name}.json"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": "write_failed", "detail": str(exc)[:160]}
    return {"ok": True, "name": name, "bytes": len(text.encode("utf-8"))}


async def _act_data_read(params, ctx) -> dict:
    name = _NAME_RE.sub("_", str(params.get("name") or "data"))[:40] or "data"
    path = _data_dir(ctx) / f"{name}.json"
    try:
        if not path.exists():
            return {"ok": False, "error": "not_found", "name": name}
        return {"ok": True, "name": name,
                "text": path.read_text(encoding="utf-8")[:200_000]}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": "read_failed", "detail": str(exc)[:160]}


async def _act_reminder_add(params, ctx) -> dict:
    text = str(params.get("text") or "").strip()
    if not text:
        return {"ok": False, "error": "empty_text"}
    try:
        minutes = max(1, int(params.get("minutes") or 1))
    except (TypeError, ValueError):
        return {"ok": False, "error": "invalid_minutes"}
    target = str(params.get("target") or "")
    try:
        rid = add_reminder(minutes, text, target, ctx)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": "store_error", "detail": str(exc)[:160]}
    return {"ok": True, "reminder_id": rid, "minutes": minutes,
            "remind_at": time.strftime(
                "%Y-%m-%d %H:%M:%S",
                time.localtime(time.time() + minutes * 60))}


async def _act_memory_write(params, ctx) -> dict:
    return memory_write(str(params.get("fact") or ""), ctx)


async def _act_memory_read(params, ctx) -> dict:
    return memory_read(str(params.get("user") or ""), ctx)


_ACTIONS = {
    "send_message": _act_send_message,
    "recall_message": _act_recall_message,
    "mute_user": lambda params, ctx: _act_mute(params, ctx, False),
    "mute_all": lambda params, ctx: _act_mute(params, ctx, True),
    "http_request": _act_http_request,
    "data_write": _act_data_write,
    "data_read": _act_data_read,
    "reminder_add": _act_reminder_add,
    "memory_write": _act_memory_write,
    "memory_read": _act_memory_read,
}

# 动作需要的权限（None = 无门槛）；沙箱侧再查一遍
ACTION_PERMISSIONS = {
    "send_message": "send_message",
    "recall_message": "group_admin",
    "mute_user": "group_admin",
    "mute_all": "group_admin",
    "http_request": "network",
    "data_write": None,
    "data_read": None,
    "reminder_add": "timer",
    "memory_write": "memory",
    "memory_read": "memory",
}


async def do_action(action: str, params: dict, ctx) -> dict:
    """执行一个工具/沙箱插件请求的动作（主程序侧，全部要过校验）。"""
    handler = _ACTIONS.get(action)
    if handler is None:
        return {"ok": False, "error": "unknown_action", "action": str(action)}
    needed = ACTION_PERMISSIONS.get(action)
    if needed and not ctx.can(needed):
        return {"ok": False, "error": "permission_denied",
                "permission": needed, "action": str(action)}
    try:
        return await handler(dict(params or {}), ctx)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": "action_error",
                "detail": str(exc)[:200], "action": str(action)}


async def execute_tool_with_actions(runtime, name: str, args: dict, ctx) -> str:
    """统一执行入口：沙箱插件走子进程，普通能力包的动作排队后由主程序执行。

    普通工具（官方能力包）是同步函数，没法在函数里 await 发送动作，
    所以先排队、工具返回后由这里真正执行，再把真实回执合并进结果 ——
    "工具说成功、动作其实失败"会被如实写回去。
    """
    from qbotmanager.core.agent.tool import merge_effect_report

    spec = runtime.registry.get(name)
    ctx.effect_results.clear()
    queued = []
    if spec is not None and getattr(spec, "sandbox", False):
        ctx.extra["pack_id"] = spec.pack_id

        async def host(action, params, tool_ctx):
            # 沙箱里是同步一问一答，这里顺手记一份回执：
            # 插件如果"动作失败了还说成功"，结果一样会被改回真相。
            res = await do_action(action, params, tool_ctx)
            tool_ctx.effect_results.append(res)
            return res

        result = await runtime.execute_async(name, args, ctx, host=host)
        return merge_effect_report(result, ctx.effect_results)
    ctx.bind_send(lambda action, prm: (
        queued.append((str(action), dict(prm or {}))),
        {"ok": True, "queued": True, "action": str(action)})[1])
    if spec is not None and spec.pack_id:
        # 每个插件的数据各自一个目录，插件之间互相看不到对方的数据
        ctx.extra["pack_id"] = spec.pack_id
    try:
        result = runtime.execute(name, args, ctx)
    finally:
        ctx.bind_send(None)
    if not queued:
        return result
    ctx.effect_results.clear()
    for action, params in queued:
        ctx.effect_results.append(await do_action(action, params, ctx))
    return merge_effect_report(result, ctx.effect_results)


class BridgeStore:
    """给工具用的 store：记忆 + 提醒都落到真实文件。"""

    def __init__(self, ctx):
        self._ctx = ctx

    def add_reminder(self, minutes, text, target=""):
        return add_reminder(minutes, text, target, self._ctx)

    def remember(self, user, fact):
        res = memory_write(fact, self._ctx)
        if not res.get("ok"):
            raise RuntimeError(str(res.get("error") or "memory_failed"))
        return True

    def fetch_memory(self, user=""):
        res = memory_read(user, self._ctx)
        if not res.get("ok"):
            raise RuntimeError(str(res.get("error") or "memory_failed"))
        return res.get("memory")


def build_tool_context(msg, channel, memory_enabled: bool = True) -> ToolContext:
    """按当前消息/通道建工具上下文（旧调用方不传 platform 时不过滤）。"""
    perms = permissions_for(msg)
    if not memory_enabled:
        perms.discard("memory")
    scene = str(getattr(msg, "scene", "") or "")
    room_id = str(getattr(msg, "room_id", "") or "")
    ctx = ToolContext(
        permissions=perms,
        platform=str(getattr(msg, "platform", "") or ""),
        scene=scene,
        user_id=str(getattr(msg, "user_id", "") or ""),
        group_id=room_id if scene == "group" else "",
        nickname=str(getattr(msg, "nickname", "") or ""),
        is_superuser=bool(getattr(msg, "is_superuser", False)),
        extra={"room_id": room_id,
               "at_others": bool((getattr(msg, "extra", None) or {}).get("at_others"))},
        channel=channel,
    )
    ctx.store = BridgeStore(ctx)
    ensure_reminder_loop()
    return ctx
