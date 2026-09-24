# -*- coding: utf-8 -*-
"""李清菡官方 QQ 适配层：nonebot-adapter-qq 事件 → 李清菡事件 dict；动作 → 官方 API。

只依赖标准库（urllib），可在无 httpx 的构建环境测试。
官方通道能力裁剪见 capabilities.py。
"""
import json
import logging
import time
import urllib.request
from datetime import datetime, timezone

API_BASE = "https://api.sgroup.qq.com"
_RESTRICT = "/v2/groups/{group_openid}/restrict_chat_setting"


def _text_of(message):
    """把李清菡消息参数（str 或 segments 列表）转成纯文本。"""
    if isinstance(message, str):
        return message
    parts = []
    for s in message or []:
        if isinstance(s, dict) and s.get("type") == "text":
            parts.append(str(s.get("data", {}).get("text", "")))
        elif isinstance(s, dict) and s.get("type") == "image":
            parts.append("[图片]")
        elif isinstance(s, dict) and s.get("type") == "at":
            parts.append("@")
    return "".join(parts).strip()


def to_data(event, bot_qq="", source=None):
    """NoneBot QQ 官方消息事件 → 李清菡 on_event dict。"""
    is_group = bool(getattr(event, "group_openid", None))
    user_id = str(event.get_user_id() or "")
    group_id = str(getattr(event, "group_openid", "") or "") if is_group else ""
    plain = str(getattr(event, "get_plaintext", lambda: "")() or "").strip()
    segs = []
    try:
        raw_segs = event.get_message()
    except Exception:  # noqa: BLE001
        raw_segs = []
    for s in raw_segs or []:
        s_type = str(getattr(s, "type", ""))
        try:
            s_data = dict(getattr(s, "data", None) or {})
        except Exception:  # noqa: BLE001
            s_data = {}
        if s_type == "text":
            segs.append({"type": "text", "data": {"text": str(s_data.get("text") or "")}})
        elif s_type == "image":
            segs.append({"type": "image", "data": {
                "file": str(s_data.get("file") or s_data.get("file_info") or ""),
                "url": str(s_data.get("url") or ""),
            }})
        elif s_type == "at":
            segs.append({"type": "at", "data": {
                "qq": str(s_data.get("qq") or s_data.get("user_openid")
                          or s_data.get("member_openid") or ""),
                "name": str(s_data.get("name") or ""),
            }})
        else:
            segs.append({"type": s_type, "data": s_data})
    if not segs:
        segs.append({"type": "text", "data": {"text": plain}})
    to_me = bool(getattr(event, "to_me", False))
    if is_group and to_me and bot_qq:
        segs.insert(0, {"type": "at", "data": {"qq": bot_qq, "name": ""}})
    author = getattr(event, "author", None)
    nickname = str(getattr(author, "username", "") or "") if author is not None else ""
    return {
        "post_type": "message",
        "message_type": "group" if is_group else "private",
        "user_id": user_id,
        "group_id": group_id,
        "message_id": str(getattr(event, "id", "") or ""),
        "message": segs,
        "raw_message": plain,
        "member_role": str(getattr(author, "member_role", "") or "") if author is not None else "",
        "sender": {"nickname": nickname, "card": nickname},
        "source": source or ("qq:group" if is_group else "qq:c2c"),
    }


