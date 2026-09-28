"""统一任务 Worker：所有后台耗时操作都通过 TaskWorker 基类向 UI 汇报状态。"""
import threading

from .qtcompat import QThread, Signal

from ..core.installer import deploy_all
from ..core import dsh as dsh_mod
from ..core.plugins import (
    detect_dependencies_from_dir,
    detect_dependencies_from_zip,
    extract_zip_plugin,
    install_store_plugin,
    missing_dependencies,
)
from ..core.python_runtime import DependencyInstallError, install_with_fallback
from ..core.uninstall import uninstall_deployment
from .task import TaskCancelled, TaskStatus


class TaskWorker(QThread):
    """统一 Worker 基类：一个任务 = 一次 run()，通过 ctx_* 方法汇报状态。

    子类只需实现 _run() 并返回结果 dict；取消通过 cancel()（协作式）。
    """
    started = Signal(str, str)
    stage_changed = Signal(str, str, int, int, str)
    progress_changed = Signal(str, int)
    log = Signal(str, str, str)
    status_changed = Signal(str, str)
    error = Signal(str, str, str)
    finished = Signal(str, str, dict)

    def __init__(self, task_id, task_name, category, payload=None):
        super().__init__()
        self.task_id = task_id
        self.task_name = task_name
        self.category = category
        self.payload = payload
        self._cancelled = False
        self.cancel_event = threading.Event()
        self._stage = "准备中"

    # ---- 取消 ----
    def cancel(self):
        self._cancelled = True
        self.cancel_event.set()

    def check_cancel(self):
        if self._cancelled:
            raise TaskCancelled("任务已取消")

    # ---- 状态汇报 ----
    def ctx_stage(self, stage, current=0, total=-1, message=""):
        self._stage = stage
        self.stage_changed.emit(self.task_id, stage, int(current), int(total), str(message))

    def ctx_progress(self, pct):
        try:
            pct = int(pct)
        except (TypeError, ValueError):
            pct = -1
        self.progress_changed.emit(self.task_id, max(-1, min(100, pct)))

    def ctx_log(self, level, msg):
        self.log.emit(self.task_id, str(level), str(msg))

    # ---- 执行 ----
    def run(self):
        self.started.emit(self.task_id, self.task_name)
        self.status_changed.emit(self.task_id, TaskStatus.RUNNING.value)
        try:
            result = self._run() or {}
            self.check_cancel()
            self.status_changed.emit(self.task_id, TaskStatus.SUCCESS.value)
            self.finished.emit(self.task_id, TaskStatus.SUCCESS.value, dict(result))
        except TaskCancelled:
            self.ctx_log("WARN", "任务已取消")
            self.status_changed.emit(self.task_id, TaskStatus.CANCELLED.value)
            self.finished.emit(self.task_id, TaskStatus.CANCELLED.value, {})
        except Exception as e:  # noqa: BLE001
            self.ctx_log("ERROR", str(e))
            self.error.emit(self.task_id, self._stage or "执行", str(e))
            self.status_changed.emit(self.task_id, TaskStatus.FAILED.value)
            self.finished.emit(self.task_id, TaskStatus.FAILED.value, {"error": str(e)})

    def _run(self) -> dict:
        raise NotImplementedError


# ---------------------------------------------------------------- 一键部署
class DeployTask(TaskWorker):
    def __init__(self, task_id, task_name, category, payload=None, settings=None):
        super().__init__(task_id, task_name, category, payload)
        self.settings = settings

    def _run(self) -> dict:
        self.ctx_stage("准备部署", 0, 4)

        def step_progress(done, total, label):
            self.ctx_stage(label, done, total)
            if total:
                self.ctx_progress(int(done * 100 / total))

        def dl_progress(*args):
            # 兼容两种进度回调：install_packages 传 int 百分比；下载传 (done, total) 字节
            if len(args) == 1:
                self.ctx_progress(args[0])
            elif len(args) >= 2 and args[1]:
                self.ctx_progress(min(99, int(args[0] * 100 / args[1])))

        def on_line(line):
            line = str(line)
            self.ctx_log("INFO", line)

        result = deploy_all(
            self.settings,
            progress=step_progress,
            log=on_line,
            download_progress=dl_progress,
            cancel_event=self.cancel_event,
        )
        self.check_cancel()
        self.ctx_progress(100)
        self.ctx_log("OK", "部署完成")
        return result


