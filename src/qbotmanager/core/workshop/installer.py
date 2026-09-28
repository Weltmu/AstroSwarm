# -*- coding: utf-8 -*-
"""工坊插件安装：版本历史 / 一键回滚 / 一键卸载（补上"没有版本"的短板）。

目录约定（都在机器人根目录下，Linux 无头端同一套）：
  tool_packs/<id>/              已安装的插件（机器人启动时加载）
  workshop/history/<id>/<时间>/ 历史版本（回滚用，最多留 5 个）
  workshop/<id>.json            这个插件是谁生成的、用什么需求生成的
"""
import json
import re
import shutil
import time
from pathlib import Path

_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{1,31}$")
MAX_HISTORY = 5


class InstallError(RuntimeError):
    """安装失败（大白话说明）。"""


def packs_root(settings) -> Path:
    return Path(settings.root) / "tool_packs"


def workshop_root(settings) -> Path:
    return Path(settings.root) / "workshop"


def history_root(settings, pid: str) -> Path:
    return workshop_root(settings) / "history" / pid


def meta_file(settings, pid: str) -> Path:
    return workshop_root(settings) / f"{pid}.json"


def existing_ids(settings) -> set:
    root = packs_root(settings)
    if not root.exists():
        return set()
    return {p.name for p in root.iterdir() if p.is_dir()}


def unique_id(settings, pid: str) -> str:
    """重名自动加后缀（-2 / -3 …）。"""
    pid = str(pid or "").strip().lower()
    if not _ID_RE.match(pid):
        pid = "ai_pack"
    taken = existing_ids(settings)
    if pid not in taken:
        return pid
    for i in range(2, 100):
        cand = f"{pid}-{i}"
        if cand not in taken:
            return cand
    raise InstallError("同名插件太多了，换个名字吧。")


def _write_files(target: Path, files: dict) -> None:
    for rel, content in files.items():
        rel = str(rel).replace("\\", "/").lstrip("/")
        if not rel or ".." in rel.split("/"):
            raise InstallError(f"文件名不合法：{rel}")
        path = target / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(content), encoding="utf-8")


def install(settings, pid: str, files: dict, meta: dict | None = None) -> dict:
    """装一个工坊生成的插件；已装过的话旧版本先进历史（可回滚）。"""
    pid = str(pid or "").strip().lower()
    if not _ID_RE.match(pid):
        raise InstallError("插件 id 不合法（小写字母开头，字母/数字/中划线）。")
    if not isinstance(files, dict) or "manifest.json" not in files:
        raise InstallError("插件文件不完整（缺 manifest.json）。")
    root = packs_root(settings)
    target = root / pid
    staging = workshop_root(settings) / "staging" / f"{pid}-{int(time.time())}"
    if staging.exists():
        shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=True)
    _write_files(staging, files)
    backup = ""
    root.mkdir(parents=True, exist_ok=True)
    if target.exists():
        stamp = time.strftime("%Y%m%d-%H%M%S")
        dest = history_root(settings, pid) / stamp
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        shutil.move(str(target), str(dest))
        backup = str(dest)
        _prune_history(settings, pid)
    shutil.move(str(staging), str(target))
    shutil.rmtree(staging.parent, ignore_errors=True)
    payload = {
        "id": pid,
        "source": "workshop",
        "installed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "backup": backup,
    }
    payload.update({k: v for k, v in (meta or {}).items() if k != "id"})
    try:
        meta_file(settings, pid).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:  # noqa: BLE001 —— 元信息写失败不影响插件本身
        pass
    return {"ok": True, "id": pid, "dir": str(target), "backup": backup}


def _prune_history(settings, pid: str) -> None:
    root = history_root(settings, pid)
    if not root.exists():
        return
    items = sorted([p for p in root.iterdir() if p.is_dir()],
                   key=lambda p: p.name, reverse=True)
    for old in items[MAX_HISTORY:]:
        shutil.rmtree(old, ignore_errors=True)


def history(settings, pid: str) -> list:
    root = history_root(settings, pid)
    if not root.exists():
        return []
    items = sorted([p for p in root.iterdir() if p.is_dir()],
                   key=lambda p: p.name, reverse=True)
    return [{"stamp": p.name, "dir": str(p)} for p in items]


def rollback(settings, pid: str) -> dict:
    """回滚到上一个版本（当前版本也会进历史，方便再换回来）。"""
    items = history(settings, pid)
    if not items:
        raise InstallError("这个插件没有可回滚的历史版本。")
    src = Path(items[0]["dir"])
    target = packs_root(settings) / pid
    stamp = time.strftime("%Y%m%d-%H%M%S") + "-rollback"
    if target.exists():
        dest = history_root(settings, pid) / stamp
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(target), str(dest))
    shutil.move(str(src), str(target))
    return {"ok": True, "id": pid, "from": items[0]["stamp"],
            "dir": str(target)}


def uninstall(settings, pid: str) -> dict:
    """卸载（当前版本先进历史，万一还要装回来）。"""
    target = packs_root(settings) / pid
    if not target.exists():
        raise InstallError("这个插件没装（或已经被删掉了）。")
    stamp = time.strftime("%Y%m%d-%H%M%S") + "-uninstall"
    dest = history_root(settings, pid) / stamp
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(target), str(dest))
    return {"ok": True, "id": pid, "archive": str(dest)}


def generated(settings) -> list:
    """列出 AI 工坊生成的插件（读过 workshop/<id>.json 且当前装着）。"""
    root = packs_root(settings)
    out = []
    if not root.exists():
        return out
    for pack in sorted(root.iterdir()):
        if not pack.is_dir():
            continue
        info = {}
        try:
            info = json.loads(meta_file(settings, pack.name).read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            info = {}
        manifest = {}
        try:
            manifest = json.loads((pack / "manifest.json").read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            manifest = {}
        if not info and not manifest:
            continue
        out.append({
            "id": pack.name,
            "name": manifest.get("name") or info.get("name") or pack.name,
            "version": manifest.get("version") or "",
            "adapters": manifest.get("adapters") or [],
            "tools": [t.get("name") for t in (manifest.get("tools") or [])],
            "ai_generated": bool(info.get("source") == "workshop"),
            "installed_at": info.get("installed_at") or "",
            "model": info.get("model") or "",
            "need": str(info.get("need") or "")[:120],
            "history": len(history(settings, pack.name)),
        })
    return out
