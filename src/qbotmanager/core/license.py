# -*- coding: utf-8 -*-
"""AstroSwarm 星群许可证：机器码 / 离线验签 / 联网激活 / 本地存档。

- 机器码：硬盘+CPU+主板序列号哈希（稳定硬件，重装不失效），结果缓存
- 激活码：服务器用 Ed25519 私钥对「产品ID:机器码」签名（base32 分组，填充 = 可省）
- 客户端只内置公钥，可离线验签；首次激活联网上报，之后 30 天宽限复查
"""
import base64
import hashlib
import json
import logging
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

# 与服务器一致
PRODUCT_ID = "qbotmanager-v1"
TRIAL_PRODUCT_ID = "qbotmanager-trial-v1"
PAY_URL = "https://ifdian.net/a/astroswarm"
# 签发站：优先 HTTPS（nginx 把 astroswarm.cn/license/ 反代到 8300），旧明文地址只作回退
SERVER_URL = "https://astroswarm.cn/license"
SERVER_URL_FALLBACKS = ()   # 公开代码里不放明文 IP；签发站统一走 https://astroswarm.cn/license
SERVER_WEB = "https://astroswarm.cn"
PUBLIC_KEY_HEX = "904bcb7bdfa60d0d129157032844730c6bfc0ee0d76ba43154a64d59d4b09415"
GRACE_DAYS = 30           # 买断密钥的联网复查窗口（天）
TRIAL_RECHECK_DAYS = 7    # 试用密钥的联网复查窗口（天）
OFFLINE_GRACE_DAYS = 7    # 复查窗口已过但仍连不上服务器时的宽限期（天），期间照常可用

_MACHINE_CACHE: str | None = None
logger = logging.getLogger("qbotmanager")


def _appdata_dir() -> Path:
    base = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
    d = base / "QBotManager"
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger.warning("写入许可证失败: %s", e)
    return d


def license_file() -> Path:
    return _appdata_dir() / "license.json"


# ---------------------------------------------------------------- 机器码
def machine_code() -> str:
    """稳定硬件指纹：磁盘序列号 + CPU ID + 主板序列号 -> SHA256 前 32 位。

    结果缓存（进程内只算一次）；子进程调用禁止弹出控制台窗口。
    """
    global _MACHINE_CACHE
    if _MACHINE_CACHE:
        return _MACHINE_CACHE
    parts = []
    try:
        ps = (
            "(Get-CimInstance Win32_DiskDrive | Select-Object -First 1).SerialNumber;"
            "(Get-CimInstance Win32_Processor | Select-Object -First 1).ProcessorId;"
            "(Get-CimInstance Win32_BaseBoard | Select-Object -First 1).SerialNumber"
        )
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True, text=True, timeout=20,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        for line in (r.stdout or "").splitlines():
            s = line.strip()
            if s and s.lower() not in ("none", "null", "default string", ""):
                parts.append(s)
    except Exception as e:  # noqa: BLE001
        logger.warning("机器码采集失败（回退卷序列号）: %s", e)
    if not parts:
        try:
            import ctypes
            buf = ctypes.create_unicode_buffer(261)
            ctypes.windll.kernel32.GetVolumeInformationW(
                "C:\\", buf, 261, None, None, None, None, 0)
            if buf.value:
                parts.append(buf.value)
        except Exception as e:  # noqa: BLE001
            logger.warning("卷序列号采集失败，使用 unknown 机器码: %s", e)
    raw = "|".join(parts) or "unknown"
    h = hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()[:32].upper()
    _MACHINE_CACHE = "-".join(h[i:i + 4] for i in range(0, len(h), 4))
    return _MACHINE_CACHE


# ---------------------------------------------------------------- 验签
def _decode_key(key: str) -> bytes:
    """解码激活码：忽略分组符与大小写，自动补全 base32 填充（末尾 = 可省）。"""
    raw = (key or "").replace("-", "").strip().upper().rstrip("=")
    raw += "=" * (-len(raw) % 8)
    return base64.b32decode(raw)


