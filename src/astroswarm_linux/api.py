"""AstroSwarm headless 控制 API + React 控制台托管。"""
import json
import logging
import os
import secrets
import time
import urllib.request
from pathlib import Path

from fastapi import FastAPI
from fastapi import HTTPException
from fastapi import Header as FastAPIHeader
from fastapi import Request
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from qbotmanager.core import ai_config
from qbotmanager.core import tool_packs as tool_packs_mod

from . import (
    __version__,
    auth,
    deploy,
    headless_config,
    logs,
    platform_info,
    plugins,
    services,
    tools,
)

app = FastAPI(title="AstroSwarm Headless", version=__version__)


@app.get("/health")
def health():
    """探活接口（客户端/nginx 只用它判断服务活着没）。

    未登录只回 ok/version。machine_id 是权益签名的绑定字段，不给未鉴权的请求。
    """
    return {
        "ok": True,
        "service": "astroswarm-headless",
        "version": __version__,
        "linux": platform_info.is_linux(),
    }


@app.get("/api/status")
def status(authorization: str = FastAPIHeader("", alias="Authorization")):
    """未登录只回最小信息；本机路径/机器码等只给已登录的控制台。

    未登录只回 ok/version；data_home / config_home / 机器码要登录后才给。
    """
    try:
        _require_auth(authorization)
        authed = True
    except HTTPException:
        authed = False
    if not authed:
        return {"ok": True, "version": __version__}
    return {
        "ok": True,
        "version": __version__,
        "machine_id": platform_info.machine_id(),
        "data_home": str(platform_info.data_home()),
        "config_home": str(platform_info.config_home()),
        "log_home": str(platform_info.log_home()),
        "services": {"bot": "pending", "dsh": "pending"},
    }


class LoginBody(BaseModel):
    email: str
    password: str


class ClaimBody(BaseModel):
    machine_id: str


class ServiceBody(BaseModel):
    service: str


class PersonalityBody(BaseModel):
    personality: str


class ToolInstallBody(BaseModel):
    id: str


@app.post("/api/auth/login")
def auth_login(body: LoginBody, request: Request):
    # 限流桶按真实来源 IP 建：用常量 key 时，一个人打几次就能把所有人（含机主）锁在门外。
    client_ip = _client_ip(request)
    _login_rate_limit(client_ip)
    try:
        # 透传真实来访 IP：无头端是从本机再 POST 一次账号服务，不带转发头的话
        # 账号服务只看到 127.0.0.1，所有控制台登录会共用一个限流桶。
        result = auth.login(body.email.strip(), body.password, client_ip=client_ip)
        result["token"] = str(headless_config.load().get("account_token") or "")
        return result
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(401, f"登录失败：{exc}")


@app.post("/api/auth/claim")
def auth_claim(
    body: ClaimBody,
    authorization: str = FastAPIHeader("", alias="Authorization"),
):
    _require_auth(authorization)
    try:
        return auth.claim(body.machine_id.strip())
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, str(exc))


@app.post("/api/auth/logout")
def auth_logout(authorization: str = FastAPIHeader("", alias="Authorization")):
    _require_auth(authorization)
    auth.logout()
    return {"ok": True}


@app.get("/api/auth/status")
def auth_status(authorization: str = FastAPIHeader("", alias="Authorization")):
    """未登录只回「没登录」；账号邮箱/套餐/已购插件只给已登录的控制台。

    未登录不返回本机账号邮箱与套餐。

    未登录分支与 auth.feature_gate() 保持同一组字段（含 member / all_plugins）：
    前端按 member 判「会员」、按 all_plugins 判「能不能装付费包」，少一个字段
    就会被读成 undefined，界面会退回「免费版」。
    """
    try:
        _require_auth(authorization)
    except HTTPException:
        return {"full": False, "member": False, "all_plugins": False,
                "plan": "none", "plan_expires_at": 0,
                "email": "", "logged_in": False, "reason": "未登录"}
    return auth.feature_gate()


