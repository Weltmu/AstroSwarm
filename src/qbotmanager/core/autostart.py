# -*- coding: utf-8 -*-
"""Windows 开机自启动（当前用户注册表 Run 键）。"""
import sys
from pathlib import Path

try:
    import winreg
except ImportError:  # 非 Windows 环境
    winreg = None

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "AstroSwarm"


def exe_path() -> str:
    """返回要注册的自启动命令（打包版=exe；开发模式=pythonw + 入口）。"""
    if getattr(sys, "frozen", False):
        return f'"{Path(sys.executable)}"'
    pyw = Path(sys.executable).with_name("pythonw.exe")
    main = Path(__file__).resolve().parents[2] / "main.py"
    if pyw.exists():
        return f'"{pyw}" "{main}"'
    return f'"{Path(sys.executable)}" "{main}"'


def set_enabled(enabled: bool) -> bool:
    """写入/删除 HKCU 自启动项；成功返回 True。"""
    if winreg is None:
        return False
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            if enabled:
                winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, exe_path())
            else:
                try:
                    winreg.DeleteValue(key, VALUE_NAME)
                except FileNotFoundError:
                    pass
        return True
    except OSError:
        return False


def is_enabled() -> bool:
    """查询当前是否已设置自启动。"""
    if winreg is None:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, VALUE_NAME)
        return True
    except OSError:
        return False