# ---------------------------------------------------------------- 启停/重启/切换
class StartStopTask(TaskWorker):
    def __init__(self, task_id, task_name, category, payload=None, manager=None):
        super().__init__(task_id, task_name, category, payload)
        self.manager = manager

    def _on_stage(self, stage, current=0, total=-1, message=""):
        self.ctx_stage(stage, current, total, message)

    def _run(self) -> dict:
        start = bool((self.payload or {}).get("start"))
        self.ctx_stage("准备" + ("启动" if start else "停止"))
        if start:
            result = self.manager.start_all(
                on_stage=self._on_stage,
                on_progress=lambda done, total: self.ctx_progress(
                    int(done * 100 / total) if total else -1),
                cancel_event=self.cancel_event,
            )
        else:
            result = self.manager.stop_all(on_stage=self._on_stage)
        self.check_cancel()
        self.ctx_progress(100)
        self.ctx_log("OK", "服务已" + ("启动" if start else "停止"))
        return result


class RestartBotTask(TaskWorker):
    def __init__(self, task_id, task_name, category, payload=None, manager=None):
        super().__init__(task_id, task_name, category, payload)
        self.manager = manager

    def _run(self) -> dict:
        self.ctx_progress(20)
        reset_wechat = bool((self.payload or {}).get("reset_wechat"))
        if reset_wechat:
            # 先停旧进程，再清登录态，最后启动：避免旧进程在删除后把
            # token 状态文件写回去，导致重启后直接恢复登录、不出新二维码
            self.ctx_stage("正在停止 NoneBot")
            self.manager.stop_bot()
            self.ctx_stage("正在清除微信登录状态")
            self.manager.reset_wechat_login()
            self.ctx_stage("正在启动 NoneBot")
            self.manager.start_bot(
                on_stage=lambda stage, current=0, total=-1, message="": self.ctx_stage(stage, current, total, message),
                cancel_event=self.cancel_event,
            )
        else:
            self.manager.restart_bot(
                on_stage=lambda stage, current=0, total=-1, message="": self.ctx_stage(stage, current, total, message),
                cancel_event=self.cancel_event,
            )
        self.check_cancel()
        self.ctx_progress(100)
        self.ctx_log("OK", "NoneBot 已重启")
        return {"restarted": True}


class InstallDshTask(TaskWorker):
    """安装/修复 dsh（DeepSeek Harness）QQ 群聊 AI 通道。"""

    def __init__(self, task_id, task_name, category, payload=None, settings=None, manager=None):
        super().__init__(task_id, task_name, category, payload)
        self.settings = settings
        self.manager = manager

    def _run(self) -> dict:
        def on_line(line):
            self.ctx_log("INFO", str(line))

        reinstall = bool((self.payload or {}).get("reinstall"))
        if reinstall:
            self.ctx_stage("正在停止旧 dsh")
            if self.manager is not None:
                try:
                    self.manager.stop_dsh()
                except Exception as e:  # noqa: BLE001
                    self.ctx_log("WARN", "停止旧 dsh 失败（继续重装）: " + str(e))
            self.ctx_stage("正在卸载旧 dsh")
            dsh_mod.uninstall(self.settings, log=on_line)
            self.check_cancel()
        self.ctx_stage("准备安装 dsh")
        dsh_mod.install(
            self.settings,
            log=on_line,
            on_progress=lambda value: self.ctx_progress(value),
            cancel_event=self.cancel_event,
            force=reinstall,
        )
        self.check_cancel()
        self.ctx_progress(100)
        self.ctx_log("OK", "dsh 重装完成" if reinstall else "dsh 安装完成")
        return {"installed": True}


