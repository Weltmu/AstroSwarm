# -*- coding: utf-8 -*-
"""官方插件市场：清单拉取/验签/解析、插件校验、manifest 适配器校验、下载 SHA256 校验。

市场清单为 JSON（服务器静态文件 + market.json.sig 签名），支持两种形态：
  [ {id,name,version,category,description,url,sha256,adapters}, ... ]
  { "categories": [...], "plugins": [ ... ] }
清单必须通过 Ed25519 验签（与激活码同一把密钥），且清单/下载地址必须
是 https 且落在 MARKET_ALLOW_HOSTS 白名单里，否则一律拒绝加载与下载。
插件 zip 内须含 <插件名>/plugin.json，manifest 至少声明 id/name/version/adapters；
adapters 必须包含至少一个官方通道标识（qq_official / wechat_ilink），
否则视为不兼容第三方插件拒绝安装。
"""
import base64
import hashlib
import json
import os
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

# 市场清单走 HTTPS，且必须带 Ed25519 签名（与激活码同一把密钥，客户端已内置公钥）
MARKET_DEFAULT_URL = "https://astroswarm.cn/plugins/market.json"
MARKET_SIG_SUFFIX = ".sig"
# 只信任这些主机（https）：清单自身地址 + 清单里的插件下载地址
MARKET_ALLOW_HOSTS = ("astroswarm.cn", "www.astroswarm.cn")
# 最近一次拉取失败的原因（成功时为空串），UI 可以直接展示
LAST_ERROR = ""

# 官方通道标识：QQ 官方机器人 / 微信 iLink（manifest.adapters 声明）
OFFICIAL_ADAPTERS = ("qq_official", "wechat_ilink")

# 商店权益档位：2026-09 起插件全部免费（随主仓库开源），TIER_* 仅作兼容保留（旧清单可能还带 tier 字段）
TIER_FREE = "free"
TIER_MEMBER = "member"
TIER_BUY = "buy"


def market_sig_url(url: str) -> str:
    """清单签名文件地址（detached 签名，覆盖清单原始字节）。"""
    return str(url or "").strip() + MARKET_SIG_SUFFIX


def url_allowed(url: str) -> bool:
    """地址白名单：必须 https + 官方域名（可用 QBM_MARKET_ALLOW_HOSTS 追加，逗号分隔）。"""
    try:
        u = urllib.parse.urlsplit(str(url or "").strip())
    except ValueError:
        return False
    if u.scheme != "https":
        return False
    host = (u.hostname or "").lower()
    if not host:
        return False
    extra = tuple(
        h.strip().lower()
        for h in os.environ.get("QBM_MARKET_ALLOW_HOSTS", "").split(",")
        if h.strip()
    )
    return any(host == h or host.endswith("." + h) for h in MARKET_ALLOW_HOSTS + extra)


def verify_manifest(raw: bytes, sig_text: str, public_key_hex: str | None = None) -> bool:
    """校验市场清单的 Ed25519 detached 签名：签名 base64，覆盖清单原始字节。

    公钥与激活码验签用的是同一把（license.PUBLIC_KEY_HEX），私钥只在签发站。
    """
    from .license import PUBLIC_KEY_HEX

    try:
        sig = base64.b64decode("".join(str(sig_text or "").split()), validate=True)
    except Exception:  # noqa: BLE001
        return False
    if len(sig) != 64:
        return False
    try:
        from nacl.signing import VerifyKey

        VerifyKey(bytes.fromhex(public_key_hex or PUBLIC_KEY_HEX)).verify(bytes(raw), sig)
        return True
    except Exception:  # noqa: BLE001
        return False


def entry_tier(entry: dict) -> str:
    """返回市场条目的权益档位。

    插件已全部免费（2026-09 起随主仓库开源，含清单里还带 tier 的历史条目），
    所以恒为 TIER_FREE；函数名与常量保留是为了兼容旧调用方与旧清单。
    """
    return TIER_FREE


def plugin_access(entry: dict, entitlements: dict | None = None) -> dict:
    """判断当前账号能否安装该插件。

    插件已全部免费（2026-09 起随主仓库开源）：不再看档位 / 买断 / 登录状态，
    任何条目都直接放行。entitlements 参数只为兼容旧调用方保留。
    """
    return {"allowed": True, "reason": "免费", "label": "免费"}


def parse_market(raw: str) -> list:
    """解析市场清单 JSON，返回插件条目列表（过滤缺 id/name 的脏数据）。"""
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return []
    if isinstance(data, dict):
        data = data.get("plugins") or []
    if not isinstance(data, list):
        return []
    out = []
    for item in data:
        if not isinstance(item, dict):
            continue
        if not str(item.get("id") or "").strip() or not str(item.get("name") or "").strip():
            continue
        out.append(item)
    return out


def validate_market_plugin(entry: dict) -> str | None:
    """校验市场条目关键字段；合法返回 None，否则返回错误说明。"""
    for key in ("id", "name", "version", "url", "sha256"):
        if not str(entry.get(key) or "").strip():
            return f"插件缺少字段 {key}"
    if not str(entry.get("url") or "").startswith(("http://", "https://")):
        return "插件下载地址不是 http(s)"
    if not url_allowed(str(entry.get("url") or "")):
        return "插件下载地址不在官方白名单（须 https + astroswarm.cn）"
    return None


