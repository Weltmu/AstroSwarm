# -*- coding: utf-8 -*-
"""内置 AI 插件配置桥：服务商预设 + 读写机器人侧 aichat_manager.json。

ai 插件（assets/plugins/ai）使用 nonebot_plugin_localstore 存储配置；
.env 已设置 LOCALSTORE_USE_CWD=true，localstore 落在机器人目录内：
  - 管理配置：<bot>/config/ai/aichat_manager.json
  - 记忆：     <bot>/data/ai/aichat_memory.json
  - 身份绑定： <bot>/config/ai/aichat_identity.json
"""
import json
import shutil
from pathlib import Path

MANAGER_NAME = "aichat_manager.json"
MEMORY_NAME = "aichat_memory.json"
IDENTITY_NAME = "aichat_identity.json"

_DEFAULT_PERSONALITY = "你是星群（AstroSwarm）的 AI 助手，负责跨平台对话与记忆管理。回答保持简洁直接，情绪随心情波动，回答长短看情况，只给关键信息，不啰嗦。"

# 常见大厂 OpenAI 兼容接口预设：切换服务商自动填 base_url + 默认模型
AI_PROVIDERS = [
    {"key": "custom", "name": "自定义接口", "url": "", "model": ""},
    {"key": "deepseek", "name": "DeepSeek", "url": "https://api.deepseek.com", "model": "deepseek-v4-flash"},
    {"key": "dashscope", "name": "通义千问（百炼）", "url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "model": "qwen3.7-flash"},
    {"key": "zhipu", "name": "智谱 GLM", "url": "https://open.bigmodel.cn/api/paas/v4", "model": "glm-5.2"},
    {"key": "moonshot", "name": "Kimi（Moonshot）", "url": "https://api.moonshot.cn/v1", "model": "kimi-k3"},
    {"key": "openai", "name": "OpenAI", "url": "https://api.openai.com/v1", "model": "gpt-5.6"},
]

PROVIDER_BY_URL = {}
for _p in AI_PROVIDERS:
    if _p["url"]:
        PROVIDER_BY_URL[_p["url"].rstrip("/")] = _p["key"]


def normalize_api_url(url: str) -> str:
    """规范化 OpenAI 兼容接口地址，兼容用户误贴完整 /chat/completions 的情况。"""
    u = (url or "").strip()
    if not u:
        return ""
    lowered = u.lower()
    if lowered.endswith("/chat/completions"):
        u = u[: -len("/chat/completions")]
    return u.rstrip("/")


def _first_existing(*paths: Path) -> Path | None:
    for p in paths:
        if p.exists():
            return p
    return None


def _manager_candidates(settings) -> list:
    """管理配置候选路径：localstore use_cwd 规范路径优先。"""
    bot = settings.bot_dir
    return [
        bot / "config" / "ai" / MANAGER_NAME,
        bot / "data" / "config" / "ai" / MANAGER_NAME,
    ]


def manager_file(settings) -> Path:
    """机器人侧 AI 管理配置文件（规范路径优先，旧路径回退）。"""
    found = _first_existing(*_manager_candidates(settings))
    return found if found is not None else _manager_candidates(settings)[0]


def manager_write_file(settings) -> Path:
    """写入用固定规范路径：插件 ai 的 localstore（use_cwd）读 config/ai，旧路径仅迁移。"""
    return settings.bot_dir / "config" / "ai" / MANAGER_NAME


def memory_file(settings) -> Path:
    bot = settings.bot_dir
    return bot / "data" / "ai" / MEMORY_NAME


def identity_file(settings) -> Path:
    bot = settings.bot_dir
    return _first_existing(
        bot / "config" / "ai" / IDENTITY_NAME,
        bot / "data" / "config" / "ai" / IDENTITY_NAME,
    ) or (bot / "config" / "ai" / IDENTITY_NAME)


def read_manager(settings) -> dict:
    """读取 ai 插件管理配置；无文件返回空 dict。"""
    p = manager_file(settings)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (ValueError, OSError):
        return {}


def current_config(settings) -> dict:
    """当前使用的 AI 配置（name/api_url/model/api_key），未配置返回空 dict。"""
    mgr = read_manager(settings)
    configs = mgr.get("ai_configs") or []
    idx = int(mgr.get("current_ai_config") or 0)
    if configs and 0 <= idx < len(configs):
        return configs[idx] if isinstance(configs[idx], dict) else {}
    return {}


def _default_manager() -> dict:
    return {
        "super_users": [],
        "enabled_groups": [],
        "chat_enabled": True,
        "ai_configs": [],
        "current_ai_config": 0,
        "image_recognition_enabled": False,
        "current_image_recognition_config": 0,
        "enable_search": False,
        "mcp_enabled": False,
        "mcp_servers": {},
        "personality": _DEFAULT_PERSONALITY,
        "proactive_enabled": False,
        "proactive_targets": [],
        "proactive_groups": [],
        "proactive_interval_min": 30,
        "proactive_interval_max": 90,
        "proactive_cooldown": 30,
        "proactive_quiet_start": 0,
        "proactive_quiet_end": 8,
        "memory_enabled": True,
    }


def _write_manager(settings, mgr: dict) -> bool:
    try:
        p = manager_write_file(settings)
        p.parent.mkdir(parents=True, exist_ok=True)
        # 首次切换到规范路径时，把旧路径数据带过来，避免丢配置
        if not p.exists():
            for old in _manager_candidates(settings):
                if old != p and old.exists():
                    shutil.copy2(old, p)
                    break
        p.write_text(json.dumps(mgr, ensure_ascii=False, indent=2), encoding="utf-8")
        return True
    except OSError:
        return False


def save_config(settings, api_key: str, api_url: str, model: str, name: str = "main") -> bool:
    """把 API 配置写入机器人侧 aichat_manager.json 并设为当前配置。

    只更新 ai_configs 里同名的项（没有则追加），不动其它设置（MCP/记忆/群聊等）。
    机器人下次启动（或 ac config 命令重载）后生效。
    """
    mgr = read_manager(settings)
    if not mgr:
        mgr = _default_manager()
    configs = mgr.setdefault("ai_configs", [])
    if not isinstance(configs, list):
        configs = []
        mgr["ai_configs"] = configs
    entry = {
        "name": name,
        "api_key": (api_key or "").strip(),
        "api_url": normalize_api_url(api_url),
        "model": (model or "").strip(),
    }
    for i, cfg in enumerate(configs):
        if isinstance(cfg, dict) and cfg.get("name") == name:
            configs[i] = entry
            break
    else:
        configs.append(entry)
    mgr["current_ai_config"] = configs.index(entry)
    return _write_manager(settings, mgr)


def read_personality(settings) -> str:
    """读取机器人侧人设；未配置返回默认人设。"""
    mgr = read_manager(settings)
    return str(mgr.get("personality") or _default_manager()["personality"])


def save_personality(settings, text: str) -> bool:
    """把人设写入机器人侧 aichat_manager.json（重启机器人生效）。"""
    mgr = read_manager(settings) or _default_manager()
    mgr["personality"] = (text or "").strip()
    return _write_manager(settings, mgr)


def read_proactive(settings) -> dict:
    """读取主动聊天配置。"""
    mgr = read_manager(settings)
    return {
        "enabled": bool(mgr.get("proactive_enabled", False)),
        "targets": list(mgr.get("proactive_targets") or []),
        "groups": list(mgr.get("proactive_groups") or []),
        "interval_min": int(mgr.get("proactive_interval_min", 30)),
        "interval_max": int(mgr.get("proactive_interval_max", 90)),
        "cooldown": int(mgr.get("proactive_cooldown", 30)),
        "quiet_start": int(mgr.get("proactive_quiet_start", 0)),
        "quiet_end": int(mgr.get("proactive_quiet_end", 8)),
    }


def save_proactive(
    settings,
    enabled: bool,
    targets: list,
    groups: list,
    interval_min: int = 30,
    interval_max: int = 90,
    cooldown: int = 30,
    quiet_start: int = 0,
    quiet_end: int = 8,
) -> bool:
    """把主动聊天配置写入机器人侧 aichat_manager.json（重启机器人生效）。"""
    mgr = read_manager(settings) or _default_manager()
    mgr["proactive_enabled"] = bool(enabled)
    mgr["proactive_targets"] = [str(x).strip() for x in targets if str(x).strip()]
    mgr["proactive_groups"] = [str(x).strip() for x in groups if str(x).strip()]
    mgr["proactive_interval_min"] = max(1, int(interval_min))
    mgr["proactive_interval_max"] = max(1, int(interval_max))
    if mgr["proactive_interval_max"] < mgr["proactive_interval_min"]:
        mgr["proactive_interval_max"] = mgr["proactive_interval_min"]
    mgr["proactive_cooldown"] = max(1, int(cooldown))
    mgr["proactive_quiet_start"] = max(0, min(23, int(quiet_start)))
    mgr["proactive_quiet_end"] = max(0, min(23, int(quiet_end)))
    return _write_manager(settings, mgr)


def read_memory_enabled(settings) -> bool:
    """全局记忆开关（默认开启）。"""
    mgr = read_manager(settings)
    return bool(mgr.get("memory_enabled", True))


def save_memory_enabled(settings, enabled: bool) -> bool:
    mgr = read_manager(settings) or _default_manager()
    mgr["memory_enabled"] = bool(enabled)
    return _write_manager(settings, mgr)


def read_mcp(settings) -> dict:
    """读取 MCP 总开关与服务器配置。"""
    mgr = read_manager(settings)
    servers = mgr.get("mcp_servers")
    return {
        "enabled": bool(mgr.get("mcp_enabled", False)),
        "servers": servers if isinstance(servers, dict) else {},
    }


def save_mcp(settings, enabled: bool, servers: dict) -> bool:
    mgr = read_manager(settings) or _default_manager()
    mgr["mcp_enabled"] = bool(enabled)
    mgr["mcp_servers"] = servers if isinstance(servers, dict) else {}
    return _write_manager(settings, mgr)


# MCP 服务器允许的传输类型（桌面端页面的 JSON 编辑器与无头端 console_ext.mcp_save 同一套）
MCP_TYPES = ("sse", "stdio", "ws", "http", "streamable_http")


def normalize_mcp_servers(servers) -> dict:
    """校验并清洗 MCP 服务器配置，出错抛 ValueError（消息直接给用户看）。

    以前桌面端只检查「是不是 JSON 对象」就存盘：type 写错、stdio 没填 command、
    名称超长都会原样落盘，机器人重启后 MCP 直接起不来，用户只能自己猜哪儿写错了。
    这里按无头端的规则逐项校验 + 只保留认识的字段。
    """
    if servers is None:
        return {}
    if not isinstance(servers, dict):
        raise ValueError('MCP 配置必须是 JSON 对象，例如 {"名称": {"type": "sse", "url": "..."}}')
    clean = {}
    for name, spec in servers.items():
        key = str(name).strip()
        if not key or len(key) > 64:
            raise ValueError(f"MCP 名称不合法：{name!r}（1~64 个字符，不能为空）")
        if not isinstance(spec, dict):
            raise ValueError(f"「{key}」的配置必须是对象，例如 {{\"type\": \"sse\", \"url\": \"...\"}}")
        typ = str(spec.get("type") or "sse").strip().lower()
        if typ not in MCP_TYPES:
            raise ValueError(f"「{key}」的 type 不支持：{typ}（只能是 {'/'.join(MCP_TYPES)}）")
        if typ == "stdio":
            if not str(spec.get("command") or "").strip():
                raise ValueError(f"「{key}」是 stdio，必须填 command")
        elif not str(spec.get("url") or "").strip():
            raise ValueError(f"「{key}」必须填 url")
        item = {"type": typ, "enabled": bool(spec.get("enabled", True))}
        for k in ("url", "command", "args", "env", "headers"):
            if spec.get(k) not in (None, "", [], {}):
                item[k] = spec[k]
        clean[key] = item
    return clean


def provider_key_for_url(url: str) -> str:
    return PROVIDER_BY_URL.get((url or "").rstrip("/"), "custom")