# ---------------------------------------------------------------- 插件/依赖
class InstallPluginTask(TaskWorker):
    """payload: {"kind": "store"|"zip"|"deps", "target": ..., "deps": [...]}"""

    def __init__(self, task_id, task_name, category, payload=None, settings=None):
        super().__init__(task_id, task_name, category, payload)
        self.settings = settings
        self.kind = (payload or {}).get("kind", "store")
        self.target = (payload or {}).get("target", "")
        self.deps = list((payload or {}).get("deps") or [])
        self.module_name = (payload or {}).get("module_name", "") or ""

    def _run(self) -> dict:
        def on_line(line):
            self.ctx_log("INFO", line)

        def on_progress(value):
            self.ctx_progress(value)

        if self.kind == "store":
            self.ctx_stage("正在安装插件", message=self.target)
            install_store_plugin(
                self.settings, self.target,
                log=on_line, progress=on_progress,
                module_name=self.module_name or None,
            )
            self.ctx_progress(100)
            self.ctx_log("OK", "商店插件已安装并启用: " + self.target)
            return {"installed": self.target}

        if self.kind == "zip":
            self.ctx_stage("正在解压插件", message=self.target)
            p = extract_zip_plugin(self.settings, self.target, log=on_line)
            if self.deps:
                self._install_deps(self.deps)
            self.ctx_progress(100)
            self.ctx_log("OK", "zip 插件已解压: " + str(p))
            return {"extracted": str(p)}

        # kind == "deps"
        deps = self.deps or (self.target if isinstance(self.target, (list, tuple)) else [self.target])
        self._install_deps(deps)
        self.ctx_progress(100)
        self.ctx_log("OK", "依赖安装完成")
        return {"deps": list(deps)}

    def _install_deps(self, deps):
        deps = list(deps)
        for i, dep in enumerate(deps, 1):
            self.check_cancel()
            self.ctx_stage("正在安装依赖", i, len(deps), dep)
            try:
                install_with_fallback(
                    self.settings, [dep],
                    log=lambda line: self.ctx_log("INFO", line),
                    progress=lambda value: self.ctx_progress(value),
                    cancel_event=self.cancel_event,
                )
            except DependencyInstallError as e:
                raise RuntimeError(
                    f"依赖安装失败: {', '.join(e.packages)}（{e.reason}）"
                ) from e
        self.ctx_log("OK", f"依赖安装完成（{len(deps)} 项）")


class InstallMarketPluginTask(TaskWorker):
    """官方插件市场安装：下载 → SHA256 校验 → manifest 校验 → 解压。

    payload: {"url": ..., "sha256": ..., "name": ..., "version": ...}
    """

    def __init__(self, task_id, task_name, category, payload=None, settings=None):
        super().__init__(task_id, task_name, category, payload)
        self.settings = settings

    def _run(self) -> dict:
        from ..core import plugin_market
        from ..core.plugins import extract_zip_plugin

        p = self.payload or {}
        url = str(p.get("url") or "")
        name = str(p.get("name") or "plugin")
        version = str(p.get("version") or "latest")
        sha256 = str(p.get("sha256") or "")
        if not url:
            raise RuntimeError("插件下载地址为空")

        dest_dir = self.settings.downloads_dir / "plugins"
        dest = dest_dir / f"{name}-{version}.zip"
        self.ctx_stage("正在下载插件", message=name)
        plugin_market.download_plugin(url, dest, sha256=sha256)
        self.ctx_stage("正在校验插件清单")
        manifest = plugin_market.read_plugin_manifest(dest)
        err = plugin_market.validate_plugin_manifest(manifest)
        if err:
            raise RuntimeError(err)
        self.ctx_stage("正在安装插件", message=name)
        plugin_dir = extract_zip_plugin(
            self.settings, dest, log=lambda line: self.ctx_log("INFO", line))
        dest.unlink(missing_ok=True)  # 安装完成即删除下载缓存
        self.check_cancel()
        self.ctx_progress(100)
        self.ctx_log("OK", f"插件已安装: {name} → {plugin_dir}")
        return {"installed": name, "dir": str(plugin_dir)}


