# -*- coding: utf-8 -*-
"""AstroSwarm 自动卸载：停止服务由调用方完成，这里删除整个安装根目录与启动指针。

删除范围：安装向导选择的整个安装路径（bot / python / 配置 / 日志等全部）。
登录与授权状态（APPDATA 下的 license.json）保留，重装无需重新登录。
"""
import os
import shutil
import stat
import subprocess
import time
from pathlib import Path

from ..constants import POINTER_DIR, POINTER_FILE


def force_delete(path) -> bool:
    """递归删除，自动处理只读属性与 ACL 限制。"""
    path = Path(path)
    if not path.exists():
        return True
    try:
        if path.is_symlink() or path.is_file():
            try:
                path.unlink()
                return not path.exists()
            except OSError:
                pass
    except OSError:
        pass

    # 1) 解除只读属性
    for root, dirs, files in os.walk(path, topdown=False):
        for name in list(dirs) + list(files):
            p = os.path.join(root, name)
            try:
                os.chmod(p, stat.S_IWRITE | stat.S_IREAD)
            except OSError:
                pass

    # 2) 授权（解决安装目录 ACL 拒绝删除的问题）
    try:
        subprocess.run(
            ["icacls", str(path), "/grant", "*S-1-1-0:(OI)(CI)F", "/T", "/Q"],
            capture_output=True, timeout=120,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception:  # noqa: BLE001
        pass

    # 3) 多轮重试删除
    for _ in range(3):
        try:
            shutil.rmtree(path)
            return not path.exists()
        except OSError:
            time.sleep(0.5)

    # 4) 最后一轮逐项删除
    for root, dirs, files in os.walk(path, topdown=False):
        for name in files:
            try:
                os.remove(os.path.join(root, name))
            except OSError:
                pass
        for name in dirs:
            try:
                os.rmdir(os.path.join(root, name))
            except OSError:
                pass
    try:
        path.rmdir()
    except OSError:
        pass
    return not path.exists()


def uninstall_deployment(settings, log=None):
    """删除整个安装根目录与指针文件。登录与授权状态（APPDATA 下的 license.json）保留。"""
    root = Path(settings.root)
    if log:
        log("正在删除安装目录: " + str(root))
    force_delete(root)

    # 清除启动指针（下次启动会重新进入部署向导）
    try:
        if POINTER_FILE.exists():
            POINTER_FILE.unlink()
    except OSError:
        pass
    try:
        if POINTER_DIR.exists() and not any(POINTER_DIR.iterdir()):
            POINTER_DIR.rmdir()
    except OSError:
        pass

    if log:
        log("卸载完成，安装目录与启动记录已清除")
    return True