@app.get("/api/config")
def get_config(authorization: str = FastAPIHeader("", alias="Authorization")):
    _require_auth(authorization)
    cfg = headless_config.load()
    out = {}
    for key in headless_config.SAFE_KEYS:
        value = cfg.get(key)
        out[key] = _mask(value) if key in SECRET_FIELDS and value else value
    # 配置坏过要让前端看得见，否则界面一切正常，用户不知道登录态是从坏文件里抢救的。
    for key in ("_config_error", "_config_backup", "_config_last_good"):
        if cfg.get(key):
            out[key] = str(cfg[key])
    if cfg.get("_config_rescued"):
        out["_config_rescued"] = list(cfg["_config_rescued"])
    return out


@app.post("/api/config/restore-last-good")
def post_config_restore(authorization: str = FastAPIHeader("", alias="Authorization")):
    """把上一份好配置（config.json.bak）回滚回来。

    回滚到上一份能正常解析的配置（需登录）。日志里提示的 restore_last_good() 就是这个入口。
    """
    _require_auth(authorization)
    result = headless_config.restore_last_good()
    if not result.get("ok"):
        raise HTTPException(400, result.get("error") or "回滚失败")
    return result


@app.put("/api/config")
def put_config(body: dict, authorization: str = FastAPIHeader("", alias="Authorization")):
    _require_auth(authorization)
    cfg = headless_config.load()
    for key, cast in headless_config.SAFE_KEYS.items():
        if key in body:
            try:
                value = body[key]
                if (
                    key in SECRET_FIELDS
                    and isinstance(value, str)
                    and (value.startswith("****") or not value.strip())
                    and str(cfg.get(key) or "")
                ):
                    continue
                cfg[key] = cast(value)
            except Exception:  # noqa: BLE001
                raise HTTPException(400, f"{key} 格式不正确")
    headless_config.save(cfg)
    out = {}
    for key in headless_config.SAFE_KEYS:
        value = cfg.get(key)
        out[key] = _mask(value) if key in SECRET_FIELDS and value else value
    return out


@app.get("/api/services/status")
def services_status(authorization: str = FastAPIHeader("", alias="Authorization")):
    # 回的是 bot_dir / 日志绝对路径与状态，要登录
    _require_auth(authorization)
    return services.status()


@app.post("/api/services/start")
def services_start(
    body: ServiceBody,
    authorization: str = FastAPIHeader("", alias="Authorization"),
):
    _require_auth(authorization)
    try:
        return services.start(body.service)
    except NotImplementedError as exc:
        raise HTTPException(501, str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, str(exc))


@app.post("/api/services/stop")
def services_stop(
    body: ServiceBody,
    authorization: str = FastAPIHeader("", alias="Authorization"),
):
    _require_auth(authorization)
    try:
        return services.stop(body.service)
    except NotImplementedError as exc:
        raise HTTPException(501, str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, str(exc))


@app.post("/api/services/restart")
def services_restart(
    body: ServiceBody,
    authorization: str = FastAPIHeader("", alias="Authorization"),
):
    _require_auth(authorization)
    try:
        return services.restart(body.service)
    except NotImplementedError as exc:
        raise HTTPException(501, str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, str(exc))


@app.get("/api/ai/personality")
def ai_personality_get(authorization: str = FastAPIHeader("", alias="Authorization")):
    _require_auth(authorization)
    s = deploy.build_settings()
    try:
        text = ai_config.read_personality(s)
    except Exception:  # noqa: BLE001
        text = ""
    return {"ok": True, "personality": str(text or "")}


@app.put("/api/ai/personality")
def ai_personality_put(
    body: PersonalityBody,
    authorization: str = FastAPIHeader("", alias="Authorization"),
):
    _require_auth(authorization)
    text = (body.personality or "").strip()
    if len(text) > 2000:
        raise HTTPException(400, "人格设定最长 2000 字")
    s = deploy.build_settings()
    if not ai_config.save_personality(s, text):
        raise HTTPException(500, "保存失败")
    return {"ok": True, "needs_restart": True}