class InstallMarketPackTask(TaskWorker):
    """插件商店能力包安装：下载 → SHA256 → manifest.json 校验 → 安装。

    payload: {"entry": {市场条目}, "url": ..., "sha256": ..., "name": ..., "version": ...}
    """

    def __init__(self, task_id, task_name, category, payload=None, settings=None):
        super().__init__(task_id, task_name, category, payload)
        self.settings = settings

    def _run(self) -> dict:
        from ..core import license as lic_mod
        from ..core import plugin_market
        from ..core import tool_packs

        p = self.payload or {}
        entry = p.get("entry") or {}
        url = str(p.get("url") or "")
        name = str(p.get("name") or "能力包")
        version = str(p.get("version") or "latest")
        sha256 = str(p.get("sha256") or "")
        if not url:
            raise RuntimeError("能力包下载地址为空")
        access = plugin_market.plugin_access(entry, lic_mod.entitlements())
        if not access.get("allowed"):
            raise RuntimeError(access.get("reason") or "当前账号无权安装该能力包")
        dest_dir = self.settings.downloads_dir / "plugins"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"{name}-{version}.zip"
        self.ctx_stage("正在下载能力包", message=name)
        plugin_market.download_plugin(url, dest, sha256=sha256)
        self.ctx_stage("正在安装能力包", message=name)
        result = tool_packs.install_pack(
            self.settings, entry, zip_path=dest,
            log=lambda line: self.ctx_log("INFO", line))
        dest.unlink(missing_ok=True)  # 安装完成即删除下载缓存
        self.check_cancel()
        self.ctx_progress(100)
        self.ctx_log("OK", f"能力包已安装: {name}，重启机器人后生效")
        return result


class CheckDepsTask(TaskWorker):
    """扫描插件依赖并检查缺失项。payload: {"mode": "all"|"dir"|"zip", "target": path}"""

    def __init__(self, task_id, task_name, category, payload=None, settings=None):
        super().__init__(task_id, task_name, category, payload)
        self.settings = settings

    def _run(self) -> dict:
        mode = (self.payload or {}).get("mode", "all")
        target = (self.payload or {}).get("target", "")
        deps = []

        if mode == "zip":
            self.ctx_stage("正在读取 zip 依赖", message=target)
            deps = detect_dependencies_from_zip(target)
        else:
            dirs = []
            if mode == "dir" and target:
                dirs = [target]
            else:
                pd = self.settings.plugins_dir
                if pd.exists():
                    dirs = [p for p in sorted(pd.iterdir()) if p.is_dir() and p.name != "__pycache__"]
            for i, d in enumerate(dirs, 1):
                self.check_cancel()
                self.ctx_stage("正在扫描插件", i, len(dirs), str(d))
                deps += detect_dependencies_from_dir(d)

        seen, uniq = set(), []
        for d in deps:
            k = str(d).strip().lower()
            if k and k not in seen:
                seen.add(k)
                uniq.append(str(d).strip())
        deps = uniq

        missing = []
        if deps:
            missing = missing_dependencies(
                self.settings, deps,
                log=lambda line: self.ctx_log("INFO", line),
                on_progress=lambda done, total, dep: self.ctx_stage("正在检查依赖", done, total, dep),
                cancel_event=self.cancel_event,
            )
        self.check_cancel()
        self.ctx_log("OK", f"依赖检查完成：共 {len(deps)} 项，缺失 {len(missing)} 项")
        return {"checked": len(deps), "missing": missing, "missing_count": len(missing)}


class UninstallTask(TaskWorker):
    """自动卸载：停止服务 -> 删除安装目录与指针。payload 无。"""

    def __init__(self, task_id, task_name, category, payload=None, manager=None, settings=None):
        super().__init__(task_id, task_name, category, payload)
        self.manager = manager
        self.settings = settings

    def _run(self) -> dict:
        self.ctx_progress(0)
        self.ctx_stage("正在停止服务")
        if self.manager is not None:
            self.manager.stop_all(
                on_stage=lambda stage, current=0, total=-1, message="":
                    self.ctx_stage(stage, current, total, message))
        self.check_cancel()
        self.ctx_stage("正在删除安装文件")
        self.ctx_progress(40)
        ok = uninstall_deployment(self.settings, log=lambda line: self.ctx_log("INFO", line))
        self.ctx_progress(100)
        if not ok:
            raise RuntimeError("安装文件删除失败，请关闭占用程序后重试或手动删除")
        self.ctx_log("OK", "卸载完成")
        return {"uninstalled": str(self.settings.root)}
