"""服务启停：bot 走 deploy 模块，dsh 待 M4.5。"""
from . import deploy


def status() -> dict:
    return {
        "bot": deploy.status(),
        "dsh": {"state": "not_installed", "detail": "dsh 待 M4.5"},
    }


def start(service: str, log=print) -> dict:
    if service != "bot":
        raise NotImplementedError("dsh 待 M4.5 接入")
    return deploy.start(log=log)


def stop(service: str, log=print) -> dict:
    if service != "bot":
        raise NotImplementedError("dsh 待 M4.5 接入")
    return deploy.stop(log=log)


def restart(service: str, log=print) -> dict:
    stop(service, log=log)
    return start(service, log=log)
