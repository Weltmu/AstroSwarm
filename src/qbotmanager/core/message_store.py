# -*- coding: utf-8 -*-
"""跨平台消息/大脑数据源：读取内置 AI 插件落盘数据，供首页/消息中心/AI 大脑页展示。"""
import json
from pathlib import Path


def _load_json(path: Path) -> dict:
    """mtime 缓存读取：文件没变就不重读（首页等每 2 秒刷新的热路径）。"""
    try:
        st = path.stat()
        key = (str(path), st.st_mtime_ns, st.st_size)
    except OSError:
        return {}
    cached = _JSON_CACHE.get(key)
    if cached is not None:
        return cached
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        data = data if isinstance(data, dict) else {}
    except (ValueError, OSError):
        data = {}
    if len(_JSON_CACHE) > 64:
        _JSON_CACHE.clear()
    _JSON_CACHE[key] = data
    return data


def _load_jsonl(path: Path) -> list:
    """读取 JSONL（每行一个 JSON 对象）。

    不缓存：追加写时同秒同大小可能漏读；文件很小，每 2 秒读一次开销可忽略。
    """
    rows = []
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    except OSError:
        rows = []
    return rows


_JSON_CACHE: dict = {}


def context_file(settings) -> Path:
    return settings.bot_dir / "data" / "ai" / "aichat_context.json"


def dsh_sessions_dir(settings) -> Path:
    return settings.root / "dsh" / "home" / "sessions"


def _read_zstd(path: Path) -> str:
    """解压 dsh 会话文件（session.jsonl.zstd）为文本；失败返回空串。"""
    try:
        import io
        import zstandard
        dctx = zstandard.ZstdDecompressor()
        raw = dctx.stream_reader(io.BytesIO(path.read_bytes())).read()
        return raw.decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return ""


def load_dsh_conversations(settings, limit: int = 20) -> list:
    """从 dsh 会话存储读取 QQ 对话（dsh 是 QQ 消息的唯一落盘来源）。"""
    base = dsh_sessions_dir(settings)
    if not base.exists():
        return []
    convs = []
    for ws in base.iterdir():
        if not ws.is_dir():
            continue
        for sess in ws.iterdir():
            f = sess / "session.jsonl.zstd"
            if not f.exists():
                continue
            text = _read_zstd(f)
            last_user = ""
            last_assistant = ""
            count = 0
            ts = 0.0
            for line in text.splitlines():
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                t = obj.get("type")
                if t not in ("user/message", "assistant/message"):
                    continue
                data = obj.get("data") or {}
                content = ""
                for part in data.get("content") or []:
                    if isinstance(part, dict) and part.get("type") == "text":
                        content += str(part.get("text") or "")
                content = content.strip()
                if not content:
                    continue
                count += 1
                try:
                    ts = max(ts, float(obj.get("time") or 0))
                except (TypeError, ValueError):
                    pass
                if t == "user/message":
                    last_user = content[:80]
                else:
                    last_assistant = content[:80]
            last = last_assistant or last_user
            if not last:
                continue
            convs.append(_with_key({
                "platform": "qq",
                "scene": "private",
                "room": sess.name[:12],
                "count": count,
                "last": last,
                "ts": ts,
            }))
    convs.sort(key=lambda c: c.get("ts") or 0, reverse=True)
    return convs[:limit]


def _parse_key(key: str):
    """把会话记忆 key 解析成 (platform, scene, room)。"""
    if key.startswith("group_"):
        return "qq", "group", key[len("group_"):]
    if key.isdigit():
        return "qq", "private", key
    if key.startswith("wechat:"):
        parts = key.split(":", 2)
        return "wechat", parts[1], parts[2] if len(parts) > 2 else ""
    if key.startswith("feishu:"):
        parts = key.split(":", 2)
        return "feishu", parts[1], parts[2] if len(parts) > 2 else ""
    if key.startswith("telegram:"):
        parts = key.split(":", 2)
        return "telegram", parts[1], parts[2] if len(parts) > 2 else ""
    return "qq", "private", key


PLATFORM_LABELS = {
    "qq": "QQ",
    "wechat": "微信",
    "feishu": "飞书",
    "telegram": "纸飞机",
}

# 会话场景：群聊 / 私聊。控制台与桌面端都用它拼「QQ 群 123456」这种能区分的标题
SCENE_LABELS = {"group": "群", "private": "好友"}


