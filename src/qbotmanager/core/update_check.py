# -*- coding: utf-8 -*-
"""版本检测：向许可证服务器查询最新版本，启动/每 2 天自动检查（结果缓存）。"""
import json
import os
import re
import time
import urllib.request
from pathlib import Path

from ..constants import APP_NAME, APP_VERSION
from .license import SERVER_URL, SERVER_URL_FALLBACKS

# 版本接口挂在签发站上：优先 HTTPS（astroswarm.cn/license/version），旧明文地址兜底
UPDATE_URLS = tuple(u.rstrip("/") + "/version" for u in (SERVER_URL,) + tuple(SERVER_URL_FALLBACKS))
UPDATE_URL = UPDATE_URLS[0]          # 兼容旧引用
CHECK_INTERVAL = 2 * 86400  # 2 天
TIMEOUT = 8

_state_cache = None


def _state_file() -> Path:
    base = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))) / APP_NAME
    try:
        base.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return base / "update_check.json"


def read_state() -> dict:
    """mtime 缓存读取检查状态（设置页 2 秒刷新热路径）。"""
    global _state_cache
    p = _state_file()
    try:
        st = p.stat()
        key = (st.st_mtime_ns, st.st_size)
    except OSError:
        return {}
    if _state_cache is not None and _state_cache[0] == key:
        return _state_cache[1]
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        data = data if isinstance(data, dict) else {}
    except (ValueError, OSError):
        data = {}
    _state_cache = (key, data)
    return data


def _write_state(data: dict):
    try:
        _state_file().write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def _parse(v) -> tuple:
    return tuple(int(x) for x in re.split(r"[^0-9]+", str(v or "")) if x.isdigit()) or (0,)


def newer_available(current: str, latest: str) -> bool:
    return bool(latest) and _parse(latest) > _parse(current)


def check(force: bool = False) -> dict:
    """检查更新。结果写入状态文件；未到间隔且非强制时直接返回缓存。"""
    now = time.time()
    state = read_state()
    out = {
        "ok": False, "current": APP_VERSION, "latest": "",
        "url": "", "notes": "", "newer": False, "cached": False,
        "checked_at": 0, "error": "",
    }
    if state.get("checked_at"):
        out["checked_at"] = float(state["checked_at"])
    if not force and state.get("last_check") and (now - float(state["last_check"])) < CHECK_INTERVAL:
        out.update({
            "ok": True, "cached": True, "latest": state.get("latest", ""),
            "url": state.get("url", ""), "notes": state.get("notes", ""),
            "newer": newer_available(APP_VERSION, state.get("latest", "")),
        })
        return out
    data = None
    err = ""
    for url in UPDATE_URLS:            # HTTPS 优先，旧明文地址兜底
        try:
            req = urllib.request.Request(url, headers={"User-Agent": f"AstroSwarm/{APP_VERSION}"})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                data = json.loads(resp.read().decode("utf-8", "replace"))
            break
        except Exception as e:  # noqa: BLE001
            err = str(e)
    if not isinstance(data, dict):
        out["error"] = err or "版本接口无响应"
        return out
    latest = str(data.get("version") or "").strip()
    new_state = {
        "last_check": now, "checked_at": now,
        "latest": latest, "url": str(data.get("url") or ""),
        "notes": str(data.get("notes") or ""),
    }
    _write_state(new_state)
    out.update({
        "ok": True, "latest": latest, "url": new_state["url"],
        "notes": new_state["notes"], "checked_at": now,
        "newer": newer_available(APP_VERSION, latest),
    })
    return out
