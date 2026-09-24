# -*- coding: utf-8 -*-
"""星群账号：程序端登录网站账号，并同步本机激活状态到服务器。"""
import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request

from .license import SERVER_WEB, _appdata_dir

logger = logging.getLogger("qbotmanager")
TIMEOUT = 15


def account_file():
    return _appdata_dir() / "account.json"


def load_account() -> dict | None:
    p = account_file()
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if data.get("email") and data.get("token"):
            return data
    except (ValueError, OSError) as e:
        logger.warning("读取账号失败: %s", e)
    return None


def save_account(data: dict):
    try:
        account_file().write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except OSError as e:
        logger.warning("保存账号失败: %s", e)


def clear_account():
    try:
        p = account_file()
        if p.exists():
            p.unlink()
    except OSError as e:
        logger.warning("清除账号失败: %s", e)


def _post(path: str, payload: dict, token: str = ""):
    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(SERVER_WEB + path, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode("utf-8", "replace"))
        except Exception:  # noqa: BLE001
            return {"ok": False, "detail": f"HTTP {e.code}"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "detail": "无法连接星群服务器: " + str(e), "network": True}


def _get(path: str, token: str):
    req = urllib.request.Request(SERVER_WEB + path, headers={"Authorization": "Bearer " + token})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode("utf-8", "replace"))
        except Exception:  # noqa: BLE001
            return {"ok": False, "detail": f"HTTP {e.code}"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "detail": "无法连接星群服务器: " + str(e), "network": True}


def login(email: str, password: str) -> dict:
    """用网站账号登录；成功后在本地保存 token（7 天有效）。"""
    data = _post("/api/account/login", {"email": (email or "").strip(), "password": password or ""})
    if data.get("ok"):
        save_account({
            "email": data.get("email", ""),
            "token": data.get("token", ""),
            "login_at": time.time(),
        })
    return data


def me(token: str) -> dict:
    return _get("/api/account/me", token)


def redeem(token: str, code: str) -> dict:
    """兑换码兑换：只有账号服务知道码是真是假，本机只负责转发 + 之后重拉权益。

    与无头端 /api/plugins/redeem 走同一个账号服务接口，桌面端与 Linux 端行为一致。
    """
    return _post("/api/account/redeem", {"code": (code or "").strip()}, token=token)


def sync(token: str, machine_id: str, license_key: str, expires_at: float = 0) -> dict:
    """把本机激活状态（机器码/激活码/到期时间）同步到网站账号。"""
    return _post("/api/account/program-sync", {
        "machine_id": machine_id,
        "license": license_key,
        "expires_at": float(expires_at or 0),
    }, token=token)


def claim_device(token: str, machine_id: str) -> dict:
    """邮箱登录后认领本机：绑定授权，新设备认领自动踢掉旧设备。"""
    return _post("/api/account/device/claim", {"machine_id": machine_id}, token=token)


def check_device(token: str, machine_id: str) -> dict:
    """查询本机是否仍是账号当前活跃设备（被踢检测）。"""
    q = urllib.parse.urlencode({"machine_id": machine_id})
    return _get(f"/api/account/device/check?{q}", token)