def _trial_parts(key: str):
    """解析 TR1 试用密钥 -> (签名 bytes, 到期秒数)；格式不对返回 None。"""
    cleaned = (key or "").strip().upper().replace(" ", "")
    tokens = [t for t in cleaned.split("-") if t]
    if not tokens or tokens[0] != "TR1":
        return None
    exp_text = tokens[-1]
    if not exp_text.isdigit():
        return None
    sig_b32 = "".join(tokens[1:-1])
    if len(sig_b32) < 80:
        return None
    try:
        sig = base64.b32decode(sig_b32 + "=" * (-len(sig_b32) % 8))
    except Exception:  # noqa: BLE001
        return None
    return sig, int(exp_text)


def verify_key_details(machine_id: str, key: str, now: float | None = None) -> dict:
    """验签（兼容永久密钥与 TR1 试用密钥）。

    返回 {ok, reason, expires_at, remaining_days}；永久密钥 expires_at=None。
    """
    from nacl.signing import VerifyKey
    key = (key or "").strip()
    try:
        vk = VerifyKey(bytes.fromhex(PUBLIC_KEY_HEX))
        vk.verify(f"{PRODUCT_ID}:{machine_id}".encode(), _decode_key(key))
        return {"ok": True, "reason": "", "expires_at": None, "remaining_days": None}
    except Exception:  # noqa: BLE001
        pass
    parts = _trial_parts(key)
    if not parts:
        return {"ok": False, "reason": "激活码无效", "expires_at": None, "remaining_days": None}
    sig, exp = parts
    try:
        vk = VerifyKey(bytes.fromhex(PUBLIC_KEY_HEX))
        vk.verify(f"{TRIAL_PRODUCT_ID}:{machine_id}:{exp}".encode(), sig)
    except Exception:  # noqa: BLE001
        return {"ok": False, "reason": "激活码无效或与这台电脑不匹配",
                "expires_at": float(exp), "remaining_days": None}
    now = time.time() if now is None else now
    if now > exp:
        return {"ok": False, "reason": "激活码已过期",
                "expires_at": float(exp), "remaining_days": 0}
    days = max(0, int((exp - now + 86399) // 86400))
    return {"ok": True, "reason": "", "expires_at": float(exp), "remaining_days": days}


def verify_key_offline(machine_id: str, key: str) -> bool:
    return verify_key_details(machine_id, key)["ok"]


# ---------------------------------------------------------------- 本地存档
def load_license() -> dict | None:
    p = license_file()
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if data.get("machine_id") and data.get("key"):
            return data
    except (ValueError, OSError) as e:
        logger.warning("读取许可证失败: %s", e)
    return None


def save_license(data: dict):
    p = license_file()
    try:
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as e:
        logger.warning("清除许可证失败: %s", e)


def clear_license():
    try:
        p = license_file()
        if p.exists():
            p.unlink()
    except OSError as e:
        logger.warning("清除许可证失败: %s", e)


# 付费门禁的服务器签名。规范文本两端必须一字不差。
ENTITLEMENT_PREFIX = "QBM-ENT1"


def entitlement_payload(machine_id: str, plan, plan_expires_at=0, owned_plugins=None) -> str:
    """权益签名覆盖的规范文本：QBM-ENT1|<机器码>|<plan>|<到期秒>|<已购插件,逗号排序>。"""
    owned = ",".join(sorted(
        str(x).strip() for x in (owned_plugins or []) if str(x).strip()))
    return "{}|{}|{}|{}|{}".format(
        ENTITLEMENT_PREFIX, str(machine_id or "").strip(),
        str(plan or "none").strip().lower(),
        int(float(plan_expires_at or 0)), owned)


def verify_entitlement(lic: dict | None = None) -> bool:
    """校验本地 plan / 已购插件是否带服务器 Ed25519 签名。

    feature_gate() 不能只信本地 JSON：记事本改一行 plan 就能解锁；
    现在没有有效签名一律按免费版处理（fail closed）。
    """
    lic = load_license() if lic is None else lic
    if not lic:
        return False
    sig = str(lic.get("plan_sig") or "").strip()
    if not sig:
        return False
    # 用服务器签的那台机器（save_plan 时存下来的），不再回退本机 machine_code()：
    # 这样"账号在本机同步过"才算数，换机器复制 license.json 不会自动生效。
    payload = entitlement_payload(
        lic.get("plan_machine") or "",
        lic.get("plan"), lic.get("plan_expires_at"), lic.get("owned_plugins"))
    try:
        from nacl.signing import VerifyKey

        VerifyKey(bytes.fromhex(PUBLIC_KEY_HEX)).verify(payload.encode(), base64.b64decode(sig))
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning("权益签名校验失败（按免费版处理）: %s", e)
        return False


def save_plan(plan: str, plan_expires_at: float = 0, owned_plugins=None,
              sig: str = "", machine_id: str = ""):
    """记录账号授权档位（permanent / monthly / trial）与单独购买的插件。

    `sig` 是账号服务用发码私钥对 entitlement_payload(...) 的 base64 签名；
    没有它 feature_gate()/entitlements() 一律按免费版 —— 光改本地 JSON 不再能解锁。
    """
    data = {}
    try:
        p = license_file()
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8")) or {}
    except (ValueError, OSError):
        data = {}
    data["plan"] = (plan or "trial").strip().lower()
    data["plan_expires_at"] = float(plan_expires_at or 0)
    if owned_plugins is not None:
        data["owned_plugins"] = [
            str(x).strip() for x in owned_plugins if str(x).strip()]
    else:
        data.setdefault("owned_plugins", [])
    data["plan_sig"] = str(sig or "").strip()
    data["plan_machine"] = str(machine_id or "").strip() or machine_code()
    save_license(data)


def save_entitlements_from_account(data: dict) -> bool:
    """把账号服务返回的权益（/me、/redeem、program-sync 都是这套字段名）落到本机。

    **没有签名就不写**：签名决定付费能力是否生效，而账号服务有些响应不带
    entitlement_sig（比如没登录权益、或这次没下发）。以前桌面端直接
    save_plan(..., sig=data.get("entitlement_sig") or "")，一次例行同步就把本机
    已有的好签名抹成空 -> 付费插件/微信通道当场掉回免费版，用户以为"买的白买了"。
    返回值 = 这次是否真的写入了新权益。
    """
    if not isinstance(data, dict):
        return False
    sig = str(data.get("entitlement_sig") or data.get("sig") or "").strip()
    if not sig:
        return False
    save_plan(
        str(data.get("plan") or "none"),
        data.get("plan_expires_at") or 0,
        data.get("owned_plugins"),
        sig=sig,
        machine_id=data.get("entitlement_machine") or data.get("machine_id")
        or machine_code())
    return True


def entitlements() -> dict:
    """插件商店权益：当前账号 plan / 是否会员 / 单独购买的插件列表。

    字段必须通过服务器签名校验；校验不过按免费版（连已购插件也不认）。

    - `all_plugins` / `full` = 解锁**全部付费能力包**：只有 plans.json 里该档
      all_plugins=true（目前只有 permanent）且未过期才为真；
    - `member` = 付费会员档且未过期（解锁微信等付费通道）；trial 不算会员。
    """
    lic = load_license() or {}
    if not verify_entitlement(lic):
        return {"plan": "none", "plan_expires_at": 0, "full": False,
                "member": False, "all_plugins": False, "owned_plugins": []}
    plan = str(lic.get("plan") or "none").lower()
    plan_exp = float(lic.get("plan_expires_at") or 0)
    allp, member = _plan_flags(plan, plan_exp, lic)
    owned = [
        str(x).strip() for x in (lic.get("owned_plugins") or []) if str(x).strip()
    ]
    return {
        "plan": plan,
        "plan_expires_at": plan_exp,
        "full": allp,
        "all_plugins": allp,
        "member": member,
        "owned_plugins": owned,
    }


def _plan_flags(plan: str, plan_exp: float, lic: dict) -> tuple:
    """按 plans.json 判两个互不替代的口径：(解锁全部付费包, 是否付费会员)。

    到期判断用本地时钟 + license 里的服务器时间偏移（_effective_now），
    不直接用 time.time()，避免改本机时间变相续期。
    """
    from . import plans as plans_mod

    alive = plan_exp <= 0 or plan_exp > _effective_now(lic)
    allp = bool(plans_mod.allows_all(plan) and alive)
    member = bool(plan in plans_mod.MEMBER_PLANS and alive) or allp
    return allp, member


def feature_gate() -> dict:
    """功能闸门：邮箱账号授权，不再需要激活码。

    - `full` / `all_plugins` = 解锁**全部付费能力包**（只有 plans.json 里
      all_plugins=true 的档位，目前只有 permanent）；
    - `member` = 付费会员档且未过期，微信等付费通道看它；trial 不算会员。
    """
    lic = load_license() or {}
    # 没签名（或签名不对）一律免费版：改本地 plan 不再是「付费后解锁微信」
    if not verify_entitlement(lic):
        return {"full": False, "member": False, "all_plugins": False,
                "plan": "none", "plan_expires_at": 0,
                "reason": "免费版仅支持 QQ 机器人，付费后解锁微信（权益未通过签名校验）"}
    plan = str(lic.get("plan") or "trial").lower()
    plan_exp = float(lic.get("plan_expires_at") or 0)
    allp, member = _plan_flags(plan, plan_exp, lic)
    return {
        "full": allp,
        "member": member,
        "all_plugins": allp,
        "plan": plan,
        "plan_expires_at": plan_exp,
        "reason": "" if member else "免费版仅支持 QQ 机器人，付费后解锁微信",
    }


# ---------------------------------------------------------------- 联网
def _last_good_server() -> str:
    """上次成功联网用的签发站地址（记在 license.json 的 server 字段），下次优先用它。"""
    try:
        return str((load_license() or {}).get("server") or "")
    except Exception:  # noqa: BLE001
        return ""


def _server_candidates() -> list:
    """签发站候选地址：环境变量 > 上次成功 > 内置 HTTPS > 内置明文（老地址回退）。"""
    urls: list = []

    def _add(u):
        u = str(u or "").strip().rstrip("/")
        if u and u not in urls:
            urls.append(u)

    _add(os.environ.get("QBM_LICENSE_SERVER", ""))
    _add(_last_good_server())
    _add(SERVER_URL)
    for u in SERVER_URL_FALLBACKS:
        _add(u)
    return urls


def _post_json(url: str, payload: dict, timeout: int = 8) -> dict:
    """POST JSON 并返回 dict；网络层异常原样抛出，交给调用方归类。"""
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8", errors="replace"))
    return data if isinstance(data, dict) else {}


def online_activate(machine_id: str, key: str) -> dict:
    """POST /activate。按候选地址依次尝试；全部失败返回 {"ok": False, "network": True}。"""
    payload = {"machine_id": machine_id, "license": key}
    last_err = "无可用地址"
    for base in _server_candidates():
        try:
            data = _post_json(base + "/activate", payload, timeout=8)
        except Exception as e:  # noqa: BLE001
            last_err = f"{base} -> {e}"
            continue
        data["_server"] = base
        return data
    return {"ok": False, "reason": "无法连接激活服务器: " + last_err, "network": True}


def _effective_now(lic: dict) -> float:
    """本地时间 + 最近一次联网校准的服务器时间差，防系统时间回拨绕过到期。

    偏移量封顶 ±1 天：否则手工把 license.json 的 time_offset 改大就能变相续期。
    """
    try:
        offset = float(lic.get("time_offset") or 0)
    except (TypeError, ValueError):
        offset = 0.0
    offset = max(-86400.0, min(86400.0, offset))
    return time.time() + offset


def _touch_online(lic: dict, online: dict):
    """联网验证成功：记录校验时间、服务器时间差与服务器返回的到期时间。"""
    now = time.time()
    lic["last_check"] = now
    lic["last_online"] = now
    server_time = online.get("server_time")
    if server_time:
        lic["time_offset"] = float(server_time) - now
    if online.get("expires_at"):
        lic["expires_at"] = online["expires_at"]
    if online.get("_server"):
        lic["server"] = online["_server"]
    save_license(lic)


# ---------------------------------------------------------------- 状态
def status() -> dict:
    lic = load_license()
    mid = machine_code()
    if not lic:
        return {"activated": False, "machine_id": mid, "key": "",
                "reason": "未激活", "revoked": False}
    details = verify_key_details(mid, lic.get("key", ""), now=_effective_now(lic))
    if not details["ok"]:
        return {"activated": False, "machine_id": mid, "key": lic.get("key", ""),
                "reason": details["reason"] or "激活码与当前电脑不匹配（可能更换了硬件）",
                "revoked": False}
    expires_at = details.get("expires_at")
    remaining_days = details.get("remaining_days")
    if expires_at is not None and remaining_days == 0:
        return {"activated": False, "machine_id": mid, "key": lic.get("key", ""),
                "reason": "免费版（仅 QQ 通道）", "revoked": False}
    last = float(lic.get("last_check") or 0)
    grace_days = (time.time() - last) / 86400.0
    return {
        "activated": True, "machine_id": mid, "key": lic.get("key", ""),
        "reason": "", "revoked": False,
        "grace_remaining": max(0.0, GRACE_DAYS - grace_days),
        "expires_at": expires_at,
        "remaining_days": remaining_days,
        "trial": expires_at is not None,
    }


# ---------------------------------------------------------------- 激活
def _sanitize_key(key: str) -> str:
    """清洗激活码：只保留字母数字与 - =，去掉前缀/换行/空格等干扰。"""
    return re.sub(r"[^A-Za-z0-9=-]", "", key or "").strip()


def _log_attempt(mid: str, key: str, offline: bool, result: dict):
    try:
        f = _appdata_dir() / "activate.log"
        with open(f, "a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} mid={mid} "
                     f"key_len={len(key)} offline={offline} result={result}\n")
    except Exception:  # noqa: BLE001
        pass


def activate(key: str) -> dict:
    """用户输入激活码：清洗 -> 离线验签 -> 联网上报。成功返回 {"ok": True}。"""
    key = _sanitize_key(key)
    mid = machine_code()
    if not key:
        _log_attempt(mid, key, False, {"ok": False, "reason": "请输入激活码"})
        return {"ok": False, "reason": "请输入激活码"}
    details = verify_key_details(mid, key)
    if not details["ok"]:
        result = {"ok": False, "reason": details["reason"]}
        _log_attempt(mid, key, False, result)
        return result
    expires_at = details.get("expires_at")
    remaining_days = details.get("remaining_days")
    online = online_activate(mid, key)
    if online.get("ok"):
        now = time.time()
        save_license({"machine_id": mid, "key": key, "activated_at": time.time(),
                      "last_check": now, "last_online": now,
                      "expires_at": online.get("expires_at") or expires_at,
                      "server": online.get("_server") or "",
                      "time_offset": (float(online["server_time"]) - now)
                      if online.get("server_time") else 0})
        result = {"ok": True, "reason": "激活成功",
                  "expires_at": expires_at, "remaining_days": remaining_days}
        _log_attempt(mid, key, False, result)
        return result
    if online.get("network"):
        # 网络失败：允许暂存，但试用密钥下次启动必须联网复查，防止离线拖过期
        now = time.time()
        save_license({"machine_id": mid, "key": key, "activated_at": time.time(),
                      "last_check": now,
                      "last_online": 0 if expires_at is not None else now,
                      "expires_at": expires_at})
        result = {"ok": True, "reason": "离线激活（暂未联网验证）",
                  "expires_at": expires_at, "remaining_days": remaining_days}
        _log_attempt(mid, key, False, result)
        return result
    result = {"ok": False, "reason": online.get("reason", "激活失败")}
    _log_attempt(mid, key, False, result)
    return result


def redeem_trial(code: str) -> dict:
    """网站个人中心领取的试用码 + 本机机器码 -> 签发并激活 30 天试用。"""
    mid = machine_code()
    payload = json.dumps({"code": (code or "").strip(), "machine_id": mid}).encode("utf-8")
    req = urllib.request.Request(
        SERVER_WEB + "/api/account/trial/redeem", data=payload,
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "reason": "无法连接星群服务器: " + str(e), "network": True}
    if not data.get("ok"):
        detail = data.get("detail") or data.get("reason") or "兑换失败"
        if isinstance(detail, list):
            detail = "输入格式不正确"
        return {"ok": False, "reason": str(detail)}
    result = activate(data.get("license", ""))
    if result.get("ok"):
        result["remaining_days"] = data.get("remaining_days") or result.get("remaining_days")
    return result


def auto_trial() -> dict:
    """首次安装免激活：上报机器码，服务器自动签发 14 天试用密钥并激活。"""
    mid = machine_code()
    payload = {"machine_id": mid}
    data = None
    last_err = "无可用地址"
    for base in _server_candidates():
        try:
            data = _post_json(base + "/trial/auto", payload, timeout=15)
            break
        except urllib.error.HTTPError as e:
            try:
                data = json.loads(e.read().decode("utf-8", errors="replace"))
                break
            except Exception:  # noqa: BLE001
                last_err = f"{base} -> HTTP {e.code}"
        except Exception as e:  # noqa: BLE001
            last_err = f"{base} -> {e}"
    if not isinstance(data, dict):
        return {"ok": False, "reason": "无法连接激活服务器: " + last_err, "network": True}
    if not data.get("ok"):
        detail = data.get("reason") or data.get("detail") or "试用申请失败"
        return {"ok": False, "reason": str(detail)}
    result = activate(data.get("license", ""))
    if result.get("ok"):
        result["remaining_days"] = data.get("remaining_days") or result.get("remaining_days")
    return result


def check_startup() -> dict:
    """启动检查（联网加固）：到期/复查窗口过期必须联网验证，否则拒绝使用。"""
    st = status()
    if not st.get("activated"):
        return st
    lic = load_license() or {}
    now = time.time()
    last_check = float(lic.get("last_check") or 0)
    # 系统时间被回拨：强制联网校准；连不上就拒绝
    if last_check and now < last_check - 3600:
        online = online_activate(st["machine_id"], st["key"])
        if online.get("ok"):
            _touch_online(lic, online)
            return status()
        return {"activated": False, "machine_id": st["machine_id"],
                "key": st.get("key", ""), "reason": "系统时间异常，请校准时间并联网后重试",
                "revoked": False}
    # 试用密钥 7 天、永久密钥 30 天必须联网复查一次
    offline_window = (
        TRIAL_RECHECK_DAYS if st.get("remaining_days") is not None else GRACE_DAYS
    ) * 86400
    last_online = float(lic.get("last_online") or lic.get("last_check") or 0)
    if now - last_online < offline_window:
        return st
    online = online_activate(st["machine_id"], st["key"])
    if online.get("ok"):
        _touch_online(lic, online)
        return status()
    if online.get("revoked") or (not online.get("network") and not online.get("ok")):
        st["activated"] = False
        st["reason"] = online.get("reason", "激活已被封禁")
        st["revoked"] = True
        return st
    # 复查窗口已过且连不上服务器：先给宽限期（网络抖动/服务器故障不该把正版用户挡在门外），
    # 超过宽限期才拒绝离线使用，防止过期/封禁密钥无限期离线续命
    overdue_days = (now - last_online) / 86400.0
    limit_days = offline_window / 86400.0 + OFFLINE_GRACE_DAYS
    if overdue_days <= limit_days:
        st["activated"] = True
        st["grace_warn"] = True
        days_left = max(0, int(limit_days - overdue_days + 0.999))
        st["reason"] = f"暂时连不上激活服务器，已进入宽限期（还剩 {days_left} 天，请尽快联网）"
        logger.warning("联网复查失败，进入宽限期：%s", st["reason"])
        return st
    st["activated"] = False
    st["reason"] = "联网验证超期，请连接网络后重新启动程序"
    st["revoked"] = False
    return st
