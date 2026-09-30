# -*- coding: utf-8 -*-
"""离线载荷定位：安装包内置的 Python / Node / wheels / dsh 都放在安装目录的 offline\\ 下。

查找顺序：环境变量 QBM_OFFLINE_DIR -> exe 同级的 offline -> 仓库根的 offline（开发态）。
任何异常都吞掉返回 None：找不到就走原有联网下载逻辑。
"""
import os
import sys
from pathlib import Path


def _first_dir(candidates):
    for d in candidates:
        try:
            if d is not None and Path(d).is_dir():
                return Path(d)
        except (OSError, TypeError, ValueError):
            continue
    return None


def offline_dir() -> Path | None:
    """安装包内置载荷目录；不存在返回 None。"""
    cands = []
    env = (os.environ.get("QBM_OFFLINE_DIR") or "").strip()
    if env:
        cands.append(Path(env))
    try:
        cands.append(Path(sys.executable).resolve().parent / "offline")
    except OSError:
        pass
    cands.append(Path(__file__).resolve().parents[3] / "offline")
    return _first_dir(cands)


def _first_file(patterns):
    d = offline_dir()
    if not d:
        return None
    try:
        for pat in patterns:
            hits = sorted(d.glob(pat))
            for h in hits:
                if h.is_file():
                    return h
    except OSError:
        pass
    return None


def python_zip() -> Path | None:
    return _first_file(("python-*-embed-amd64.zip",))


def node_zip() -> Path | None:
    return _first_file(("node-*-win-x64.zip",))


def wheels_dir() -> Path | None:
    d = offline_dir()
    if not d:
        return None
    w = d / "wheels"
    try:
        if w.is_dir() and any(w.glob("*.whl")):
            return w
    except OSError:
        pass
    return None


def dsh_payload() -> Path | None:
    return _first_file((os.path.join("dsh", "payload.tar.gz"),))


def notices_file() -> Path | None:
    return _first_file(("THIRD_PARTY_NOTICES.txt",))