def _rfc3339(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class OfficialChannel:
    """把李清菡 ob.action 动作映射到 QQ 官方 API。"""

    def __init__(self):
        self.bot = None
        self._event = None
        self._source = "qq:c2c"
        self._seq = {}
        self._msg_scope = {}
        self.api_base = API_BASE

    def attach(self, bot):
        self.bot = bot

    def set_current(self, bot, event, source="qq:c2c"):
        self.bot = bot
        self._event = event
        self.set_source(source)

    def set_source(self, source):
        self._source = source or "qq:c2c"

    def _is_group(self, params):
        if self._source == "qq:group":
            return True
        if "group_id" in params:
            return True
        return bool(getattr(self._event, "group_openid", None))

    @staticmethod
    def _resp_id(resp):
        if isinstance(resp, dict):
            return str(resp.get("id") or resp.get("message_id") or "")
        return str(getattr(resp, "id", "") or "")

    async def action(self, action, params=None):
        params = params or {}
        try:
            if action == "send_private_msg":
                return await self._send_private(params)
            if action == "send_group_msg":
                return await self._send_group(params)
            if action == "delete_msg":
                return await self._delete(params)
            if action == "set_group_ban":
                return await self._set_group_ban(params)
            if action == "set_group_whole_ban":
                return {"error": "官方通道暂不支持全员禁言接口"}
            if action in ("get_group_member_info", "get_group_member_list"):
                return None
            if action == "set_group_add_request":
                return {"error": "官方入群审批接口尚未接入"}
            return {"error": f"未知动作 {action}"}
        except Exception as e:  # noqa: BLE001
            logging.exception("QQ 官方动作 %s 失败", action)
            return {"error": f"{action} 执行失败：{e}"}

    async def _send_private(self, params):
        openid = str(params.get("user_id") or "")
        text = _text_of(params.get("message"))
        if self.bot is None:
            return {"error": "QQ 官方机器人未连接"}
        ev = self._event
        if ev is not None and str(getattr(ev, "get_user_id", lambda: "")()) == openid:
            resp = await self.bot.send(ev, text)
        else:
            seq = self._next_seq(f"c2c:{openid}")
            resp = await self.bot.send_to_c2c(openid=openid, message=text, msg_seq=seq)
        mid = self._resp_id(resp)
        if mid:
            self._msg_scope[mid] = ("c2c", openid)
        return {"message_id": mid}

    async def _send_group(self, params):
        gid = str(params.get("group_id") or "")
        text = _text_of(params.get("message"))
        if self.bot is None:
            return {"error": "QQ 官方机器人未连接"}
        ev = self._event
        if ev is not None and str(getattr(ev, "group_openid", "") or "") == gid:
            resp = await self.bot.send(ev, text)
        else:
            seq = self._next_seq(f"group:{gid}")
            resp = await self.bot.send_to_group(group_openid=gid, message=text, msg_seq=seq)
        mid = self._resp_id(resp)
        if mid:
            self._msg_scope[mid] = ("group", gid)
        return {"message_id": mid}

    async def _delete(self, params):
        mid = str(params.get("message_id") or "")
        scope = self._msg_scope.get(mid)
        if scope:
            kind, target = scope
            if kind == "c2c":
                await self.bot.delete_c2c_message(openid=target, message_id=mid)
            else:
                await self.bot.delete_group_message(group_openid=target, message_id=mid)
            return {"ok": True}
        return {"error": "找不到可撤回的消息记录（官方仅支持撤回机器人自己的消息）"}

    def _next_seq(self, key):
        self._seq[key] = self._seq.get(key, 0) + 1
        return self._seq[key]

    async def _set_group_ban(self, params):
        gid = str(params.get("group_id") or "")
        uid = str(params.get("user_id") or "")
        duration = max(0, int(params.get("duration") or 0))
        if not gid or not uid:
            return {"error": "禁言缺少 group_id / user_id"}
        if self.bot is None:
            return {"error": "QQ 官方机器人未连接"}
        token = await self.bot.get_access_token()
        url = self.api_base + _RESTRICT.format(group_openid=gid)
        state = self.http_request("GET", url, token) or {}
        members = state.get("members") or []
        muted = any(str(m.get("member_openid") or "") == uid for m in members)
        if duration == 0:
            member_body = {"op": "del", "member_openid": uid}
        else:
            op = "update" if muted else "add"
            member_body = {
                "op": op,
                "member_openid": uid,
                "mute_expire_at": _rfc3339(time.time() + duration),
            }
        self.http_request("POST", url, token, {"members": [member_body]})
        return {"ok": True, "op": member_body["op"]}

    def http_request(self, method, url, token, body=None):
        req = urllib.request.Request(url, method=method)
        req.add_header("Authorization", f"QQBot {token}")
        req.add_header("Content-Type", "application/json")
        if body is not None:
            req.data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8", "ignore")
        return json.loads(raw) if raw else {}


class NoopChannel:
    """微信桥通道：回复由桥返回给 qbm_bridge_client 发送，这里不真发。"""

    async def action(self, action, params=None):
        if action in ("send_private_msg", "send_group_msg"):
            return {"ok": True, "noop": True}
        return {"error": "微信通道不支持该动作"}


class DispatchChannel:
    """按当前 source 分发给官方 QQ 通道或微信 Noop 通道。"""

    def __init__(self):
        self.official = OfficialChannel()
        self.noop = NoopChannel()
        self._source = "qq:c2c"

    def attach(self, bot):
        self.official.attach(bot)

    def set_current(self, bot, event, source="qq:c2c"):
        self.official.set_current(bot, event, source)
        self.set_source(source)

    def set_source(self, source):
        self._source = source or "qq:c2c"

    async def action(self, action, params=None):
        if self._source.startswith("wechat"):
            return await self.noop.action(action, params)
        return await self.official.action(action, params)
