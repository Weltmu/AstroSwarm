# -*- coding: utf-8 -*-
"""随安装包分发的第三方组件清单（合规用）。

只列「随包内置」的组件，全部为宽松许可（MIT / Apache-2.0 / BSD / PSF / ISC）；
完整许可原文由构建脚本汇总到安装目录 offline/THIRD_PARTY_NOTICES.txt。

明确不内置（合规红线，剪裁清单见 tools/build_offline_bundle.py）：
  - @tencent-connect/qqbot-connector（UNLICENSED 专有包，不内置、不调用）
  - @deepseek-ai/libreoffice-kit*（MPL-2.0，机器人用不到）
  - @img/sharp*（含 LGPL-3.0-or-later，机器人用不到）
"""
import os
import subprocess
import sys
from pathlib import Path

# (组件, 版本, 许可, 主页)
BUNDLED_COMPONENTS = (
    ("Python（内置运行时）", "3.12.10", "PSF-2.0", "https://www.python.org/"),
    ("Node.js（内置便携版）", "22.23.2", "MIT", "https://nodejs.org/"),
    ("DeepSeek Harness · dsh", "0.2.0-rc.2", "MIT", "https://github.com/deepseek-ai/deepseek-harness"),
    ("@tencent-connect/dsh-qqbot", "0.5.0", "MIT", "https://github.com/tencent-connect/dsh-qqbot"),
    ("NoneBot2", "2.5.0", "MIT", "https://github.com/nonebot/nonebot2"),
    ("nonebot-adapter-qq", "1.7.3", "MIT", "https://github.com/nonebot/adapter-qq"),
    ("nonebot-plugin-localstore", "0.7.4", "MIT", "https://github.com/nonebot/plugin-localstore"),
    ("nonebot-plugin-apscheduler", "0.5.0", "MIT", "https://github.com/nonebot/plugin-apscheduler"),
    ("openai（Python SDK）", "3.22.1", "Apache-2.0", "https://github.com/openai/openai-python"),
    ("mcp（Python SDK）", "2.2.0", "MIT", "https://github.com/modelcontextprotocol/python-sdk"),
    ("PyJWT", "2.15.1", "MIT", "https://github.com/jpadilla/pyjwt"),
    ("cryptography", "48.0.1", "Apache-2.0 OR BSD-3-Clause", "https://github.com/pyca/cryptography"),
    ("tzdata", "2026.4", "Apache-2.0", "https://github.com/python/tzdata"),
)


def notices_file() -> Path | None:
    """安装目录里的完整许可文本；找不到返回 None。"""
    candidates = []
    env = os.environ.get("QBM_OFFLINE_DIR")
    if env:
        candidates.append(Path(env))
    try:
        candidates.append(Path(sys.executable).resolve().parent / "offline")
    except OSError:
        pass
    candidates.append(Path(__file__).resolve().parents[3] / "offline")
    for d in candidates:
        try:
            p = d / "THIRD_PARTY_NOTICES.txt"
            if p.is_file():
                return p
        except OSError:
            continue
    return None


def open_notices() -> bool:
    """用系统默认程序打开完整许可文本；成功返回 True。"""
    p = notices_file()
    if not p:
        return False
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(p))
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(p)])
        else:
            subprocess.Popen(["xdg-open", str(p)])
        return True
    except OSError:
        return False