@app.get("/api/tools/status")
def tools_status(authorization: str = FastAPIHeader("", alias="Authorization")):
    # packs_dir 是绝对路径（未登录者不用知道服务器目录结构）
    _require_auth(authorization)
    return {
        "ok": True,
        "installed": tools.installed(),
        "packs_dir": str(tools.packs_dir()),
    }


@app.get("/api/tools/market")
def tools_market():
    try:
        plugins = _fetch_market()
    except Exception as exc:  # noqa: BLE001 —— 清单拿不到就明确报错，不假装成空市场
        return {"ok": False, "error": str(exc), "packs": []}
    packs = [p for p in plugins if p.get("kind") in ("tool-pack", "behavior-pack")]
    return {"ok": True, "packs": packs}


@app.post("/api/tools/install")
def tools_install(
    body: ToolInstallBody,
    authorization: str = FastAPIHeader("", alias="Authorization"),
):
    _require_auth(authorization)
    entry = next(
        (
            p
            for p in _fetch_market()
            if p.get("id") == body.id
            and p.get("kind") in ("tool-pack", "behavior-pack")
        ),
        None,
    )
    if entry is None:
        raise HTTPException(404, "工具包不存在")
    try:
        return tools.install(entry)
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, str(exc))


@app.post("/api/tools/uninstall")
def tools_uninstall(
    body: ToolInstallBody,
    authorization: str = FastAPIHeader("", alias="Authorization"),
):
    _require_auth(authorization)
    if str(body.id) not in {str(p.get("id")) for p in tools.installed()}:
        raise HTTPException(404, "能力包不存在")
    return tools.uninstall(body.id)


@app.get("/api/qweather/config")
def qweather_config(authorization: str = FastAPIHeader("", alias="Authorization")):
    _require_auth(authorization)
    s = deploy.build_settings()
    cfg = tool_packs_mod.load_qweather_config(s)
    key_path = cfg.get("private_key_path") or ""
    return {
        "ok": True,
        "configured": bool(
            cfg.get("project_id") and cfg.get("credential_id")
            and key_path and Path(key_path).exists()),
        "project_id": cfg.get("project_id") or "",
        "credential_id": cfg.get("credential_id") or "",
        "api_host": cfg.get("api_host") or "",
        "private_key_path": key_path,
    }


@app.post("/api/qweather/generate-key")
def qweather_generate_key(
    authorization: str = FastAPIHeader("", alias="Authorization"),
):
    _require_auth(authorization)
    s = deploy.build_settings()
    cfg = tool_packs_mod.load_qweather_config(s)
    key_path = str(Path(s.root) / "qweather_ed25519_private.pem")
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives import serialization
    except Exception:  # noqa: BLE001
        raise HTTPException(500, "服务器缺少 cryptography，请先安装依赖")
    priv = Ed25519PrivateKey.generate()
    try:
        Path(key_path).parent.mkdir(parents=True, exist_ok=True)
        with open(key_path, "wb") as f:
            f.write(priv.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption()))
        os.chmod(key_path, 0o600)
    except OSError as exc:  # noqa: BLE001
        raise HTTPException(500, f"私钥写入失败: {exc}")
    pub_pem = priv.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    tool_packs_mod.save_qweather_config(
        s, cfg.get("project_id", ""), cfg.get("credential_id", ""), key_path,
        cfg.get("api_host", ""))
    return {"ok": True, "public_key": pub_pem, "private_key_path": key_path}


class QWeatherSaveBody(BaseModel):
    api_host: str = ""
    project_id: str = ""
    credential_id: str = ""


@app.post("/api/qweather/save")
def qweather_save(
    body: QWeatherSaveBody,
    authorization: str = FastAPIHeader("", alias="Authorization"),
):
    _require_auth(authorization)
    s = deploy.build_settings()
    cfg = tool_packs_mod.load_qweather_config(s)
    tool_packs_mod.save_qweather_config(
        s,
        body.project_id or cfg.get("project_id", ""),
        body.credential_id or cfg.get("credential_id", ""),
        cfg.get("private_key_path", ""),
        body.api_host or cfg.get("api_host", ""),
    )
    return {"ok": True}