def read_plugin_manifest(zip_path) -> dict | None:
    """读取插件 zip 内的 <顶层>/plugin.json；找不到返回 None。"""
    zip_path = Path(zip_path)
    if not zip_path.exists():
        return None
    with zipfile.ZipFile(zip_path) as z:
        for name in z.namelist():
            if name.endswith("plugin.json") and "/" in name:
                try:
                    data = json.loads(z.read(name).decode("utf-8", "ignore"))
                    if isinstance(data, dict):
                        return data
                except (ValueError, KeyError):
                    continue
    return None


def validate_plugin_manifest(manifest: dict | None) -> str | None:
    """校验插件 manifest；合法返回 None，否则返回错误说明。"""
    if not isinstance(manifest, dict):
        return "插件缺少 plugin.json 清单"
    for key in ("id", "name", "version"):
        if not str(manifest.get(key) or "").strip():
            return f"插件清单缺少字段 {key}"
    adapters = manifest.get("adapters")
    if not isinstance(adapters, list) or not any(
            str(a).strip() in OFFICIAL_ADAPTERS for a in adapters):
        return "插件不兼容官方通道（manifest.adapters 需包含 qq_official 或 wechat_ilink）"
    return None


def fetch_market(url: str = MARKET_DEFAULT_URL, timeout: int = 10,
                 opener=None, require_signature: bool = True,
                 public_key_hex: str | None = None) -> list:
    """拉取市场清单 → 验签 → 解析；任何一步失败都返回空列表（不抛给 UI）。

    清单必须带 Ed25519 签名（market.json.sig，与发码同一把密钥）。
    验签不过一律拒绝加载——否则中间人同时改 url 和 sha256 就能投毒。
    失败原因放在 LAST_ERROR 里，UI 可直接展示。
    """
    global LAST_ERROR
    try:
        if require_signature and not url_allowed(url):
            LAST_ERROR = "市场清单地址不在白名单（须 https + astroswarm.cn）：" + str(url)
            return []
        raw = _http_get(url, timeout=timeout, opener=opener)
        if require_signature:
            sig_text = _http_get(market_sig_url(url), timeout=timeout, opener=opener)
            if isinstance(sig_text, (bytes, bytearray)):
                sig_text = sig_text.decode("utf-8", "replace")
            if not verify_manifest(raw, sig_text, public_key_hex):
                LAST_ERROR = "市场清单签名校验失败（可能被篡改），已拒绝加载"
                return []
        LAST_ERROR = ""
    except Exception as e:  # noqa: BLE001 —— 市场不可用不应阻塞页面
        LAST_ERROR = str(e)
        return []
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", "replace")
    return parse_market(raw)


def download_plugin(url: str, dest, sha256: str | None = None,
                    timeout: int = 20, opener=None) -> Path:
    """下载插件 zip 到 dest，可选 SHA256 校验；校验失败抛 RuntimeError。

    未显式传入 opener 时，会自动带上当前登录星群账号的 token，
    使插件下载带上当前登录账号（没登录就是匿名下载，插件已全部免费）。
    """
    dest = Path(dest)
    if not url_allowed(str(url)):
        raise RuntimeError("插件下载地址不在官方白名单（须 https + astroswarm.cn），已拒绝下载")
    if opener is None:
        opener = _authed_opener(timeout)
    try:
        data = _http_get(url, timeout=timeout, opener=opener)
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise RuntimeError(
                "服务器拒绝了这次下载（HTTP 401/403），可稍后重试或到官网插件市场手动下载 zip"
            ) from e
        raise RuntimeError(f"插件下载失败（HTTP {e.code}）") from e
    if sha256:
        actual = hashlib.sha256(data).hexdigest()
        if actual.lower() != str(sha256).strip().lower():
            raise RuntimeError("插件校验失败：SHA256 不匹配（下载可能被篡改）")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return dest


def _account_token() -> str:
    """读取当前登录的星群账号 token：桌面端读 account.json，无头版读 headless 配置。"""
    try:
        from . import account as _account

        data = _account.load_account()
        if data and data.get("token"):
            return str(data["token"])
    except Exception:  # noqa: BLE001
        pass
    try:
        from astroswarm_linux import headless_config

        cfg = headless_config.load()
        token = str(cfg.get("account_token") or "")
        if token:
            return token
    except Exception:  # noqa: BLE001
        pass
    return ""


def _authed_opener(timeout: int = 20):
    """返回带星群账号 Authorization 头的下载 opener（未登录则不带）。"""

    def opener(url):
        req = urllib.request.Request(url, headers={"User-Agent": "AstroSwarm/0.1"})
        token = _account_token()
        if token:
            req.add_header("Authorization", "Bearer " + token)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()

    return opener


def _http_get(url: str, timeout: int, opener=None) -> bytes:
    if opener is not None:
        return opener(url)
    req = urllib.request.Request(url, headers={"User-Agent": "AstroSwarm/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()
