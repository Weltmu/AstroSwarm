"""星群账号授权：登录/认领/本地授权状态（对接现有账号服务）。"""
import json
import os
import urllib.error
import urllib.request

from . import headless_config, plans

# 账号服务地址：配置 account_base > 环境变量 ASTROSWARM_ACCOUNT_BASE > 官方托管服务。
# 不要写死本机开发地址：客户机器上没人监听那个端口，登录会一路 401。
ACCOUNT_BASE_ENV = "ASTROSWARM_ACCOUNT_BASE"
ACCOUNT_BASE_DEFAULT = "https://astroswarm.cn/api/account"
ACCOUNT_PATH_PREFIX = "/api/account"


def account_base() -> str:
    """当前生效的账号服务地址（原样返回，可能带 /api/account 后缀）。

    优先级：config.json 的 account_base > 环境变量 ASTROSWARM_ACCOUNT_BASE > 官方默认。

    注意「配置里存着官方默认地址」这件事：老版本 headless_config.DEFAULTS 把官方地址
    写进了默认值，于是**每个客户机的 config.json 里都有一个"配置值"**，
    环境变量与 systemd 的 Environment= 会被它压住。
    所以这里把"等于官方默认"的配置值也当成没配 —— 已经装过的机器同样能靠环境变量改。
    """
    try:
        cfg = str(headless_config.load().get("account_base") or "").strip()
    except Exception:  # noqa: BLE001 —— 配置读不出来就退回环境变量/默认值
        cfg = ""
    if cfg and cfg.rstrip("/") != ACCOUNT_BASE_DEFAULT.rstrip("/"):
        return cfg.rstrip("/")
    env = str(os.environ.get(ACCOUNT_BASE_ENV) or "").strip()
    if env:
        return env.rstrip("/")
    return ACCOUNT_BASE_DEFAULT


def account_url(path: str) -> str:
    """拼接口 URL（path 形如 /api/account/login）。

    account_base 允许两种写法：`https://astroswarm.cn` 或
    `https://astroswarm.cn/api/account`（默认值就是后者），这里统一去重前缀。
    """
    base = account_base()
    if base.endswith(ACCOUNT_PATH_PREFIX):
        base = base[: -len(ACCOUNT_PATH_PREFIX)]
    return base + path


def _open_json(req) -> dict:
    """发请求并解析 JSON；把「连不上账号服务」和「账号密码错」分开报。"""
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            body = json.loads(exc.read().decode("utf-8", "replace"))
            detail = str(body.get("detail") or body.get("error") or body.get("message") or "")
        except Exception:  # noqa: BLE001
            detail = ""
        raise RuntimeError(detail or f"账号服务返回 HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"连不上星群账号服务（{account_base()}）：{exc.reason}。"
            f"自建账号服务请改配置 account_base 或环境变量 {ACCOUNT_BASE_ENV}"
        ) from exc