@app.get("/api/logs/stream")
def logs_stream(
    token: str = "",
    name: str = logs.LOG_FILE_DEFAULT,
    authorization: str = FastAPIHeader("", alias="Authorization"),
):
    """实时日志流。日志里有 AI key / 微信 token / 用户对话，必须鉴权。

    EventSource 不能自定义请求头，所以额外接受 ?token=<登录 token>；
    控制台通过 src/api.js 的 authUrl() 自动拼上。

    `?name=` 选日志来源（headless / nonebot）。**只接受名字，不接受路径**：
    名字到文件的映射在 logs.LOG_FILES 这张白名单里，非法名字直接 400。

    必须用异步生成器（logs.afollow）：同步生成器交给 StreamingResponse 会走
    anyio.to_thread，日志空闲时线程卡在 next() 里，客户端断开也收不回（每次断开漏一个线程）。
    afollow 在事件循环上等待，取消立刻生效，并自带 10 分钟上限（到点结束，前端重连）。
    """
    _require_auth(token or authorization)
    try:
        src, log_path = logs.resolve_log(name)
    except ValueError:
        raise HTTPException(400, f"未知的日志名，只能是：{logs.LOG_NAME_LIST}") from None

    async def gen():
        yield "data: " + logs.tail(log_path, 200).replace("\n", "\ndata: ") + "\n\n"
        async for chunk in logs.afollow(log_path):
            yield "data: " + chunk.replace("\n", "\ndata: ") + "\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


def _console_dist() -> Path:
    """控制台前端产物目录。

    控制台前端产物的查找顺序：环境变量 → 代码包旁的 console-dist → 开发机默认路径。
    都没有时 `GET /` 直接 404，所以这个顺序必须覆盖安装脚本铺产物的位置。
    """
    env = os.environ.get("ASTROSWARM_CONSOLE_DIST", "").strip()
    if env:
        return Path(env)
    here = Path(__file__).resolve()
    for base in (here.parents[1], here.parents[2]):      # <安装目录>/console-dist
        cand = base / "console-dist"
        if cand.exists():
            return cand
    return here.parents[2] / "console-dist"              # 兜底：不存在时 GET / 会 404 并写日志


CONSOLE_DIST = _console_dist()
# 市场清单走 HTTPS + Ed25519 验签（清单地址可用 ASTROSWARM_MARKET_URL 覆盖，
# 自建镜像要把域名加进 QBM_MARKET_ALLOW_HOSTS；签名始终用客户端内置公钥校验）
MARKET_URL = os.environ.get(
    "ASTROSWARM_MARKET_URL", "https://astroswarm.cn/plugins/market.json"
)
_market_cache = {"at": 0.0, "data": []}
_login_hits = {}

SECRET_FIELDS = {"qq_app_secret", "qq_app_token", "ai_api_key", "vision_api_key"}


def _mask(value) -> str:
    value = str(value or "")
    if not value:
        return ""
    return "****" + (value[-4:] if len(value) > 4 else "")


def _require_auth(authorization: str) -> None:
    token = (authorization or "").removeprefix("Bearer ").strip()
    expected = str(headless_config.load().get("account_token") or "")
    if not expected or not token or not secrets.compare_digest(expected, token):
        raise HTTPException(401, "请先登录")


def _login_rate_limit(ip: str) -> None:
    now = time.time()
    lst = [t for t in _login_hits.get(ip, []) if now - t < 60]
    if len(lst) >= 5:
        raise HTTPException(429, "登录尝试过于频繁，请稍后再试")
    lst.append(now)
    _login_hits[ip] = lst