def conversation_key(platform: str, scene: str, room: str) -> str:
    """按 (platform, scene, room) 还原会话 key —— 与 _parse_key 互逆。

    key 是界面上「这个会话是哪个群 / 哪个好友」的唯一来源：
    多个 QQ 会话如果只有 platform，就都显示成「QQ 会话」，分不清谁是谁。
    """
    platform = str(platform or "qq").lower()
    scene = str(scene or "").strip().lower()
    room = str(room or "").strip()
    if not room:
        return ""
    if platform == "qq":
        return f"group_{room}" if scene == "group" else room
    return f"{platform}:{scene or 'private'}:{room}"


def _with_key(item: dict) -> dict:
    """补齐会话 key 与 last_text（last 是旧字段，两个都留着，别让老界面读不到）。"""
    if not item.get("key"):
        item["key"] = conversation_key(
            item.get("platform"), item.get("scene"), item.get("room"))
    if item.get("last") and not item.get("last_text"):
        item["last_text"] = item["last"]
    return item


def load_conversations(settings, limit: int = 200) -> list:
    """从 AI 插件上下文文件读取会话列表（按 key 顺序，最近的在后）。"""
    data = _load_json(context_file(settings))
    convs = []
    for key, messages in data.items():
        if not isinstance(messages, list) or not messages:
            continue
        platform, scene, room = _parse_key(str(key))
        last = ""
        for m in reversed(messages):
            content = str(m.get("content", "")).strip()
            if content:
                last = content
                break
        convs.append(_with_key({
            "platform": platform,
            "scene": scene,
            "room": room,
            "count": len(messages),
            "last": last[:80],
        }))
    # 合并 ilink 适配器落盘的微信原始消息（不依赖 AI 是否回复）
    for m in _load_jsonl(settings.bot_dir / "data" / "nonebot_adapter_ilink" / "messages.jsonl"):
        key = str(m.get("from_user_id") or "")
        if not key:
            continue
        existing = next((c for c in convs if c["platform"] == "wechat" and c["room"] == key), None)
        try:
            m_ts = float(m.get("create_time_ms") or m.get("time") or 0) / 1000.0
        except (TypeError, ValueError):
            m_ts = 0.0
        if existing is None:
            existing = {
                "platform": "wechat",
                "scene": "group" if m.get("message_type") == "group" else "private",
                "room": key,
                "count": 0,
                "last": "",
                "last_text": "",
                "key": conversation_key(
                    "wechat",
                    "group" if m.get("message_type") == "group" else "private",
                    key),
                "ts": 0.0,
            }
            convs.append(existing)
        existing["count"] += 1
        existing["ts"] = max(existing.get("ts") or 0.0, m_ts)
        text = str(m.get("text") or "").strip()
        if text:
            existing["last"] = text[:80]
            existing["last_text"] = text[:80]
    # 并入 dsh 的 QQ 会话（QQ 消息由 dsh 落盘，不经过 AI 插件）
    dsh_convs = load_dsh_conversations(settings, limit=max(limit, 20))
    seen_keys = {(c["platform"], c["room"]) for c in convs}
    for c in dsh_convs:
        key = (c["platform"], c["room"])
        if key in seen_keys:
            continue
        convs.append(c)
        seen_keys.add(key)
    # 优先按时间倒序（dsh/ilink 有时间戳），无时间戳的按消息数
    convs.sort(key=lambda c: (c.get("ts") or 0.0, c["count"]), reverse=True)
    return convs[:limit]


def load_message_count(settings) -> int:
    data = _load_json(context_file(settings))
    count = sum(len(v) for v in data.values() if isinstance(v, list))
    count += sum(c["count"] for c in load_dsh_conversations(settings, limit=1000))
    return count


def brain_summary(settings) -> dict:
    """AI 大脑摘要：模型/MCP/记忆/绑定（读内置 ai 插件落盘数据，兼容旧版路径）。"""
    from .ai_config import identity_file, manager_file, memory_file
    mgr = _load_json(manager_file(settings))
    memory = _load_json(memory_file(settings))
    identity = _load_json(identity_file(settings))
    ai_configs = mgr.get("ai_configs") or []
    idx = int(mgr.get("current_ai_config") or 0)
    model = ""
    if ai_configs and 0 <= idx < len(ai_configs):
        model = str(ai_configs[idx].get("model") or "")
    groups = identity.values() if isinstance(identity, dict) else []
    binds = sum(1 for g in groups if isinstance(g, list) and len(g) > 1)
    return {
        "model": model,
        "mcp_enabled": bool(mgr.get("mcp_enabled")),
        "mcp_servers": len(mgr.get("mcp_servers") or {}),
        "memory_global": len(memory.get("global") or []),
        "memory_users": len(memory.get("users") or {}),
        "identity_binds": binds,
    }
