import json
import time
from pathlib import Path

from fastapi.testclient import TestClient

from astroswarm_linux import api, auth, headless_config, logs, platform_info, services
from astroswarm_linux.api import app

client = TestClient(app)


def _auth(monkeypatch, tmp_path, token="test-token"):
    monkeypatch.setattr(platform_info, "config_home", lambda: tmp_path)
    headless_config.save({**headless_config.load(), "account_token": token})
    return {"Authorization": f"Bearer {token}"}


def test_health():
    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True and data["service"] == "astroswarm-headless"
    # 探活接口不再泄露机器码（机器码是权益签名绑定字段，未登录者不该拿到）
    assert "machine_id" not in data, data


def test_status_json():
    res = client.get("/api/status")
    assert res.status_code == 200
    assert res.json()["ok"] is True


def test_index_html():
    """控制台前端产物存在时回 HTML；不存在时回可读的 JSON 提示（不再静默 404）。"""
    res = client.get("/")
    assert res.status_code == 200
    if "AstroSwarm" in res.text:
        return                       # 本机装了 console-dist（开发机）
    data = res.json()
    assert data["ok"] is False and "console-dist" in data["hint"], data


def test_config_roundtrip(tmp_path, monkeypatch):
    headers = _auth(monkeypatch, tmp_path)
    res = client.put(
        "/api/config",
        headers=headers,
        json={"qq_app_id": "123", "port": "7861", "bad_key": "x"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["qq_app_id"] == "123" and data["port"] == 7861
    assert "bad_key" not in data
    cfg = headless_config.load()
    assert cfg["qq_app_id"] == "123" and cfg["port"] == 7861


def test_auth_login_and_feature_gate(tmp_path, monkeypatch):
    headers = _auth(monkeypatch, tmp_path)   # 新鉴权要求：/api/auth/status 现在需要登录
    monkeypatch.setattr(platform_info, "config_home", lambda: tmp_path)
    calls = {}
    # 有效期不能写死时间戳：写死的时间戳一过期，这条用例就会自己烂掉（2026-09-21 踩过）
    exp_future = time.time() + 30 * 86400

    def fake_post(path, body, token=None, client_ip=""):
        calls["path"] = path
        calls["client_ip"] = client_ip
        return {
            "ok": True,
            "email": "buyer@test.local",
            "token": "TOKEN-1",
            "plan": "monthly",
            "plan_expires_at": exp_future,
        }

    monkeypatch.setattr(auth, "_post", fake_post)
    res = client.post(
        "/api/auth/login", json={"email": "buyer@test.local", "password": "x"}
    )
    assert res.status_code == 200, res.text
    assert res.json()["plan"] == "monthly"
    # 登录必须把真实来访 IP 透传给账号服务，否则账号服务只看到
    # 127.0.0.1 → 所有控制台登录共用一个限流桶（谁打错几次就锁全服）。
    assert calls.get("client_ip"), calls
    # 注意：登录成功会把手里的 token 覆盖成服务端返回的那个，所以 header 要在登录之后再取
    hdr = {"Authorization": "Bearer " + str(headless_config.load().get("account_token") or "")}
    # /api/auth/status 现在要登录：未登录只回最小信息（不再泄漏本机账号邮箱）
    gate = client.get("/api/auth/status", headers=hdr).json()
    # 关键回归：光有 plan 字符串**不算**付费权益 —— feature_gate 现在必须验签名。
    # 这个假登录没有服务器签名，所以 full 必须是 False（以前只看本地 JSON，改一行 plan 就解锁）。
    assert gate["full"] is False, gate
    assert "签名" in str(gate.get("reason") or ""), gate
    # 补一个真签名后应当解锁（用账号服务的同一套规范文本）
    from qbotmanager.core.license import entitlement_payload
    from nacl.signing import SigningKey
    import base64

    cfg = headless_config.load()
    key = SigningKey.generate()          # 本地生成一对，公钥换掉客户端内置公钥
    payload = entitlement_payload(cfg.get("entitlement_machine") or "M-TEST",
                                  "monthly", exp_future, [])
    monkeypatch.setattr(
        "qbotmanager.core.license.PUBLIC_KEY_HEX", key.verify_key.encode().hex())
    cfg2 = {**cfg,
            "entitlement_machine": "M-TEST",
            "plan": "monthly",
            "plan_expires_at": exp_future,
            "owned_plugins": [],
            "entitlement_sig": base64.b64encode(key.sign(payload.encode()).signature).decode()}
    headless_config.save(cfg2)
    gate2 = client.get("/api/auth/status", headers=hdr).json()
    # 月费档不是「全解锁」：full=False，
    # 但 member=True（微信等付费通道照常开）。全解锁只有 plans.json 里
    # all_plugins=true 的档位（permanent）。所以月费档下已装付费包仍被冻结，
    # 只有 owned_plugins 里单独买断的才放行。
    assert gate2["full"] is False, gate2
    assert gate2["member"] is True, gate2


def test_auth_claim_requires_login(tmp_path, monkeypatch):
    _auth(monkeypatch, tmp_path)
    res = client.post("/api/auth/claim", json={"machine_id": "M-1"})
    assert res.status_code == 401


def test_status_keeps_machine_id_when_logged_in(tmp_path, monkeypatch):
    """机器码只给已登录的控制台（/health 不再回，/api/status 登录后照旧）。"""
    headers = _auth(monkeypatch, tmp_path)
    data = client.get("/api/status", headers=headers).json()
    assert data["machine_id"] and data["config_home"]


def test_services_status(tmp_path, monkeypatch):
    headers = _auth(monkeypatch, tmp_path)
    assert client.get("/api/services/status").status_code == 401      # bot_dir/日志路径不外泄
    res = client.get("/api/services/status", headers=headers)
    assert res.status_code == 200
    assert res.json()["bot"]["state"] in ("not_installed", "installed", "running")


def test_services_start_stop_mocked(monkeypatch):
    import tempfile
    from pathlib import Path

    tmp = Path(tempfile.mkdtemp(prefix="qbm_api_"))
    headers = _auth(monkeypatch, tmp)
    monkeypatch.setattr(services, "start", lambda service, log=print: {"ok": True, "pid": 1})
    monkeypatch.setattr(services, "stop", lambda service, log=print: {"ok": True})
    start = client.post("/api/services/start", headers=headers, json={"service": "bot"})
    stop = client.post("/api/services/stop", headers=headers, json={"service": "bot"})
    assert start.status_code == 200 and start.json()["pid"] == 1
    assert stop.status_code == 200


def test_ai_personality_get_and_put(monkeypatch):
    import tempfile
    from pathlib import Path

    tmp = Path(tempfile.mkdtemp(prefix="qbm_api_"))
    headers = _auth(monkeypatch, tmp)
    calls = {}
    monkeypatch.setattr(api.ai_config, "read_personality", lambda s: "默认人设")

    def fake_save(s, text):
        calls["text"] = text
        return True

    monkeypatch.setattr(api.ai_config, "save_personality", fake_save)
    res = client.get("/api/ai/personality", headers=headers)
    assert res.status_code == 200
    assert res.json()["personality"] == "默认人设"
    res = client.put("/api/ai/personality", headers=headers, json={"personality": "新人格"})
    assert res.status_code == 200 and res.json()["needs_restart"] is True
    assert calls["text"] == "新人格"
    res = client.put("/api/ai/personality", headers=headers, json={"personality": "x" * 2001})
    assert res.status_code == 400


def test_logs_tail(tmp_path):
    log = tmp_path / "headless.log"
    log.write_text("line1\nline2\nline3\n", encoding="utf-8")
    assert logs.tail(log, n=2) == "line2\nline3\n"


# ============================================ 日志来源（name 白名单，不接受路径）

def test_log_resolve_is_a_whitelist(tmp_path, monkeypatch):
    """?name= 只能给名字，且只能给白名单里的名字 —— 路径穿越连走到文件系统的机会都没有。"""
    monkeypatch.setattr(platform_info, "log_home", lambda: tmp_path)
    home = tmp_path
    home.mkdir(exist_ok=True)
    for bad in ("../../etc/passwd", "/etc/passwd", "..\\..\\win.ini", "headless.log",
                "nonebot.log", "other", "headless/../../x"):
        try:
            logs.resolve_log(bad)
        except ValueError:
            continue
        raise AssertionError(f"非法日志名没有被拒绝：{bad!r}")
    for name, filename in logs.LOG_FILES.items():
        src, path = logs.resolve_log(name)
        assert src == name and path.parent == home and path.name == filename
    # 空 / 缺省 / all 都回落默认来源
    assert logs.resolve_log("")[0] == logs.LOG_FILE_DEFAULT
    assert logs.resolve_log(None)[0] == logs.LOG_FILE_DEFAULT
    assert logs.resolve_log("all")[0] == logs.LOG_FILE_DEFAULT


def test_logs_tail_by_name(tmp_path, monkeypatch):
    headers = _auth(monkeypatch, tmp_path)
    monkeypatch.setattr(platform_info, "data_home", lambda: tmp_path)
    home = tmp_path / "logs"
    home.mkdir(exist_ok=True)
    (home / "headless.log").write_text("manager line\n", encoding="utf-8")
    (home / "nonebot.log").write_text("bot line\n", encoding="utf-8")

    res = client.get("/api/logs/tail", headers=headers)
    assert res.status_code == 200 and res.json()["lines"] == ["manager line"]
    res = client.get("/api/logs/tail?name=nonebot", headers=headers)
    assert res.status_code == 200, res.text
    assert res.json()["name"] == "nonebot" and res.json()["lines"] == ["bot line"]
    # 非法名字 400；匿名 401
    assert client.get("/api/logs/tail?name=../secrets", headers=headers).status_code == 400
    assert client.get("/api/logs/tail?name=bogus", headers=headers).status_code == 400
    assert client.get("/api/logs/tail?name=nonebot").status_code == 401


def test_logs_download_by_name(tmp_path, monkeypatch):
    headers = _auth(monkeypatch, tmp_path)
    monkeypatch.setattr(platform_info, "data_home", lambda: tmp_path)
    home = tmp_path / "logs"
    home.mkdir(exist_ok=True)
    (home / "nonebot.log").write_text("bot tail\n", encoding="utf-8")
    res = client.get("/api/logs/download?name=nonebot", headers=headers)
    assert res.status_code == 200, res.text
    assert "bot tail" in res.text
    assert "nonebot-" in res.headers["content-disposition"]
    assert client.get("/api/logs/download?name=/etc/passwd", headers=headers).status_code == 400
    assert client.get("/api/logs/download?name=/etc/passwd").status_code == 401   # 先鉴权


def test_logs_stream_by_name_and_bad_name(tmp_path, monkeypatch):
    headers = _auth(monkeypatch, tmp_path)
    monkeypatch.setattr(platform_info, "data_home", lambda: tmp_path)
    (tmp_path / "logs").mkdir(exist_ok=True)
    assert client.get("/api/logs/stream?name=../../x", headers=headers).status_code == 400
    resp = api.logs_stream(authorization=headers["Authorization"], name="nonebot")
    assert resp.media_type == "text/event-stream"


# ============================================ 权益字段：member / all_plugins / full

def test_auth_status_exposes_member_and_all_plugins(tmp_path, monkeypatch):
    """月费档：member=True 但 full/all_plugins=False（前端「会员」字样读 member）。

    只回 full 会让月费用户在界面上被显示成「免费版」、微信开关显示未解锁 ——
    少一个字段界面就会退回「免费版」。
    """
    headers = _auth(monkeypatch, tmp_path)
    cfg = headless_config.load()
    cfg.update({"plan": "monthly", "plan_expires_at": 9999999999})
    headless_config.save(cfg)
    monkeypatch.setattr(auth, "verify_entitlement", lambda c=None: True)

    res = client.get("/api/auth/status", headers=headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["member"] is True
    assert body["full"] is False and body["all_plugins"] is False
    assert body["reason"] == ""                    # 是会员，不该给「免费版」的理由

    # 永久档：三个字段全 True（生产库现有 4 个 permanent 账号必须完全不受影响）
    cfg = headless_config.load()
    cfg.update({"plan": "permanent", "plan_expires_at": 0})
    headless_config.save(cfg)
    body = client.get("/api/auth/status", headers=headers).json()
    assert body["member"] is True and body["full"] is True and body["all_plugins"] is True


def test_auth_status_anonymous_has_the_same_fields(tmp_path, monkeypatch):
    """未登录分支也要有 member/all_plugins：少字段会被前端读成 undefined → 界面错乱。"""
    monkeypatch.setattr(platform_info, "config_home", lambda: tmp_path)
    body = client.get("/api/auth/status").json()
    assert body["member"] is False and body["all_plugins"] is False and body["full"] is False
    assert body["logged_in"] is False


def test_feature_gate_never_claims_member_for_free_or_trial(tmp_path, monkeypatch):
    headers = _auth(monkeypatch, tmp_path)
    monkeypatch.setattr(auth, "verify_entitlement", lambda c=None: True)
    for plan in ("none", "", "trial", "bogus"):
        cfg = headless_config.load()
        cfg.update({"plan": plan, "plan_expires_at": 9999999999})
        headless_config.save(cfg)
        body = client.get("/api/auth/status", headers=headers).json()
        assert body["member"] is False, (plan, body)
        assert body["reason"], (plan, body)
    # 过期的月费档同样不算会员
    cfg = headless_config.load()
    cfg.update({"plan": "monthly", "plan_expires_at": 1000})
    headless_config.save(cfg)
    assert client.get("/api/auth/status", headers=headers).json()["member"] is False


def test_plugins_list(monkeypatch):
    monkeypatch.setattr(
        api,
        "_fetch_market",
        lambda: [
            {"id": "daily-motto", "name": "每日一言", "version": "1.0.0"},
            {
                "id": "group-manager",
                "name": "群管理",
                "kind": "tool-pack",
                "version": "1.0.0",
            },
        ],
    )
    res = client.get("/api/plugins")
    assert res.status_code == 200
    assert res.json()["plugins"][0]["id"] == "daily-motto"
    assert len(res.json()["plugins"]) == 1


def test_plugins_install_mocked(monkeypatch):
    import tempfile
    from pathlib import Path

    tmp = Path(tempfile.mkdtemp(prefix="qbm_api_"))
    headers = _auth(monkeypatch, tmp)
    calls = {}

    def fake_install(entry):
        calls["id"] = entry["id"]
        return {"ok": True, "id": entry["id"]}

    def fake_restart(service, log=print):
        return {"ok": True}

    monkeypatch.setattr(api.plugins, "install", fake_install)
    monkeypatch.setattr(api.services, "restart", fake_restart)
    monkeypatch.setattr(
        api,
        "_fetch_market",
        lambda: [{"id": "daily-motto", "name": "每日一言", "version": "1.0.0"}],
    )
    res = client.post("/api/plugins/install", headers=headers, json={"id": "daily-motto"})
    assert res.status_code == 200
    assert calls["id"] == "daily-motto"


# ============================================================ 账号服务地址可配置

def test_account_base_priority(tmp_path, monkeypatch):
    """账号服务地址优先级：配置 account_base > 环境变量 ASTROSWARM_ACCOUNT_BASE > 官方默认。

    以前写死 http://127.0.0.1:14512（开发机上的服务），客户机上没有任何东西监听它 →
    登录必 401、account_token 恒空 → 控制台全站 401，装完不能用。
    """
    monkeypatch.setattr(platform_info, "config_home", lambda: tmp_path)
    monkeypatch.delenv(auth.ACCOUNT_BASE_ENV, raising=False)

    # ① 默认值 = 官方托管服务
    headless_config.save({**headless_config.load(), "account_base": ""})
    assert auth.account_base() == "https://astroswarm.cn/api/account"
    assert auth.account_url("/api/account/login") == "https://astroswarm.cn/api/account/login"

    # ② 环境变量优先于默认值
    monkeypatch.setenv(auth.ACCOUNT_BASE_ENV, "https://env.example.com")
    assert auth.account_base() == "https://env.example.com"
    assert auth.account_url("/api/account/me") == "https://env.example.com/api/account/me"

    # ③ 配置优先于环境变量；两种写法（带不带 /api/account 后缀）都要拼对
    headless_config.save({**headless_config.load(),
                          "account_base": "https://self.example.com/api/account"})
    assert auth.account_base() == "https://self.example.com/api/account"
    assert auth.account_url("/api/account/login") == "https://self.example.com/api/account/login"

    # ④ 本机（服务商自己的机器）写回 127.0.0.1:14512 时行为与修复前一致
    headless_config.save({**headless_config.load(),
                          "account_base": "http://127.0.0.1:14512"})
    assert auth.account_url("/api/account/login") == "http://127.0.0.1:14512/api/account/login"


def test_account_base_env_works_on_fresh_install(tmp_path, monkeypatch):
    """全新装机（没有任何 config.json）+ 只设环境变量 → 环境变量必须生效。

    回归（2026-09-19 交付物验收发现）：headless_config.DEFAULTS 里以前把
    官方地址写成了默认值，于是 auth.account_base() 永远读到"配置里有值"，
    **环境变量和 systemd 的 Environment= 全部失效** —— 但 install.sh 第 186 行
    恰恰把 ASTROSWARM_ACCOUNT_BASE 写进了单元文件，自建账号服务的客户配了也没用。
    """
    monkeypatch.setattr(platform_info, "config_home", lambda: tmp_path / "cfg")
    monkeypatch.delenv(auth.ACCOUNT_BASE_ENV, raising=False)
    assert not (tmp_path / "cfg" / "config.json").exists(), "前置条件：全新装机没有配置文件"
    monkeypatch.setenv(auth.ACCOUNT_BASE_ENV, "https://self.example.com")
    assert auth.account_base() == "https://self.example.com"

    # 已经装过的机器：config.json 里存着官方默认地址（老版本 DEFAULTS 写进去的），
    # 环境变量同样要能改掉它。
    headless_config.save({**headless_config.load(),
                          "account_base": "https://astroswarm.cn/api/account"})
    assert auth.account_base() == "https://self.example.com"


def test_account_base_is_a_config_key(tmp_path, monkeypatch):
    """account_base 必须是可写配置项（否则控制台/安装脚本改不了它）。"""
    headers = _auth(monkeypatch, tmp_path)
    res = client.put("/api/config", headers=headers,
                     json={"account_base": "https://self.example.com"})
    assert res.status_code == 200, res.text
    assert res.json()["account_base"] == "https://self.example.com"
    assert headless_config.load()["account_base"] == "https://self.example.com"


def test_login_reports_unreachable_account_service(tmp_path, monkeypatch):
    """连不上账号服务要给人话（含当前地址），不能只丢一句 urlopen error。"""
    _auth(monkeypatch, tmp_path)
    headless_config.save({**headless_config.load(),
                          "account_base": "https://self.example.com"})

    def boom(path, body, token=None, client_ip=""):
        raise RuntimeError(f"连不上星群账号服务（{auth.account_base()}）：Connection refused")

    monkeypatch.setattr(auth, "_post", boom)
    res = client.post("/api/auth/login", json={"email": "a@b.c", "password": "x"})
    assert res.status_code == 401
    assert "连不上星群账号服务" in res.text and "self.example.com" in res.text


# ============================================================ 坏 config.json 不再锁死控制台

def test_bad_config_keeps_token_and_reports_error(tmp_path, monkeypatch):
    """config.json 写坏后：登录态要尽量救回来（否则用原 token 也 401，只能上服务器手改）。"""
    monkeypatch.setattr(platform_info, "config_home", lambda: tmp_path)
    headless_config.save({**headless_config.load(), "account_token": "KEEP-ME",
                          "account_email": "buyer@test.local", "qq_app_id": "12345",
                          "plan": "permanent", "ai_api_key": "sk-x"})
    cfg_path = tmp_path / "config.json"
    raw = cfg_path.read_text(encoding="utf-8")
    # 模拟「写到一半被打断」：文件在 account_token 那一行之后就断了
    cut = raw.index("\n", raw.index('"account_token"'))
    cfg_path.write_text(raw[: cut + 1], encoding="utf-8")

    cfg = headless_config.load()
    assert cfg.get("_config_error"), cfg
    assert cfg.get("account_token") == "KEEP-ME", cfg          # 关键：登录凭据救回来了
    assert "account_token" in (cfg.get("_config_rescued") or []), cfg
    assert cfg.get("qq_app_id") == "12345"                     # 断点之前的字段都还在

    # 用原来的 token 还能进控制台（以前这里全站 401）
    headers = {"Authorization": "Bearer KEEP-ME"}
    res = client.get("/api/config", headers=headers)
    assert res.status_code == 200, res.text
    body = res.json()
    # 前端要能看见「配置坏了 / 坏文件在哪 / 上一份好配置在哪」
    assert "_config_error" in body
    assert body["_config_backup"] and Path(body["_config_backup"]).exists()
    assert body["_config_last_good"] and Path(body["_config_last_good"]).exists()


def test_restore_last_good_route(tmp_path, monkeypatch):
    """restore_last_good() 以前没有任何路由（死代码），现在要求登录才能调。"""
    monkeypatch.setattr(platform_info, "config_home", lambda: tmp_path)
    headless_config.save({**headless_config.load(), "account_token": "GOOD-TOKEN",
                          "qq_app_id": "999"})
    headers = {"Authorization": "Bearer GOOD-TOKEN"}
    headless_config.save({**headless_config.load(), "qq_app_id": "111"})   # 产生一份 .bak

    assert client.post("/api/config/restore-last-good").status_code == 401
    res = client.post("/api/config/restore-last-good", headers=headers)
    assert res.status_code == 200, res.text
    assert res.json()["ok"] is True
    assert headless_config.load()["qq_app_id"] == "999"      # 回到上一份好配置


def test_first_save_writes_backup(tmp_path, monkeypatch):
    """新装机器第一次 save() 也要留 .bak（否则写坏时连回滚目标都没有）。"""
    monkeypatch.setattr(platform_info, "config_home", lambda: tmp_path)
    cfg_path = tmp_path / "config.json"
    assert not cfg_path.exists()
    headless_config.save({**headless_config.load(), "account_token": "FIRST"})
    bak = headless_config.last_good_path()
    assert bak.exists(), "第一次保存就应该生成 .bak"
    assert isinstance(json.loads(bak.read_text(encoding="utf-8")), dict)


# ============================================================ 登录限流按来源 IP

def test_login_rate_limit_is_per_ip(tmp_path, monkeypatch):
    """一个 IP 打满 5 次不能把别的 IP（比如主人自己）也堵死。"""
    monkeypatch.setattr(platform_info, "config_home", lambda: tmp_path)
    api._login_hits.clear()

    def deny(email, password):
        raise RuntimeError("账号密码不对")

    monkeypatch.setattr(auth, "login", deny)
    attacker = TestClient(app, client=("203.0.113.9", 40000))
    owner = TestClient(app, client=("198.51.100.1", 40000))

    codes = [attacker.post("/api/auth/login",
                           json={"email": "a@b.c", "password": "x"}).status_code
             for _ in range(6)]
    assert codes[:5] == [401] * 5 and codes[5] == 429, codes
    assert owner.post("/api/auth/login",
                      json={"email": "owner@b.c", "password": "x"}).status_code == 401
    assert sorted(api._login_hits) == ["198.51.100.1", "203.0.113.9"], api._login_hits
    api._login_hits.clear()


def test_client_ip_only_trusts_xff_from_local_proxy():
    """只有对端是本机（nginx 反代）时才信转发头，而且取 **XFF 最后一段**。

    否则任何人伪造一个 XFF 就能绕过限流。
    nginx 用的是 $proxy_add_x_forwarded_for：客户端自带值在前、真实 IP 追加在末尾，
    所以首段是调用方可控的 —— 取首段 = 让攻击者自己决定限流桶键。
    """
    from types import SimpleNamespace

    def req(host, xff="", real=""):
        headers = {}
        if xff:
            headers["x-forwarded-for"] = xff
        if real:
            headers["x-real-ip"] = real
        return SimpleNamespace(headers=headers, client=SimpleNamespace(host=host))

    assert api._client_ip(req("127.0.0.1", "1.2.3.4, 10.0.0.1")) == "10.0.0.1"
    assert api._client_ip(req("::1", "1.2.3.4")) == "1.2.3.4"
    # nginx 亲手写的 X-Real-IP（= $remote_addr）优先于 XFF
    assert api._client_ip(req("127.0.0.1", "1.2.3.4, 10.0.0.1", "10.0.0.2")) == "10.0.0.2"
    assert api._client_ip(req("203.0.113.9", "1.2.3.4")) == "203.0.113.9"
    assert api._client_ip(req("127.0.0.1")) == "127.0.0.1"


# ============================================================ SSE 不许泄漏线程

def test_logs_stream_generator_is_async(tmp_path, monkeypatch):
    """SSE 生成器必须是异步生成器。

    同步生成器会被 starlette 丢进 anyio 线程池，而 run_sync 默认要等线程结束才传播取消；
    日志空闲时线程永远卡在 next()，客户端断开也收不回 → 每断开一次泄漏一个 OS 线程。
    """
    import inspect

    from starlette.responses import StreamingResponse

    monkeypatch.setattr(platform_info, "config_home", lambda: tmp_path)
    monkeypatch.setattr(platform_info, "data_home", lambda: tmp_path)
    headless_config.save({**headless_config.load(), "account_token": "SSE-TOKEN"})

    assert client.get("/api/logs/stream").status_code == 401
    resp = api.logs_stream(authorization="Bearer SSE-TOKEN")
    assert isinstance(resp, StreamingResponse)
    assert inspect.isasyncgen(resp.body_iterator), type(resp.body_iterator)
    assert resp.media_type == "text/event-stream"


def test_afollow_streams_appended_lines_and_stops(tmp_path):
    """异步跟读：新写入的内容要出来，且到 max_seconds 必须自己退出（不能无限跑）。"""
    import asyncio
    import time as _time

    log = tmp_path / "headless.log"
    log.write_text("old line\n", encoding="utf-8")

    async def run():
        got = []

        async def consumer():
            async for chunk in logs.afollow(log, interval=0.05, max_seconds=5):
                got.append(chunk)
                if "brand new line" in "".join(got):
                    break

        async def feeder():
            await asyncio.sleep(0.3)          # 先让 consumer 把当前位置记成文件末尾
            with open(log, "a", encoding="utf-8") as f:
                f.write("brand new line\n")

        await asyncio.gather(consumer(), feeder())
        return "".join(got)

    out = asyncio.run(asyncio.wait_for(run(), timeout=10))
    assert "brand new line" in out, out
    assert "old line" not in out, out        # 默认从末尾跟，不重发历史

    # 到点退出（否则一个空转的 SSE 循环会一直挂着）
    async def drain():
        started = _time.monotonic()
        async for _ in logs.afollow(log, interval=0.05, max_seconds=0.2):
            pass
        return _time.monotonic() - started

    assert asyncio.run(asyncio.wait_for(drain(), timeout=10)) < 5


def test_sync_follow_can_be_stopped(tmp_path):
    """同步 follow 支持 stop 事件 / max_seconds（老接口也要能退出）。"""
    import threading
    import time as _time

    log = tmp_path / "headless.log"
    log.write_text("x\n", encoding="utf-8")
    stop = threading.Event()
    out = []
    t = threading.Thread(target=lambda: out.extend(logs.follow(log, interval=0.05, stop=stop)))
    t.start()
    _time.sleep(0.2)
    stop.set()
    t.join(timeout=5)
    assert not t.is_alive(), "follow 没有理会 stop 事件"
    assert list(logs.follow(log, interval=0.01, max_seconds=0.1)) == []


def test_static_endpoints_do_not_leak_paths_without_login(tmp_path, monkeypatch):
    """未鉴权的 GET：含绝对路径/账号信息的都要登录，探活与市场清单可以公开。"""
    _auth(monkeypatch, tmp_path)
    for path in ("/api/tools/status", "/api/services/status", "/api/plugins/installed",
                 "/api/console/dev-mode", "/api/deps/status",
                 "/api/plugins/entitlement", "/api/tools/demo/detail"):
        assert client.get(path).status_code == 401, path
    assert client.get("/health").status_code == 200
    assert client.get("/api/status").json().get("data_home") is None