def _client_ip(request) -> str:
    """真实客户端 IP：只有对端是本机（nginx 反代）时才信转发头。

    为什么不能无条件信 XFF：服务直接暴露时任何人伪造一个 XFF 就能绕过限流，
    等于没限流；而只信 socket 对端的话，反代后面所有用户又共用一个桶。

    取 XFF 的**最后一段**，并优先用 nginx 的 X-Real-IP。
    nginx 用的是 `$proxy_add_x_forwarded_for`（客户端自带值 + 真实 IP 追加在末尾），首段
    完全由调用方控制 —— 取首段等于伪造一个 X-Forwarded-For 就能无限次试密码。
    """
    peer = str(getattr(getattr(request, "client", None), "host", "") or "")
    if peer in ("127.0.0.1", "::1", "localhost"):
        headers = getattr(request, "headers", None)
        real = str(headers.get("x-real-ip") or "").strip() if headers is not None else ""
        if real:
            return real
        xff = str(headers.get("x-forwarded-for") or "") if headers is not None else ""
        segments = [s.strip() for s in xff.split(",") if s.strip()]
        if segments:
            return segments[-1]
    return peer or "unknown"


def _fetch_market() -> list:
    now = time.time()
    if _market_cache["data"] and now - _market_cache["at"] < 60:
        return _market_cache["data"]
    from qbotmanager.core import plugin_market

    plugins = plugin_market.fetch_market(MARKET_URL, timeout=10)
    if not plugins:
        raise RuntimeError(
            plugin_market.LAST_ERROR or "插件市场清单不可用（签名校验失败或网络不通）"
        )
    _market_cache.update(at=now, data=plugins)
    return plugins


@app.get("/api/plugins")
def plugins_list():
    try:
        items = [
            p for p in _fetch_market() if p.get("kind") != "tool-pack"
        ]
        return {"ok": True, "plugins": items}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc), "plugins": []}


@app.post("/api/plugins/install")
def plugins_install(
    body: dict,
    authorization: str = FastAPIHeader("", alias="Authorization"),
):
    _require_auth(authorization)
    entry = next(
        (
            p
            for p in _fetch_market()
            if p.get("id") == body.get("id") and p.get("kind") != "tool-pack"
        ),
        None,
    )
    if entry is None:
        raise HTTPException(404, "插件不存在")
    try:
        result = plugins.install(entry)
        services.restart("bot")
        return result
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, str(exc))


@app.post("/api/plugins/uninstall")
def plugins_uninstall(
    body: dict,
    authorization: str = FastAPIHeader("", alias="Authorization"),
):
    _require_auth(authorization)
    pid = str(body.get("id") or "")
    # 不存在的 id 直接 404：不要返回 ok，也不要顺手把机器人重启一遍
    if pid not in {str(p.get("id")) for p in plugins.installed()}:
        raise HTTPException(404, "插件不存在")
    try:
        result = plugins.uninstall(pid)
        services.restart("bot")
        return result
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, str(exc))


# 控制台 1:1 之后补的接口（已装插件清单 / 依赖扫描与安装 / 日志下载）。
# 必须挂在 StaticFiles 之前：它挂在 "/" 上，后注册的路由永远匹配不到。
from . import console_ext  # noqa: E402

console_ext.register(app)


if CONSOLE_DIST.exists():
    app.mount(
        "/",
        StaticFiles(directory=str(CONSOLE_DIST), html=True),
        name="console",
    )
else:
    # 不再静默：客户机上最可能的原因就是没把前端产物放进来
    logging.getLogger("astroswarm").warning(
        "控制台前端产物目录不存在：%s —— 浏览器打开会 404。"
        "请把 console-dist 放到该路径，或设置 ASTROSWARM_CONSOLE_DIST 指向它。",
        CONSOLE_DIST,
    )

    @app.get("/")
    def _console_missing():
        return {
            "ok": False,
            "error": "控制台前端产物未找到",
            "hint": "把 console-dist 放到 %s，或设置环境变量 ASTROSWARM_CONSOLE_DIST" % CONSOLE_DIST,
        }
