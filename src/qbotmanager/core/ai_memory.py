# -*- coding: utf-8 -*-
"""内置 AI 插件的「全局记忆」读写（<bot>/data/ai/aichat_memory.json）。

结构与无头端控制台 `console_ext` 的实现一致：

    {"global": [记忆...], "users": {"<用户id>": [记忆...]}}

- 一条记忆可能是字符串，也可能是 dict（取 text/content/summary/fact/value 任一字段）；
- 文件不存在 = 空结构；**文件存在但解析失败要报错**，不能当成空 —— 否则紧接着一次
  保存就把用户攒的记忆覆盖没了；
- 改动前留一份带时间戳 + 随机后缀的备份（同一秒内连点两次不会写到同一个备份）。

路径一律走 ai_config.memory_file(settings)，不要自己拼（换版本才对得上）。
"""
import json
import os
import random
import shutil
import threading
import time
from pathlib import Path

from . import ai_config

TEXT_KEYS = ("text", "content", "summary", "fact", "value")

# 记忆库的「读 → 改 → 原子写」必须整体串行：并发删不同 index 会互相覆盖，
# 10 条删除最后只落地 1 条。无头端控制台是多线程的（FastAPI 线程池），
# 桌面端现在是单线程 —— 锁放在共用的 core 里，两端都被保护。
_LOCK = threading.Lock()


def memory_path(settings) -> Path:
    return ai_config.memory_file(settings)


def item_text(item) -> str:
    """把一条记忆压成一行文本（结构不固定）。"""
    if isinstance(item, str):
        return item.strip()
    if isinstance(item, dict):
        for key in TEXT_KEYS:
            if item.get(key):
                return str(item[key]).strip()
        return json.dumps(item, ensure_ascii=False)[:300]
    return str(item)


def load(settings) -> dict:
    """读记忆库；解析失败抛 ValueError（绝不静默当空，避免下次保存覆盖）。"""
    path = memory_path(settings)
    if not path.exists():
        return {"global": [], "users": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise ValueError(f"记忆库文件解析失败（{exc}）：{path}。"
                         "请先修好或改名，避免保存时把它覆盖掉") from exc
    if not isinstance(data, dict):
        raise ValueError("记忆库格式异常（顶层不是 JSON 对象）")
    data.setdefault("global", [])
    data.setdefault("users", {})
    if not isinstance(data["global"], list) or not isinstance(data["users"], dict):
        raise ValueError("记忆库格式异常（global 应为数组、users 应为对象）")
    return data


def summary(settings) -> dict:
    """给界面用的一份概览：总数 + 全局若干条 + 按用户分组。"""
    data = load(settings)
    gl = list(data.get("global") or [])
    groups = []
    for uid, items in (data.get("users") or {}).items():
        lst = list(items or [])
        groups.append({"user": str(uid), "count": len(lst), "items": lst[-50:]})
    groups.sort(key=lambda g: g["count"], reverse=True)
    return {
        "total": len(gl) + sum(g["count"] for g in groups),
        "global_count": len(gl),
        "global": gl[-200:],
        "users": groups,
        "file": str(memory_path(settings)),
    }


def _backup(path: Path) -> str:
    """改动前留一份备份，返回备份路径（失败返回空串，不阻塞本次操作）。"""
    if not path.exists():
        return ""
    target = path.with_name(
        f"{path.name}.bak.{time.strftime('%Y%m%d-%H%M%S')}.{random.randint(0, 0xFFFF):04x}")
    try:
        shutil.copy2(path, target)
        return str(target)
    except OSError:
        return ""


def _save(settings, data: dict) -> str:
    """原子写回，返回备份路径。"""
    path = memory_path(settings)
    backup = _backup(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{random.randint(0, 0xFFFF):04x}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(data, ensure_ascii=False, indent=2))
            fh.flush()
            os.fsync(fh.fileno())      # 断电/强杀时别留半截 JSON
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
    return backup


def export_text(settings, fmt: str = "json") -> tuple:
    """导出记忆库：json = 原始结构；md = 人可读时间线。返回 (文件名, 文本)。"""
    data = load(settings)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    if str(fmt).lower() in ("md", "markdown"):
        lines = ["# 记忆时间线导出", "", f"导出时间：{stamp}", ""]
        gl = list(data.get("global") or [])
        lines.append(f"## 全局记忆（{len(gl)} 条）")
        lines += [f"- {item_text(x)}" for x in gl] or ["- （空）"]
        for uid, items in (data.get("users") or {}).items():
            lst = list(items or [])
            lines += ["", f"## 用户 {uid}（{len(lst)} 条）"]
            lines += [f"- {item_text(x)}" for x in lst] or ["- （空）"]
        return f"memory-{stamp}.md", "\n".join(lines) + "\n"
    return f"memory-{stamp}.json", json.dumps(data, ensure_ascii=False, indent=2)


def delete(settings, scope: str, user: str = "", index: int = 0) -> dict:
    """删一条。scope: global（全局）/ user（指定用户的第 index 条，负数从末尾数）。"""
    with _LOCK:
        return _delete_locked(settings, scope, user, index)


def _delete_locked(settings, scope: str, user: str = "", index: int = 0) -> dict:
    scope = str(scope or "").strip().lower()
    if scope not in ("global", "user"):
        raise ValueError("scope 只能是 global 或 user")
    if not isinstance(index, int) or isinstance(index, bool):
        raise ValueError("index 必须是整数")
    data = load(settings)
    if scope == "global":
        bucket = list(data.get("global") or [])
        target_desc = "全局记忆"
    else:
        uid = str(user or "").strip()
        if not uid:
            raise ValueError("scope=user 时必须提供用户")
        bucket = list((data.get("users") or {}).get(uid) or [])
        target_desc = f"用户 {uid} 的记忆"
    if not bucket:
        raise ValueError(f"{target_desc}是空的")
    pos = index if index >= 0 else len(bucket) + index
    if pos < 0 or pos >= len(bucket):
        raise ValueError(f"{target_desc}没有第 {index} 条")
    removed = bucket.pop(pos)
    if scope == "global":
        data["global"] = bucket
    else:
        data["users"][str(user).strip()] = bucket
    backup = _save(settings, data)
    return {"ok": True, "removed": item_text(removed), "left": len(bucket), "backup": backup}


def clear(settings, scope: str = "global", user: str = "") -> dict:
    """清空：scope=global 清全局；scope=user 清指定用户；scope=all 全清。"""
    with _LOCK:
        return _clear_locked(settings, scope, user)


def _clear_locked(settings, scope: str = "global", user: str = "") -> dict:
    scope = str(scope or "").strip().lower()
    if scope not in ("global", "user", "all"):
        raise ValueError("scope 只能是 global / user / all")
    data = load(settings)
    removed = 0
    if scope in ("global", "all"):
        removed += len(list(data.get("global") or []))
        data["global"] = []
    if scope == "all":
        removed += sum(len(list(v or [])) for v in (data.get("users") or {}).values())
        data["users"] = {}
    elif scope == "user":
        uid = str(user or "").strip()
        if not uid:
            raise ValueError("scope=user 时必须提供用户")
        removed += len(list((data.get("users") or {}).get(uid) or []))
        data.setdefault("users", {})[uid] = []
    backup = _save(settings, data)
    return {"ok": True, "removed": removed, "backup": backup}
