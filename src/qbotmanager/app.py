import json
import getpass
import os
import sys
import ctypes
import threading
from ctypes import wintypes

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from .core import migrate as migrate_mod
from .core import process as process_mod
from .core import cleanup as cleanup_mod
from .core.settings import Settings
from .tasks.task_manager import TaskManager
from .ui.main_window import MainWindow
from .ui import press_scale as _press_scale  # noqa: F401  # 全局按钮按压缩放反馈
from .ui.theme import build_qss
from .ui.wizard import DeployWizard


def _selftest(out_path: str) -> int:
    """打包后自检：写入 JSON 结果文件后退出。"""
    results = {"ok": False}
    try:
        from .core.ports import is_port_free
        results["imports"] = "ok"
        results["default_port_free"] = is_port_free(12111)
        results["ok"] = results["imports"] == "ok"
    except Exception as e:  # noqa: BLE001
        results["error"] = repr(e)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    return 0 if results["ok"] else 1


def _enable_dpi_aware():
    """强制 Per-Monitor DPI Aware，避免打包版点击坐标偏移导致按钮失灵。"""
    try:
        import ctypes
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except Exception:  # noqa: BLE001
        pass


ERROR_ALREADY_EXISTS = 183


def _single_instance(app, name: str | None = None) -> bool:
    """Windows 命名互斥体单实例：成功返回 True；已有实例返回 False。"""
    # 互斥体前缀保持旧名：升级过渡期与老版本互相排斥，避免双开抢同一安装目录
    name = name or ("QBotManager-" + getpass.getuser())
    kernel32 = ctypes.windll.kernel32
    kernel32.SetLastError(0)  # 清除残留错误码，避免误判已有实例
    handle = kernel32.CreateMutexW(None, False, name)
    if not handle:
        return True  # 创建失败不阻塞启动，避免误伤
    if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        return False
    app._qbm_single_mutex = handle  # 进程生命周期内保持句柄
    return True


def _activate_existing_window():
    """把已运行实例的主窗口恢复到前台（找不到就静默）。"""
    try:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        current_pid = kernel32.GetCurrentProcessId()
        found = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def _enum_cb(hwnd, _lparam):
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value == current_pid:
                return True
            if "AstroSwarm" in buf.value or "QBotManager" in buf.value:
                found.append(hwnd)
                return False
            return True

        user32.EnumWindows(_enum_cb, 0)
        if found:
            hwnd = found[0]
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            user32.SetForegroundWindow(hwnd)
    except Exception:  # noqa: BLE001
        pass


def run_gui():
    _enable_dpi_aware()
    # 视频后端：优先 FFmpeg（D3D11VA 硬解 + RHI 纹理直通），
    # Windows Media Foundation 在 QQuickWidget 下常走 CPU 回读转换。
    os.environ.setdefault("QT_MEDIA_BACKEND", "ffmpeg")
    os.environ.setdefault("QSG_RHI_BACKEND", "d3d11")
    # 高分屏：125%/150% 等小数缩放不四舍五入成整数倍，避免文字被二次缩放发糊
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    # 退出作业：程序退出/崩溃时由 Windows 兜底终止全部子进程，杜绝残留
    process_mod.install_exit_job()
    app = QApplication(sys.argv)
    app.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app.setStyleSheet(build_qss())
    app.setApplicationName("AstroSwarm")
    app.setOrganizationName("AstroSwarm")

    if not _single_instance(app):
        _activate_existing_window()
        QMessageBox.information(
            None, "AstroSwarm 星群",
            "AstroSwarm 已在运行，已切换到已有窗口。")
        return 0

    root = Settings.find_root()
    if root is None:
        # 自动沿用旧版本安装（配置/插件/登录原地保留，不复制）
        root = migrate_mod.try_adopt_candidate()
    if root is None:
        wizard = DeployWizard()
        if wizard.exec() != QDialog.Accepted:
            return 0
        settings = wizard.settings
    else:
        settings = Settings.load(root)
        if not settings.is_deployed():
            # 半部署：优先沿用候选里的完整旧安装；没有才进向导补齐
            adopted = migrate_mod.try_adopt_candidate(exclude=str(root))
            if adopted is not None:
                settings = Settings.load(adopted)
            else:
                wizard = DeployWizard(root=root)
                if wizard.exec() != QDialog.Accepted:
                    return 0
                settings = wizard.settings

    # 启动时后台清理日志/临时文件/消息缓存/过期会话，不阻塞主界面
    threading.Thread(
        target=lambda: cleanup_mod.run(settings),
        daemon=True,
    ).start()

    tasks = TaskManager()
    win = MainWindow(settings, tasks)
    win.show()
    return app.exec()


def main():
    argv = sys.argv
    if len(argv) > 1 and argv[1] == "--cli":
        from .core.cli import main as cli_main
        sys.exit(cli_main(argv[2:]))
    if len(argv) > 2 and argv[1] == "--selftest":
        sys.exit(_selftest(argv[2]))
    sys.exit(run_gui())


if __name__ == "__main__":
    main()
