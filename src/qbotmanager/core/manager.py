"""运行时门面：统一管理 NoneBot / QQ 官方通道 / 微信 iLink 的启停与状态。"""
import json
import re
import subprocess
import time
from pathlib import Path

from . import ai_config
from . import bot as bot_mod
from . import dsh as dsh_mod
from .exceptions import CancelledError
from .qq_channel import _pid_alive, create_qq_channel


def _proc_cmdline(pid, timeout=15) -> str:
    """查单个进程的命令行（停止前确认身份，避免 PID 复用误杀）。"""
    ps = (
        "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; "
        "Get-CimInstance Win32_Process -Filter \"ProcessId=" + str(int(pid)) + "\" | "
        "Select-Object -ExpandProperty CommandLine"
    )
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return r.stdout.strip()
    except Exception:  # noqa: BLE001
        return ""


def _kill_pid_tree(pid, timeout=15):
    try:
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True, timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception:  # noqa: BLE001
        pass


class Manager:
    def __init__(self, settings, on_log=None):
        self.settings = settings
        self.on_log = on_log or (lambda line: None)
        self.bot_proc = None
        # QQ 通道抽象：官方机器人
        self.qq_channel = create_qq_channel(self.settings, log=self.log, owner=self)
        self.dsh_proc = None
        self._dsh_verify = None   # (pid, ok, at)：dsh 命令行身份校验缓存
        self._bot_verify = None   # (pid, ok, at)：NoneBot 命令行身份校验缓存
        self._runtime_cache = None   # (mtime_ns, size, data)
        self._wx_cache = None        # (mtime_ns, size, data)
        self._wechat_adapter_synced = False  # 首次查状态时自动同步 iLink 适配器

    def log(self, line: str):
        self.on_log(line)
        try:
            logfile = self.settings.logs_dir / "manager.log"
            logfile.parent.mkdir(parents=True, exist_ok=True)
            with open(logfile, "a", encoding="utf-8", errors="replace") as f:
                f.write(line + "\n")
        except OSError:
            pass

    # ---------- 运行记录（跨进程接管后台服务，避免全量扫描进程） ----------
    def _runtime_path(self) -> Path:
        return self.settings.logs_dir / "runtime.json"

    def _read_runtime(self) -> dict:
        p = self._runtime_path()
        try:
            st = p.stat()
            key = (st.st_mtime_ns, st.st_size)
        except OSError:
            return {}
        if self._runtime_cache is not None and self._runtime_cache[0] == key:
            return self._runtime_cache[1]
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            data = data if isinstance(data, dict) else {}
        except (ValueError, OSError):
            data = {}
        self._runtime_cache = (key, data)
        return data

    def _runtime_get(self, key):
        return self._read_runtime().get(key) or 0

    def _write_runtime(self, data: dict):
        try:
            p = self._runtime_path()
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            tmp.replace(p)
            self._runtime_cache = None
        except OSError as e:
            self.log("写入运行记录失败: " + str(e))

    def _save_runtime(self, **kwargs):
        data = self._read_runtime()
        data.update(kwargs)
        self._write_runtime(data)

    def _runtime_clear(self, key):
        data = self._read_runtime()
        if key in data:
            data.pop(key)
            self._write_runtime(data)

    # ---------- 微信 ClawBot 通道 ----------
    def wechat_state_file(self) -> Path:
        """ilink 适配器登录状态文件（token / bot_id / 游标）。"""
        return self.settings.bot_dir / "data" / "nonebot_adapter_ilink" / "ilink_state.json"

    def wechat_login_status_file(self) -> Path:
        """ilink 适配器扫码进度文件（已扫码/需配对码/已绑定跳转等）。"""
        return self.settings.bot_dir / "data" / "nonebot_adapter_ilink" / "ilink_login_status.json"

    def wechat_verify_code_file(self) -> Path:
        """ilink 配对码输入文件：UI 写入，适配器轮询读取后删除。"""
        return self.settings.bot_dir / "data" / "nonebot_adapter_ilink" / "ilink_verify_code.txt"

    def submit_wechat_verify_code(self, code: str) -> bool:
        """把手机微信显示的数字配对码写入文件，适配器会在 2 秒内接走。"""
        code = (code or "").strip()
        if not code:
            return False
        try:
            p = self.wechat_verify_code_file()
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(code, encoding="utf-8")
            return True
        except OSError as e:
            self.log("写入微信配对码失败: " + str(e))
            return False

    def wechat_status(self) -> dict:
        """微信通道状态：是否已安装适配器、是否已登录、bot_id、登录时间。"""
        if not self._wechat_adapter_synced:
            self._wechat_adapter_synced = True
            try:
                from .license import feature_gate
                bot_mod.apply_wechat_gate(
                    self.settings, full=bool(feature_gate().get("member", True)))
            except Exception:  # noqa: BLE001 —— 同步失败不影响状态查询
                pass
        installed = (self.settings.plugins_dir / "nonebot_adapter_ilink").is_dir()
        st = {"installed": installed, "logged_in": False, "bot_id": "",
              "login_time": 0.0, "login_status": "", "login_status_ts": 0.0,
              "connected": False, "reason": ""}
        p = self.wechat_state_file()
        sp = self.wechat_login_status_file()
        try:
            stf = p.stat()
            st_key = (stf.st_mtime_ns, stf.st_size)
        except OSError:
            self._wx_cache = None
            self._read_login_status(st, sp)
            return st
        try:
            stf2 = sp.stat()
            st_key = (st_key, stf2.st_mtime_ns, stf2.st_size)
        except OSError:
            st_key = (st_key, None, None)
        if self._wx_cache is not None and self._wx_cache[0] == st_key:
            st.update(self._wx_cache[1])
            return st
        data = {}
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            data = {}
        vals = {
            "logged_in": bool(data.get("token")),
            "bot_id": str(data.get("bot_id") or ""),
            "login_time": float(data.get("login_time") or 0),
        }
        # 真实连接状态：机器人进程在跑 + 心跳新鲜（最近 120 秒有 getupdates）
        if vals["logged_in"]:
            if not self.bot_running():
                vals["connected"] = False
                vals["reason"] = "机器人未运行"
            else:
                last_poll = float(data.get("last_poll_ts") or 0)
                fresh = last_poll > 0 and (time.time() - last_poll) < 120
                vals["connected"] = fresh
                vals["reason"] = "已连接" if fresh else "连接中断，请重启机器人"
        else:
            vals["reason"] = "未登录"
        self._read_login_status(vals, sp)
        self._wx_cache = (st_key, vals)
        st.update(vals)
        return st

    @staticmethod
    def _read_login_status(target: dict, sp: Path) -> None:
        """把适配器写的扫码进度合并进状态 dict。"""
        try:
            d = json.loads(sp.read_text(encoding="utf-8"))
            if isinstance(d, dict):
                target["login_status"] = str(d.get("login_status") or "")
                target["login_status_ts"] = float(d.get("ts") or 0)
        except (ValueError, OSError):
            target["login_status"] = ""
            target["login_status_ts"] = 0.0

    def wechat_qr_url(self) -> str:
        """从 nonebot.log 提取最近一次 ilink 扫码链接（供 UI 打开二维码）。"""
        try:
            lines = (self.settings.logs_dir / "nonebot.log").read_text(
                encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return ""
        url = ""
        for i, line in enumerate(lines):
            if "请用微信扫码连接 ClawBot" in line:
                for nxt in lines[i + 1:i + 3]:
                    m = re.search(r"https?://\S+", nxt)
                    if m:
                        url = m.group(0).rstrip("，。；、）】\"'")
                        break
        return url

    def reset_wechat_login(self) -> None:
        """清除微信登录状态（token 与扫码进度），重启 NoneBot 后需重新扫码。"""
        try:
            for p in (self.wechat_state_file(), self.wechat_login_status_file()):
                if p.exists():
                    p.unlink()
            self._wx_cache = None
            self.log("已清除微信 ClawBot 登录状态，重启后需重新扫码")
        except OSError as e:
            self.log("清除微信登录状态失败: " + str(e))

    # ---------- 状态 ----------
    def bot_running(self) -> bool:
        if self.bot_proc is not None and self.bot_proc.poll() is None:
            return True
        return self._bot_pid_matches(self._runtime_get("bot_pid"))

    def _bot_pid_matches(self, pid) -> bool:
        """运行记录里的 PID 是否仍是本安装的 NoneBot（防 PID 复用误判/误杀）。

        Windows 会复用 PID：机器人被任务管理器强杀后，记录里的 PID 可能落到
        火绒等受保护进程上。只看 OpenProcess 会把它当成「机器人还在跑」，
        自动启动被挡住；停止时还可能按幽灵 PID 去 taskkill 无关进程。
        所以除进程存在外，还要核对命令行里有没有本安装的 Python / 机器人目录。
        """
        pid = int(pid or 0)
        if not pid or not _pid_alive(pid):
            return False
        cached = self._bot_verify
        now = time.monotonic()
        if cached is not None and cached[0] == pid:
            ttl = 30.0 if cached[1] else 5.0
            if now - cached[2] < ttl:
                return cached[1]
        cmd = (_proc_cmdline(pid) or "").lower()
        py = str(getattr(self.settings, "python_exe", "") or "").lower()
        bot_dir = str(getattr(self.settings, "bot_dir", "") or "").lower()
        markers = [m for m in (py, bot_dir) if m]
        ok = bool(cmd) and any(m in cmd for m in markers)
        self._bot_verify = (pid, ok, now)
        return ok

    def qq_running(self) -> bool:
        return self._sync_qq_channel().running()

    def _sync_qq_channel(self):
        """设置里换了接入方式就重建通道实例，再返回当前该用的那个。

        通道实例是 Manager 初始化时按当时的设置造出来的：用户在界面上把官方/第三方
        切过来并保存后，如果不重建，启动/停止/状态卡读到的还是旧通道 —— 表现就是
        「切成官方了，卡片上还挂着第三方 OneBot 的地址和状态」。
        """
        want = str(getattr(self.settings, "qq_channel", "") or "official").lower()
        if getattr(self.qq_channel, "key", None) != want:
            self.log("QQ 接入方式已切换为 " + want + "，重建通道实例")
            self.qq_channel = create_qq_channel(self.settings, log=self.log, owner=self)
        return self.qq_channel

    # ---------- dsh（DeepSeek Harness）QQ 群聊 AI 通道 ----------
    def dsh_running(self) -> bool:
        if self.dsh_proc is not None and self.dsh_proc.poll() is None:
            return True
        pid = self._runtime_get("dsh_pid")
        if not pid or not _pid_alive(pid):
            return False
        # 崩溃/退出可能留下“幽灵 PID”（OpenProcess 有句柄但进程已消失），
        # 必须验证命令行是 dsh qqbot profile，否则启动会被误判为已在运行。
        # 校验要走 PowerShell 子进程（约数百毫秒），GUI 刷新每 2 秒都会调到这里，
        # 不能每次刷新都重复拉子进程（会造成周期性卡顿）。同 PID 验证一次即可；
        # 验证失败（幽灵/换 PID）5 秒内复用结果，避免反复阻塞。
        cached = self._dsh_verify
        now = time.monotonic()
        if cached is not None and cached[0] == pid and (cached[1] or now - cached[2] < 5.0):
            return cached[1]
        cmd = _proc_cmdline(pid) or ""
        ok = "--profile" in cmd and "qqbot" in cmd
        self._dsh_verify = (pid, ok, now)
        return ok

    def dsh_status(self) -> dict:
        return dsh_mod.status(self.settings, self.dsh_running())

    def start_dsh(self, on_stage=None, cancel_event=None, on_progress=None):
        self._dsh_verify = None
        if str(getattr(self.settings, "qq_channel", "") or "").lower() == "onebot":
            # dsh 只吃 QQ 官方 AppID/AppSecret：第三方通道下拉起来等于把官方那个号
            # 又拉上线（第三方协议端还连不上），必须先在界面上切回官方。
            self.log("当前是第三方 OneBot 通道：dsh 仅支持官方，拒绝启动")
            raise RuntimeError("dsh 仅支持 QQ 官方通道：先切回「QQ 官方机器人」再启动")
        if (getattr(self.settings, "agent_profile_enabled", False)
                and getattr(self.settings, "agent_profile_id", "") == "liqinghan"):
            # 李清菡档案与 dsh 共用 18650 桥端口：档案接管时手动点「启动 dsh」，
            # 档案的微信桥就绑不上端口（日志里只有一行 warning）——直接拒绝更清楚。
            self.log("智能体档案（李清菡）正在接管：dsh 与它共用 18650 桥端口，拒绝启动")
            raise RuntimeError("李清菡档案正在接管（共用 18650 桥端口）：先关掉智能体档案再启动 dsh")
        if self.dsh_running():
            self.log("dsh 通道已在运行")
            return
        if cancel_event is not None and cancel_event.is_set():
            raise CancelledError("启动 dsh 通道已取消")
        # 没装就直接装：用户在「启动全部」/自动启动/界面按钮上都不该被
        # 「请先点安装」挡回去（装完顺手启动，这才是「自动安装 + 自动启动」）。
        self.ensure_dsh_installed(on_progress=on_progress, cancel_event=cancel_event)
        if on_stage:
            on_stage("正在启动 QQ 群聊 AI（dsh）")
        self.log("启动 dsh 通道 ...")
        try:
            # 18650 是桥插件专用回环端口：任何残留监听都会让 dsh 启动即崩
            # （例如外部手动进程、上次异常退出留下的孤儿进程），先强制清场。
            self._ensure_port_closed(dsh_mod.BRIDGE_PORT, "", force=True)
            self.dsh_proc = dsh_mod.start(self.settings, log=self.log,
                                          cancel_event=cancel_event)
            self._save_runtime(dsh_pid=self.dsh_proc.pid)
        except Exception as e:  # noqa: BLE001
            self.log("启动 dsh 通道失败: " + str(e))
            raise RuntimeError("启动 dsh 通道失败: " + str(e)) from e

    def ensure_dsh_installed(self, on_progress=None, cancel_event=None) -> bool:
        """dsh 没装就自动装好（含便携版 Node.js），返回本次是否真的装了。

        首次安装要下约 30MB Node + dsh 依赖，约 1~3 分钟，进度通过 on_progress
        (已处理量, 总量) 报给任务面板。失败时抛 RuntimeError 并带上重试入口，
        取消时原样抛 CancelledError 交给上层回滚。
        """
        settings = self.settings
        if dsh_mod.is_installed(settings):
            return False
        # 配置预检：缺 AppID / 模型 Key 时立刻报错，别下完上百 MB 才失败
        if not (str(getattr(settings, "qq_official_appid", "") or "").strip()
                and str(getattr(settings, "qq_official_secret", "") or "").strip()):
            raise RuntimeError("dsh 需要 QQ 官方机器人 AppID / AppSecret：请先在「QQ」页填写")
        ai = ai_config.current_config(settings) or {}
        if not (str(getattr(settings, "dsh_api_key", "") or "").strip()
                or str(ai.get("api_key") or "").strip()):
            raise RuntimeError("dsh 需要模型 API Key：请先在「AI 大脑」配置服务商")
        self.log("dsh 未安装：自动安装 dsh（DeepSeek Harness）+ 官方 QQ 插件 ...")

        def _prog(pct):
            if on_progress:
                try:
                    on_progress(int(pct), 100)
                except Exception:  # noqa: BLE001 —— 进度回调失败不能影响安装
                    pass

        try:
            dsh_mod.install(settings, log=self.log, on_progress=_prog,
                            cancel_event=cancel_event)
        except CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            self.log("自动安装 dsh 失败: " + str(e))
            raise RuntimeError(
                "dsh 自动安装失败（可在「QQ」页点「安装并启动 dsh」重试）: " + str(e)) from e
        self.log("dsh 自动安装完成")
        return True

    def stop_dsh(self, timeout=15):
        self._dsh_verify = None
        if self.dsh_proc is not None and self.dsh_proc.poll() is None:
            self.log("停止 dsh 通道 ...")
            bot_mod.stop_bot(self.dsh_proc)
        self.dsh_proc = None
        self._stop_runtime_pid("dsh_pid", str(dsh_mod.node_exe(self.settings)),
                               timeout=timeout, markers=("--profile",))

    # ---------- 启动/停止 ----------
    def start_all(self, on_stage=None, on_progress=None, cancel_event=None) -> dict:
        """启动 QQ 通道 + NoneBot（+ dsh 群聊 AI）。

        任一失败时先把已启动的组件回滚停止，再抛异常，
        避免“启动未完全成功”但服务仍在后台运行的半启动状态。
        """
        started = []
        qq_ok = bot_ok = dsh_ok = False
        try:
            if on_stage:
                on_stage("正在启动 " + self._sync_qq_channel().label)
            self._sync_qq_channel().start(on_stage=on_stage, on_progress=on_progress,
                                          cancel_event=cancel_event)
            qq_ok = True
            started.append("qq")

            if getattr(self.settings, "nonebot_enabled", True):
                if on_stage:
                    on_stage("正在启动 NoneBot")
                self.start_bot(on_stage=on_stage, cancel_event=cancel_event)
                bot_ok = True
                started.append("bot")
            else:
                self.log("NoneBot 已在设置中关闭，跳过启动")

            dsh_wanted = bool(getattr(self.settings, "dsh_enabled", False))
            if dsh_wanted and str(
                    getattr(self.settings, "qq_channel", "") or "").lower() == "onebot":
                # 手改 settings / 旧存档可能留下「第三方通道 + dsh 启用」的组合：
                # 启动全部时直接跳过，别让 dsh 抢回官方网关（保存通道时会自动关掉勾选）
                self.log("当前是第三方 OneBot 通道：dsh 仅支持官方，跳过启动 dsh")
                dsh_wanted = False
            if (dsh_wanted
                    and getattr(self.settings, "agent_profile_enabled", False)
                    and getattr(self.settings, "agent_profile_id", "") == "liqinghan"):
                # 李清菡插件与 dsh 共用 18650 桥端口/统一大脑角色，启用李清菡时互斥
                self.log("智能体档案（李清菡）已启用：dsh 与李清菡互斥，跳过 dsh")
                dsh_wanted = False
            if dsh_wanted:
                if on_stage:
                    on_stage("正在启动 QQ 群聊 AI（dsh）")
                self.start_dsh(on_stage=on_stage, cancel_event=cancel_event,
                               on_progress=on_progress)
                dsh_ok = True
                started.append("dsh")
            else:
                self.log("dsh 通道已在设置中关闭，跳过启动")
        except CancelledError:
            self._rollback_started(started)
            raise
        except Exception as e:  # noqa: BLE001
            self._rollback_started(started)
            raise RuntimeError("启动未完全成功；已回滚已启动的服务：" + str(e)) from e

        if not bot_ok and not dsh_ok:
            # NoneBot/dsh 都被开关关闭时不算失败，返回提示状态
            return {"qq_ok": qq_ok, "bot_ok": False,
                    "bot_skipped": True, "dsh_ok": dsh_ok}
        return {
            "qq_ok": qq_ok,
            "bot_ok": bot_ok,
            "bot_skipped": False,
            "dsh_ok": dsh_ok,
        }

    def _rollback_started(self, started):
        """启动失败/取消时，把已启动的组件按反序停止（尽力而为）。"""
        for name in reversed(started):
            try:
                if name == "dsh":
                    self.stop_dsh()
                elif name == "bot":
                    self.stop_bot()
                elif name == "qq":
                    self._sync_qq_channel().stop()
            except Exception as e:  # noqa: BLE001
                self.log(f"回滚停止 {name} 失败: {e}")

    def start_bot(self, on_stage=None, cancel_event=None):
        if self.bot_running():
            self.log("NoneBot 已在运行")
            return
        if (getattr(self.settings, "agent_profile_enabled", False)
                and getattr(self.settings, "agent_profile_id", "") == "liqinghan"
                and self.dsh_running()):
            # 李清菡档案与 dsh 共用 18650 桥端口：档案接管后 dsh 必须先让位，
            # 否则档案的微信桥绑不上端口——日志里只有一行 warning，
            # 用户看到的是「开了档案但微信那半边不动」。
            self.log("智能体档案（李清菡）已启用：先停掉 dsh（共用 18650 桥端口）")
            self.stop_dsh()
        if cancel_event is not None and cancel_event.is_set():
            raise CancelledError("启动 NoneBot 已取消")
        if on_stage:
            on_stage("正在检查环境")
        self.log("启动 NoneBot ...")
        try:
            if on_stage:
                on_stage("正在启动 NoneBot")
            self.bot_proc = bot_mod.start_bot(self.settings, on_line=self.log)
            # 短暂观察：进程立即退出说明环境/项目有问题，尽早报错而不是留下假运行状态
            time.sleep(1.2)
            if self.bot_proc.poll() is not None:
                tail = self._log_tail(self.settings.logs_dir / "nonebot.log", 400)
                raise RuntimeError("NoneBot 启动后立即退出: " + tail)
            self._save_runtime(bot_pid=self.bot_proc.pid)
            self._bot_verify = (self.bot_proc.pid, True, time.monotonic())
        except Exception as e:  # noqa: BLE001
            self.log("启动 NoneBot 失败: " + str(e))
            raise RuntimeError("启动 NoneBot 失败: " + str(e)) from e

    def _log_tail(self, path, max_chars=400) -> str:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            return (text[-max_chars:].strip()) or "无日志输出"
        except OSError:
            return "无法读取日志"

    def restart_bot(self, on_stage=None, cancel_event=None):
        """重启 NoneBot（安装插件后生效用）。"""
        if on_stage:
            on_stage("正在停止 NoneBot")
        self.stop_bot()
        time.sleep(0.8)
        self.start_bot(on_stage=on_stage, cancel_event=cancel_event)

    def stop_all(self, on_stage=None) -> dict:
        """停止全部服务；任一失败时抛异常。"""
        errors = []
        if on_stage:
            on_stage("正在停止 QQ 群聊 AI（dsh）")
        try:
            self.stop_dsh()
        except Exception as e:  # noqa: BLE001
            errors.append("QQ 群聊 AI(dsh): " + str(e))
        if on_stage:
            on_stage("正在停止 NoneBot")
        try:
            self.stop_bot()
        except Exception as e:  # noqa: BLE001
            errors.append("NoneBot: " + str(e))
        if on_stage:
            on_stage("正在停止 " + self._sync_qq_channel().label)
        try:
            self._sync_qq_channel().stop()
        except Exception as e:  # noqa: BLE001
            errors.append(self._sync_qq_channel().label + ": " + str(e))
        if on_stage:
            on_stage("清理端口残留")
        # 兜底：若按 PID 停止后端口仍被占用，按端口定位残留进程清理
        self._ensure_port_closed(self.settings.nonebot_port, str(self.settings.python_exe))
        # dsh 桥端口同样兜底：专用端口上任何残留监听都应清掉
        self._ensure_port_closed(dsh_mod.BRIDGE_PORT, "", force=True)
        if errors:
            raise RuntimeError("停止未完全成功；" + "；".join(errors))
        return {"stopped": True}

    def _port_pids(self, port) -> list:
        ps = (
            "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; "
            "Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | "
            f"Where-Object {{ $_.LocalPort -eq {int(port)} }} | "
            "Select-Object -ExpandProperty OwningProcess | Sort-Object -Unique"
        )
        try:
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=15, creationflags=subprocess.CREATE_NO_WINDOW,
            )
            return [int(x) for x in r.stdout.split() if x.strip().isdigit()]
        except Exception:  # noqa: BLE001
            return []

    def _ensure_port_closed(self, port, hint, force=False):
        """按端口清理残留监听进程。

        force=True 时无条件清理该端口上的所有监听进程（仅用于 AstroSwarm
        专用回环端口，如 dsh 桥 18650）；否则按命令行身份匹配。
        """
        if not port:
            return
        for pid in self._port_pids(port):
            if not _pid_alive(pid):
                continue
            cmd = _proc_cmdline(pid)
            if force or hint in (cmd or "") or not cmd:
                self.log(f"清理占用端口 {port} 的残留进程 (PID {pid}) ...")
                _kill_pid_tree(pid)

    def _stop_runtime_pid(self, key, hint, timeout=15, markers=()):
        """按运行记录停止后台进程；命令行为空时跳过，绝不对幽灵 PID 下手。"""
        pid = self._runtime_get(key)
        if pid and _pid_alive(pid):
            cmd = _proc_cmdline(pid)
            cmdline = cmd or ""
            if hint in cmdline or any(m in cmdline for m in markers):
                self.log(f"停止后台进程 (PID {pid}) ...")
                _kill_pid_tree(pid, timeout=timeout)
            elif not cmd:
                self.log(f"跳过 PID {pid}：读不到命令行，无法确认是本程序的后台进程")
            else:
                self.log(f"跳过 PID {pid}：进程身份与当前机器人不符")
        self._runtime_clear(key)

    def stop_bot(self):
        if self.bot_proc is not None and self.bot_proc.poll() is None:
            self.log("停止 NoneBot ...")
            bot_mod.stop_bot(self.bot_proc)
        self.bot_proc = None
        self._bot_verify = None
        self._stop_runtime_pid(
            "bot_pid", str(self.settings.python_exe), markers=("run.py",))

    def qq_login_state(self) -> dict:
        return self._sync_qq_channel().login_state()
