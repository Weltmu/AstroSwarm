# -*- coding: utf-8 -*-
"""独立卸载器核心逻辑（无 GUI 依赖，供 uninstall.exe 调用）。"""
import json
import os
import subprocess
import sys
from pathlib import Path

from . import license as lic_mod
from ..constants import POINTER_DIR, POINTER_FILE
from .settings import Settings
from .uninstall import force_delete


def find_install_root() -> Path | None:
    """通过启动记录定位已部署的机器人安装目录。"""
    try:
        if POINTER_FILE.exists():
            data = json.loads(POINTER_FILE.read_text(encoding="utf-8"))
            root = Path(data.get("root", "")).expanduser()
            if root.is_dir() and (root / "settings.json").exists():
                return root
    except Exception:  # noqa: BLE001
        pass
    return None


def find_program_dir() -> Path | None:
    """定位程序文件夹（uninstall.exe 与主程序同目录时；兼容新旧 exe 名）。"""
    if getattr(sys, "frozen", False):
        d = Path(sys.executable).resolve().parent
        if (d / "AstroSwarm.exe").exists() or (d / "QBotManager.exe").exists():
            return d
    return None


def stop_qbotmanager_processes(log=None) -> list:
    """关闭正在运行的主程序（AstroSwarm.exe / 旧 QBotManager.exe，避免程序文件夹被占用）。"""
    log = log or (lambda x: None)
    killed = []
    try:
        ps = (
            "Get-CimInstance Win32_Process -Filter \"Name='AstroSwarm.exe' Or Name='QBotManager.exe'\" | "
            "Select-Object -ExpandProperty ProcessId"
        )
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True, text=True, timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        for line in (r.stdout or "").split():
            if line.strip().isdigit():
                pid = int(line.strip())
                subprocess.run(
                    # /T 结束整棵进程树：PyInstaller onefile 有父/子两个
                    # 主程序，只杀父进程会让子进程残留并锁住程序文件夹
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    capture_output=True, timeout=10,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                killed.append(pid)
                log(f"已关闭主程序进程 (PID {pid})")
    except Exception as e:  # noqa: BLE001
        log("关闭主程序进程失败: " + str(e))
    return killed


def stop_services(root: Path, log=None, on_stage=None):
    """停止 NoneBot 服务。"""
    log = log or (lambda x: None)
    try:
        settings = Settings.load(root)
        from .manager import Manager
        m = Manager(settings)
        m.stop_all(on_stage=on_stage)
        log("机器人服务已全部停止")
    except Exception as e:  # noqa: BLE001
        log("停止服务时提示: " + str(e))


def schedule_remove_folder(folder: Path, log=None) -> bool:
    """进程退出后延迟删除程序文件夹（cmd 在临时目录等待 2 秒再 rmdir）。"""
    log = log or (lambda x: None)
    folder = folder.resolve()
    tmp = Path(os.environ.get("TEMP", str(Path.home())))
    cmd = f'timeout /t 2 /nobreak >nul & rmdir /s /q "{folder}"'
    try:
        subprocess.Popen(
            ["cmd", "/c", cmd],
            cwd=str(tmp),
            creationflags=subprocess.CREATE_NO_WINDOW | 0x00000008,
            close_fds=True,
        )
        log("已安排删除程序文件夹: " + str(folder))
        return True
    except Exception as e:  # noqa: BLE001
        log("安排删除程序文件夹失败: " + str(e))
        return False


def collect_info(root_override: str | None = None) -> dict:
    """收集卸载信息（供 GUI/检查模式展示）。"""
    root = Path(root_override) if root_override else find_install_root()
    return {
        "install_root": str(root) if root and root.is_dir() else "",
        "program_dir": str(find_program_dir()) if find_program_dir() else "",
        "license_exists": lic_mod.license_file().exists(),
    }


def run_uninstall(clear_activation: bool = False, log=None, on_stage=None,
                  root_override: str | None = None, remove_program: bool = True) -> dict:
    """执行完整卸载。

    顺序：关闭主程序进程 -> 停止服务 -> 删除安装目录 -> 清除启动记录
          -> （可选）清除登录与授权状态 -> 安排删除程序文件夹。
    """
    log = log or (lambda x: None)
    root = Path(root_override) if root_override else find_install_root()

    # 1) 关闭正在运行的程序
    stop_qbotmanager_processes(log=log)

    # 2) 停止机器人服务
    if root and root.is_dir():
        if on_stage:
            on_stage("正在停止服务")
        stop_services(root, log=log, on_stage=on_stage)
    else:
        log("未检测到已部署的机器人（跳过服务停止）")

    # 3) 删除安装目录
    if root and root.is_dir():
        if on_stage:
            on_stage("正在删除安装目录")
        force_delete(root)
        log("已删除安装目录: " + str(root))
    else:
        log("未检测到安装目录（跳过）")

    # 4) 清除启动记录
    try:
        if POINTER_FILE.exists():
            POINTER_FILE.unlink()
        if POINTER_DIR.exists() and not any(POINTER_DIR.iterdir()):
            POINTER_DIR.rmdir()
        log("已清除启动记录")
    except Exception as e:  # noqa: BLE001
        log("清除启动记录失败: " + str(e))

    # 5) 登录与授权状态
    if clear_activation:
        lic_mod.clear_license()
        log("已清除登录与授权状态（下次使用需重新登录）")
    else:
        log("已保留登录与授权状态（下次安装无需重新登录）")

    # 6) 程序文件夹（含主程序与 uninstall.exe 自身）
    if remove_program:
        prog = find_program_dir()
        if prog is not None and prog.is_dir():
            if on_stage:
                on_stage("正在删除程序文件夹")
            schedule_remove_folder(prog, log=log)
        else:
            log("未检测到随附的主程序（独立运行模式，请手动删除本程序）")

    return {"ok": True, "install_root": str(root) if root else ""}
