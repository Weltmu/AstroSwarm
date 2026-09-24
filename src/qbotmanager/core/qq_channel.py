"""QQ 通道抽象层。

统一 QQ 通道接口（登录 / 启停 / 状态 / 消息路由）。
支持两种方式：
1. official：QQ 官方机器人（q.qq.com 凭证，NoneBot 适配器直连）。
2. onebot：第三方 OneBot 协议端（用户自行安装的 LLOneBot /
   Lagrange / NapCat 等，AstroSwarm 只做标准 OneBot V11 对接：
   默认反向 WS（协议端主动连回星群），也支持正向 WS；不内置、
   不分发任何协议端；账号风险由用户自担）。
"""
import ctypes
from abc import ABC, abstractmethod

from . import bot as bot_mod
from .exceptions import CancelledError


def _pid_alive(pid) -> bool:
    if not pid:
        return False
    try:
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        h = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not h:
            return False
        ctypes.windll.kernel32.CloseHandle(h)
        return True
    except Exception:  # noqa: BLE001
        return False


class QQChannel(ABC):
    """QQ 通道统一接口。"""

    key = "unknown"
    label = "未知通道"

    def __init__(self, settings, log=None, owner=None):
        self.settings = settings
        self.log = log or (lambda line: None)
        # owner 为宿主（Manager），提供 runtime 持久化 / 端口清理等能力；
        # 缺省时通道退化为无宿主运行（如单测）。
        self.owner = owner

    # ---------- 宿主能力（runtime 记录） ----------
    def _runtime_get(self, key):
        if self.owner is not None:
            return self.owner._runtime_get(key)
        return 0

    def _runtime_save(self, **kwargs):
        if self.owner is not None:
            self.owner._save_runtime(**kwargs)

    def _runtime_clear(self, key):
        if self.owner is not None:
            self.owner._runtime_clear(key)

    def _stop_runtime_pid(self, key, hint, timeout=15):
        if self.owner is not None:
            self.owner._stop_runtime_pid(key, hint, timeout=timeout)

    # ---------- 通道接口 ----------
    @abstractmethod
    def running(self) -> bool:
        """通道是否在运行。"""

    @abstractmethod
    def start(self, on_stage=None, on_progress=None, cancel_event=None):
        """准备并启动通道；失败抛 RuntimeError，取消抛 CancelledError。"""

    @abstractmethod
    def stop(self, timeout=15):
        """停止通道。"""

    @abstractmethod
    def restart(self, cancel_event=None):
        """停止后重启通道。"""

    @abstractmethod
    def login_state(self) -> dict:
        """返回登录状态：{logged_in, reason, account}。"""

    @abstractmethod
    def accounts(self) -> list:
        """返回已发现的所有账号列表。"""

    @abstractmethod
    def qr_image_path(self):
        """返回登录二维码图片路径；无二维码时返回 None。"""

    @abstractmethod
    def pending_accounts(self) -> list:
        """返回已出现账号配置但尚未完成消息路由的账号列表。"""

    @abstractmethod
    def ensure_message_routes(self, on_stage=None, cancel_event=None):
        """为所有待处理账号写入消息路由配置，必要时重启通道。"""

    @abstractmethod
    def switch_account(self, on_stage=None, cancel_event=None):
        """清空登录资料并重启，等待重新登录。"""


class OfficialQQChannel(QQChannel):
    """QQ 官方机器人通道：无独立进程，通过 NoneBot 适配器连接 q.qq.com。"""

    key = "official"
    label = "QQ 官方机器人"

    def _configured(self) -> bool:
        return bool(
            getattr(self.settings, "qq_official_appid", "")
            and getattr(self.settings, "qq_official_token", "")
            and getattr(self.settings, "qq_official_secret", "")
        )

    def running(self) -> bool:
        if not self._configured():
            return False
        return bool(self.owner is not None and self.owner.bot_running())

    def start(self, on_stage=None, on_progress=None, cancel_event=None):
        if not self._configured():
            self.log("官方 QQ 通道未配置 appid/token/secret，跳过（请在设置中填写机器人凭证）")
            return
        if cancel_event is not None and cancel_event.is_set():
            raise CancelledError("启动官方 QQ 通道已取消")
        if on_stage:
            on_stage("配置官方 QQ 通道")
        bot_mod.sync_qq_adapters(self.settings, log=self.log)
        bot_mod.ensure_official_qq_deps(self.settings, log=self.log)
        bot_mod.write_env(self.settings)
        self.log("官方 QQ 通道配置已写入，等待 NoneBot 启动连接")

    def stop(self, timeout=15):
        self.log("官方 QQ 通道无独立进程，随 NoneBot 一起停止")

    def restart(self, cancel_event=None):
        if self.owner is not None:
            self.owner.restart_bot(cancel_event=cancel_event)

    def login_state(self) -> dict:
        if not self._configured():
            return {"logged_in": False, "reason": "未配置凭证", "account": ""}
        online = bool(self.owner is not None and self.owner.bot_running())
        return {
            "logged_in": online,
            "reason": "已配置" if online else "等待 NoneBot 连接",
            "account": str(self.settings.qq_official_appid),
        }

    def accounts(self) -> list:
        return [str(self.settings.qq_official_appid)] if self._configured() else []

    def qr_image_path(self):
        return None

    def pending_accounts(self) -> list:
        return []

    def ensure_message_routes(self, on_stage=None, cancel_event=None):
        self.log("官方 QQ 通道无需注入反向 WS（事件由官方网关推送）")
        return []

    def switch_account(self, on_stage=None, cancel_event=None):
        self.log("官方 QQ 通道无需切换账号：修改 appid/token/secret 后重启生效")


