from PySide6.QtCore import QThread, Signal

from ..core.installer import deploy_all
from ..core.plugins import extract_zip_plugin, install_store_plugin
from ..core.python_runtime import DependencyInstallError, install_with_fallback


class DeployWorker(QThread):
    progress = Signal(int, int, str)
    log = Signal(str)
    ok = Signal(dict)
    fail = Signal(str)

    def __init__(self, settings):
        super().__init__()
        self.settings = settings

    def run(self):
        try:
            result = deploy_all(self.settings, progress=self._progress, log=self.log.emit)
            self.ok.emit(result)
        except Exception as e:  # noqa: BLE001
            self.fail.emit(str(e))

    def _progress(self, done, total, label):
        self.progress.emit(done, total, label)


class InstallPluginWorker(QThread):
    log = Signal(str)
    progress = Signal(int)
    ok = Signal(str)
    fail = Signal(str)

    def __init__(self, settings, kind, payload, deps=None):
        super().__init__()
        self.settings = settings
        self.kind = kind          # "store" | "zip" | "deps"
        self.payload = payload
        self.deps = deps or []

    def run(self):
        try:
            self.progress.emit(-1)
            if self.kind == "store":
                install_store_plugin(self.settings, self.payload,
                                     log=self.log.emit, progress=self.progress.emit)
                self.ok.emit("已安装商店插件: " + self.payload)
            elif self.kind == "zip":
                p = extract_zip_plugin(self.settings, self.payload, log=self.log.emit)
                if self.deps:
                    self.log.emit("检测到插件依赖，开始安装: " + ", ".join(self.deps))
                    install_with_fallback(self.settings, self.deps,
                                          log=self.log.emit, progress=self.progress.emit)
                    self.log.emit("插件依赖安装完成")
                self.progress.emit(100)
                self.ok.emit("已解压插件: " + str(p))
            else:  # deps（重装缺失依赖）
                install_with_fallback(self.settings, self.payload,
                                      log=self.log.emit, progress=self.progress.emit)
                self.progress.emit(100)
                self.ok.emit("依赖安装完成: " + ", ".join(self.payload))
        except DependencyInstallError as e:
            reason_txt = "网络连接问题" if e.reason == "network" else "其他错误（非网络）"
            tip = (
                "依赖安装失败：\n\n"
                "未能安装: " + ", ".join(e.packages) + "\n"
                "失败原因: " + reason_txt + "\n\n"
                "建议：开启代理（VPN）后，在插件页选中该插件点「重装缺失依赖」重新安装。"
            )
            self.fail.emit(tip)
        except Exception as e:  # noqa: BLE001
            self.fail.emit(str(e))


class StartStopWorker(QThread):
    """在后台线程启动/停止 NoneBot，避免界面卡顿。"""
    done = Signal(str)
    fail = Signal(str)

    def __init__(self, manager, start: bool):
        super().__init__()
        self.manager = manager
        self.do_start = start

    def run(self):
        try:
            if self.do_start:
                self.manager.start_all()
                self.done.emit("已启动")
            else:
                self.manager.stop_all()
                self.done.emit("已停止")
        except Exception as e:  # noqa: BLE001
            self.fail.emit(str(e))


class RestartBotWorker(QThread):
    """后台重启 NoneBot（安装插件后生效用）。"""
    done = Signal(str)
    fail = Signal(str)

    def __init__(self, manager):
        super().__init__()
        self.manager = manager

    def run(self):
        try:
            self.manager.restart_bot()
            self.done.emit("NoneBot 已重启")
        except Exception as e:  # noqa: BLE001
            self.fail.emit(str(e))
