"""平台信息：机器码（/etc/machine-id）与 XDG 路径基座。"""
import os
import socket
import sys
from pathlib import Path

MACHINE_ID_PATHS = ["/etc/machine-id", "/var/lib/dbus/machine-id"]


def is_linux() -> bool:
    return sys.platform.startswith("linux")


def machine_id() -> str:
    for path in MACHINE_ID_PATHS:
        try:
            value = Path(path).read_text(encoding="utf-8").strip()
            if value:
                return value
        except OSError:
            continue
    return socket.gethostname()


def _home(kind: str) -> Path:
    if kind == "data":
        env = "XDG_DATA_HOME"
        default = Path.home() / ".local" / "share"
    else:
        env = "XDG_CONFIG_HOME"
        default = Path.home() / ".config"
    base = os.environ.get(env) or str(default)
    return Path(base) / "astroswarm"


def data_home() -> Path:
    return _home("data")


def config_home() -> Path:
    return _home("config")


def log_home() -> Path:
    return data_home() / "logs"
