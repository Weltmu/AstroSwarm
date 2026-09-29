"""和风天气查询工具：城市搜索 → 实时天气，返回结构化 JSON（数据层）。

语言表述由 agent 按人设组织，本模块不返回任何中文话术。
配置由星群程序安装引导写入，通过环境变量注入：
    QWEATHER_PROJECT_ID      项目 ID（JWT payload.sub）
    QWEATHER_CREDENTIAL_ID   凭据 ID（JWT header.kid）
    QWEATHER_PRIVATE_KEY_PATH ed25519 私钥文件路径
只支持城市实时天气；台风/辐射/海洋类数据不在范围内。
"""
import json
import os
import time

import httpx

QW_HOST = os.environ.get("QWEATHER_API_HOST", "").strip().rstrip("/")
if QW_HOST and not QW_HOST.startswith(("http://", "https://")):
    QW_HOST = "https://" + QW_HOST


def _jwt() -> str | None:
    """用 Ed25519 私钥签发和风 JWT；配置缺失或失败返回 None。"""
    try:
        import jwt
    except Exception:  # noqa: BLE001
        return None
    project_id = os.environ.get("QWEATHER_PROJECT_ID", "")
    kid = os.environ.get("QWEATHER_CREDENTIAL_ID", "")
    key_path = os.environ.get("QWEATHER_PRIVATE_KEY_PATH", "")
    if not (project_id and kid and key_path):
        return None
    try:
        with open(key_path, encoding="utf-8") as f:
            private_key = f.read()
    except OSError:
        return None
    now = int(time.time())
    try:
        return jwt.encode(
            {"sub": project_id, "iat": now - 30, "exp": now + 900},
            private_key,
            algorithm="EdDSA",
            headers={"kid": kid},
        )
    except Exception:  # noqa: BLE001
        return None


def handle(ctx, args):
    city = str(args.get("city") or "").strip()
    if not city:
        return json.dumps({"ok": False, "error": "missing_city"},
                          ensure_ascii=False)
    if not QW_HOST:
        return json.dumps({"ok": False, "error": "qweather_not_configured"},
                          ensure_ascii=False)
    token = _jwt()
    if not token:
        return json.dumps({"ok": False, "error": "qweather_not_configured"},
                          ensure_ascii=False)
    headers = {"Authorization": f"Bearer {token}"}
    try:
        with httpx.Client(timeout=15, headers=headers) as client:
            geo = client.get(
                QW_HOST + "/geo/v2/city/lookup",
                params={"location": city, "number": 1},
            )
            geo.raise_for_status()
            gj = geo.json()
            if gj.get("code") != "200" or not gj.get("location"):
                return json.dumps(
                    {"ok": False, "error": "city_not_found", "city": city},
                    ensure_ascii=False)
            loc = gj["location"][0]
            loc_id = loc.get("id") or ""
            name = str(loc.get("name") or city)
            admin = str(loc.get("adm1") or "")
            place = f"{name}（{admin}）" if admin else name
            r = client.get(
                QW_HOST + "/v7/weather/now",
                params={"location": loc_id},
            )
            r.raise_for_status()
            wj = r.json()
            if wj.get("code") != "200" or not wj.get("now"):
                return json.dumps(
                    {"ok": False, "error": "weather_api_error",
                     "code": wj.get("code")},
                    ensure_ascii=False)
            d = wj["now"]
            return json.dumps({
                "ok": True,
                "weather": {
                    "city": place,
                    "temp": d.get("temp"),
                    "feels_like": d.get("feelsLike"),
                    "text": d.get("text"),
                    "icon": d.get("icon"),
                    "wind_dir": d.get("windDir"),
                    "wind_scale": d.get("windScale"),
                    "wind_speed": d.get("windSpeed"),
                    "humidity": d.get("humidity"),
                    "precip": d.get("precip"),
                    "pressure": d.get("pressure"),
                    "vis": d.get("vis"),
                    "obs_time": d.get("obsTime"),
                },
            }, ensure_ascii=False)
    except Exception as exc:  # noqa: BLE001
        return json.dumps(
            {"ok": False, "error": "weather_failed", "detail": str(exc)},
            ensure_ascii=False)