class OneBotQQChannel(QQChannel):
    """第三方 OneBot V11 协议通道（默认反向 WS，协议端主动连回星群）。

    协议端由用户自行安装（如 LLOneBot / Lagrange.OneBot），本通道只
    负责标准 OneBot V11 对接：反向 WS（推荐）时 NoneBot 监听
    /onebot/v11/ws，把地址粘贴到协议端即可；正向 WS 时星群作为
    客户端连接协议端。事件交给 NoneBot 的 onebot v11 适配器处理。
    AstroSwarm 不内置、不下载任何协议端。
    """

    key = "onebot"
    label = "第三方 OneBot 协议"

    @property
    def _mode(self) -> str:
        return str(getattr(self.settings, "qq_onebot_mode", "") or "reverse").lower()

    @property
    def _host(self) -> str:
        return str(getattr(self.settings, "qq_onebot_host", "") or "127.0.0.1").strip()

    @property
    def _port(self) -> int:
        try:
            return int(getattr(self.settings, "qq_onebot_port", 0) or 0)
        except (TypeError, ValueError):
            return 0

    @property
    def _path(self) -> str:
        return str(getattr(self.settings, "qq_onebot_path", "") or "/onebot/v11/ws").strip()

    @property
    def _token(self) -> str:
        return str(getattr(self.settings, "qq_onebot_token", "") or "").strip()

    @property
    def _listen_host(self) -> str:
        return str(
            getattr(self.settings, "qq_onebot_listen_host", "") or "127.0.0.1"
        ).strip() or "127.0.0.1"

    def _configured(self) -> bool:
        if self._mode == "forward":
            return bool(self._host and self._port > 0)
        return int(getattr(self.settings, "nonebot_port", 0) or 0) > 0

    def _endpoint(self) -> str:
        if self._mode == "forward":
            return f"{self._host}:{self._port}"
        return self.reverse_ws_url()

    def reverse_ws_url(self) -> str:
        """返回可直接粘贴到协议端「反向 WebSocket」配置的地址。"""
        host = self._listen_host
        if host in ("0.0.0.0", "::", "[::]"):
            host = "127.0.0.1"
        port = int(getattr(self.settings, "nonebot_port", 0) or 0)
        if port <= 0:
            port = 12111
        return f"ws://{host}:{port}/onebot/v11/ws"

    def running(self) -> bool:
        if not self._configured():
            return False
        return bool(self.owner is not None and self.owner.bot_running())

    def start(self, on_stage=None, on_progress=None, cancel_event=None):
        if not self._configured():
            self.log(
                "第三方 OneBot 通道未配置，跳过（反向模式请确认 NoneBot 端口；"
                "正向模式请填写协议端地址/端口）"
            )
            return
        if cancel_event is not None and cancel_event.is_set():
            raise CancelledError("启动第三方 OneBot 通道已取消")
        if on_stage:
            on_stage("配置第三方 OneBot 通道")
        bot_mod.sync_qq_adapters(self.settings, log=self.log)
        bot_mod.ensure_onebot_deps(self.settings, log=self.log)
        bot_mod.write_env(self.settings)
        if self._mode == "forward":
            self.log(
                f"第三方 OneBot 通道配置已写入（{self._endpoint()}），"
                "等待 NoneBot 连接协议端；协议端请自行保持在线"
            )
        else:
            self.log(
                f"反向 WS 已就绪：{self.reverse_ws_url()}；"
                "请在协议端（LLOneBot / NapCat）的「反向 WebSocket」粘贴该地址，"
                "协议端会主动连回星群"
            )

    def stop(self, timeout=15):
        self.log("第三方 OneBot 通道无独立进程，随 NoneBot 一起停止")

    def restart(self, cancel_event=None):
        if self.owner is not None:
            self.owner.restart_bot(cancel_event=cancel_event)

    def login_state(self) -> dict:
        if not self._configured():
            return {"logged_in": False, "reason": "未配置协议端连接", "account": ""}
        online = bool(self.owner is not None and self.owner.bot_running())
        if self._mode == "forward":
            reason = "已配置，等待协议端连接" if online else "等待 NoneBot 连接协议端"
        else:
            reason = "已配置，等待协议端反向连接" if online else "等待协议端反向连接"
        return {
            "logged_in": online,
            "reason": reason,
            "account": self._endpoint(),
        }

    def accounts(self) -> list:
        return [self._endpoint()] if self._configured() else []

    def qr_image_path(self):
        # 第三方协议端的登录二维码由协议端自己展示，AstroSwarm 不参与登录
        return None

    def pending_accounts(self) -> list:
        return []

    def ensure_message_routes(self, on_stage=None, cancel_event=None):
        if self._mode == "forward":
            self.log("第三方 OneBot 通道由正向 WS 自动接收事件，无需注入反向 WS")
        else:
            self.log("第三方 OneBot 通道由协议端通过反向 WS 主动上报，无需注入反向 WS")
        return []

    def switch_account(self, on_stage=None, cancel_event=None):
        self.log("第三方 OneBot 账号在协议端中管理：修改连接方式/地址/令牌后重启生效")


_CHANNELS = {
    "official": OfficialQQChannel,
    "onebot": OneBotQQChannel,
}


def create_qq_channel(settings, log=None, owner=None, key=None):
    """创建 QQ 通道实例（official / onebot）。"""
    key = (key or getattr(settings, "qq_channel", "") or "official").lower()
    cls = _CHANNELS.get(key, OfficialQQChannel)
    ch = cls(settings, log=log, owner=owner)
    ch.key = key
    return ch
