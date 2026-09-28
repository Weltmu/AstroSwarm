# -*- coding: utf-8 -*-
"""记忆分层：全局记忆（全平台共享）+ 用户记忆（跨平台，按身份 key）。

- 全局记忆：所有平台、所有用户共享的长期记忆；
- 用户记忆：按身份 key（如 qq:12345 / wechat:xxx@im.wechat）存储；
  绑定身份后（identity.py），同一人的多个平台 key 共享一份用户记忆。
"""
import json
import time
from typing import Dict, List

import nonebot_plugin_localstore as store
from nonebot import logger

MEMORY_FILE = store.get_plugin_data_file("aichat_memory.json")
MAX_GLOBAL = 100
MAX_USER = 50
MAX_MEMORY_TEXT = 1200

_data: Dict = {"global": [], "users": {}}

def load_memory() -> None:
    global _data
    if MEMORY_FILE.exists():
        try:
            raw = json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                raw.setdefault("global", [])
                raw.setdefault("users", {})
                _data = raw
        except Exception as e:
            logger.warning(f"加载记忆文件失败: {e}")
            _data = {"global": [], "users": {}}


def save_memory() -> None:
    try:
        MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        MEMORY_FILE.write_text(json.dumps(_data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        logger.error(f"保存记忆文件失败: {e}")


def _entry(text: str) -> dict:
    return {"content": text, "ts": time.time()}


def get_global_memory() -> List[dict]:
    return _data.get("global", [])


def add_global_memory(text: str) -> None:
    text = text.strip()
    if not text:
        return
    items = _data.setdefault("global", [])
    items.append(_entry(text))
    if len(items) > MAX_GLOBAL:
        del items[: len(items) - MAX_GLOBAL]
    save_memory()


def clear_global_memory() -> None:
    _data["global"] = []
    save_memory()


def get_user_memory(identity_key: str) -> List[dict]:
    return _data.setdefault("users", {}).get(identity_key, [])


def add_user_memory(identity_key: str, text: str) -> None:
    text = text.strip()
    if not text or not identity_key:
        return
    users = _data.setdefault("users", {})
    items = users.setdefault(identity_key, [])
    items.append(_entry(text))
    if len(items) > MAX_USER:
        del items[: len(items) - MAX_USER]
    save_memory()


def clear_user_memory(identity_key: str) -> None:
    users = _data.setdefault("users", {})
    if identity_key in users:
        del users[identity_key]
        save_memory()


def format_memory_text(identity_keys: List[str]) -> str:
    """把全局记忆 + 绑定身份的用户记忆拼成一段提示文本（去重、限长）。"""
    lines: List[str] = []
    seen = set()
    for entry in get_global_memory():
        content = str(entry.get("content", "")).strip()
        if content and content not in seen:
            seen.add(content)
            lines.append(content)
    for key in identity_keys:
        for entry in get_user_memory(key):
            content = str(entry.get("content", "")).strip()
            if content and content not in seen:
                seen.add(content)
                lines.append(content)
    if not lines:
        return ""
    text = "\n".join(f"- {line}" for line in lines)
    if len(text) > MAX_MEMORY_TEXT:
        text = text[:MAX_MEMORY_TEXT] + "..."
    return text


load_memory()
