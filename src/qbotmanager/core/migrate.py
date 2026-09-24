# -*- coding: utf-8 -*-
"""旧版本沿用/导入：自动发现并关联已有安装根，配置、插件、登录信息原地保留。"""
import json
import sys
from pathlib import Path

from ..constants import POINTER_DIR, POINTER_FILE
from .settings import RECENT_FILE, Settings


def _add(cands: list, p) -> None:
    if p and p.is_dir():
        p = Path(p).resolve()
        if p not in cands:
            cands.append(p)


def candidate_roots() -> list:
    """候选旧安装根：指针、最近记录、exe 附近、桌面/下载里的分发目录。"""
    cands = []
    if POINTER_FILE.exists():
        try:
            _add(cands, Path(json.loads(POINTER_FILE.read_text(encoding="utf-8")).get("root", "")))
        except Exception:  # noqa: BLE001
            pass
    if RECENT_FILE.exists():
        try:
            for item in json.loads(RECENT_FILE.read_text(encoding="utf-8")):
                _add(cands, Path(str(item)))
        except Exception:  # noqa: BLE001
            pass
    exe = Path(sys.executable).resolve()
    _add(cands, exe.parent)
    _add(cands, exe.parent.parent)
    for base in (Path.home() / "Desktop", Path.home() / "Downloads"):
        if base.is_dir():
            for sub in sorted(base.iterdir()):
                if sub.is_dir() and sub.name.startswith("QBotManager"):
                    _add(cands, sub)
                    _add(cands, sub / "QBotManager_客户版")
                if sub.is_dir() and sub.name.startswith("AstroSwarm"):
                    _add(cands, sub)
                    _add(cands, sub / "AstroSwarm_客户版")
    return cands


def is_install_root(p) -> bool:
    try:
        return (Path(p) / "settings.json").is_file()
    except OSError:
        return False


def is_deployed_root(p) -> bool:
    try:
        return Settings.load(p).is_deployed()
    except Exception:  # noqa: BLE001
        return False


def adopt_root(p) -> bool:
    """把安装根指针指向 p（沿用旧安装，不复制任何数据）。"""
    p = Path(p)
    if not is_install_root(p):
        return False
    try:
        POINTER_DIR.mkdir(parents=True, exist_ok=True)
        POINTER_FILE.write_text(json.dumps({"root": str(p)}, ensure_ascii=False), encoding="utf-8")
        return True
    except OSError:
        return False


def try_adopt_candidate(exclude=None):
    """自动沿用第一个完整的旧安装根（排除 exclude）。成功返回该根，否则 None。"""
    excl = Path(exclude).resolve() if exclude else None
    for p in candidate_roots():
        if excl is not None and p == excl:
            continue
        if is_install_root(p) and is_deployed_root(p):
            if adopt_root(p):
                return p
    return None