def _post(path, body, token=None, client_ip=""):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    if client_ip:
        # 带上真实来访 IP：无头端从本机再 POST 一次账号服务，不带转发头的话账号服务
        # 只看得到 127.0.0.1，所有控制台登录会共用一个限流桶。
        # 账号服务只在直连方是回环时才采信这两个头，且取 XFF 的最后一段。
        headers["X-Real-IP"] = str(client_ip)
        headers["X-Forwarded-For"] = str(client_ip)
    req = urllib.request.Request(
        account_url(path),
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    return _open_json(req)


def login(email: str, password: str, client_ip: str = "") -> dict:
    data = _post(
        "/api/account/login", {"email": email, "password": password}, client_ip=client_ip
    )
    cfg = headless_config.load()
    cfg["account_email"] = data.get("email") or email
    cfg["account_token"] = data.get("token") or ""
    cfg["plan"] = data.get("plan") or "none"
    cfg["plan_expires_at"] = float(data.get("plan_expires_at") or 0)
    cfg["entitlement_sig"] = str(data.get("entitlement_sig") or "")
    cfg["entitlement_machine"] = str(data.get("entitlement_machine") or "")
    headless_config.save(cfg)
    return {
        "ok": True,
        "email": cfg["account_email"],
        "plan": cfg["plan"],
        "plan_expires_at": cfg["plan_expires_at"],
    }


def claim(machine_id: str) -> dict:
    cfg = headless_config.load()
    token = cfg.get("account_token") or ""
    if not token:
        raise RuntimeError("未登录星群账号")
    data = _post(
        "/api/account/device/claim",
        {"machine_id": machine_id},
        token=token,
    )
    # 权益签名由账号服务下发，认领后再拉一次 me（claim 的响应里没有签名）
    try:
        got = me(token)
        if isinstance(got, dict) and got.get("ok") is not False:
            data = {**data, **{k: v for k, v in got.items() if k.startswith("entitlement_")}}
    except Exception:  # noqa: BLE001
        pass
    cfg["plan"] = data.get("plan") or "none"
    cfg["plan_expires_at"] = float(data.get("plan_expires_at") or 0)
    cfg["entitlement_sig"] = str(data.get("entitlement_sig") or "")
    cfg["entitlement_machine"] = str(data.get("entitlement_machine") or "")
    headless_config.save(cfg)
    return {
        "ok": True,
        "plan": cfg["plan"],
        "plan_expires_at": cfg["plan_expires_at"],
        "license": bool(data.get("license")),
    }


def me(token: str) -> dict:
    """拉当前账号信息（含权益签名）。"""
    req = urllib.request.Request(
        account_url("/api/account/me"),
        headers={"Authorization": "Bearer " + token},
    )
    return _open_json(req)


def verify_entitlement(cfg: dict | None = None) -> bool:
    """校验无头配置里的 plan / 已购插件是否带账号服务的 Ed25519 签名。

    与桌面端同一套规范文本（license.entitlement_payload），验签不过一律按未开通处理。
    """
    cfg = headless_config.load() if cfg is None else cfg
    sig = str(cfg.get("entitlement_sig") or "").strip()
    if not sig:
        return False
    try:
        import base64

        from nacl.signing import VerifyKey

        from qbotmanager.core.license import PUBLIC_KEY_HEX, entitlement_payload

        payload = entitlement_payload(
            cfg.get("entitlement_machine") or "",
            cfg.get("plan"), cfg.get("plan_expires_at"), cfg.get("owned_plugins"))
        VerifyKey(bytes.fromhex(PUBLIC_KEY_HEX)).verify(payload.encode(), base64.b64decode(sig))
        return True
    except Exception:  # noqa: BLE001
        return False


def feature_gate(cfg: dict | None = None) -> dict:
    """本机权益闸门。

    两个互不替代的判定：

    - `member` = 已开通的档位且未过期（微信通道看它）。trial 不算。
    - `full` / `all_plugins` = 历史字段：2026-09 起能力包全部免费，
      运行时不再按档位放行，保留只为兼容旧调用方。

    判定只认服务器签名过的档位：光改本地 config 不会开通任何通道。
    """
    cfg = headless_config.load() if cfg is None else cfg
    if not verify_entitlement(cfg):
        return {
            "full": False,
            "member": False,
            "all_plugins": False,
            "plan": "none",
            "plan_expires_at": 0,
            "email": cfg.get("account_email") or "",
            "reason": "QQ 通道可用；微信通道未开通（本机权益未通过签名校验）",
        }
    plan = str(cfg.get("plan") or "none").lower()
    exp = float(cfg.get("plan_expires_at") or 0)
    allp = plans.all_plugins(plan, exp)
    member = plans.is_member(plan, exp) or allp
    return {
        # 微信通道看 member（见 deploy/_env 与 wechat_state）；full 只作兼容保留
        "full": allp,
        "member": member,
        "all_plugins": allp,
        "plan": plan,
        "plan_expires_at": exp,
        "email": cfg.get("account_email") or "",
        "reason": "" if member else "QQ 通道可用；微信通道未开通",
    }


def logout() -> None:
    cfg = headless_config.load()
    cfg["account_token"] = ""
    cfg["account_email"] = ""
    cfg["plan"] = "none"
    cfg["plan_expires_at"] = 0
    headless_config.save(cfg)
