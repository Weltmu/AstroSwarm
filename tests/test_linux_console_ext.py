"""无头端补充接口（console_ext）：插件清单 / 依赖扫描与安装 / 日志下载 / 开发者模式装插件。

跑法与其他 linux 测试一致：需要装了 fastapi 的解释器（部署机 / CI）。
"""
import json
import sys
import time
from pathlib import Path

from fastapi.testclient import TestClient

from astroswarm_linux import console_ext, headless_config, platform_info
from astroswarm_linux.api import app

client = TestClient(app)


def _auth(monkeypatch, tmp_path, token="test-token"):
    monkeypatch.setattr(platform_info, "config_home", lambda: tmp_path)
    headless_config.save({**headless_config.load(), "account_token": token})
    return {"Authorization": f"Bearer {token}"}


def _wait_done(headers, timeout=12.0):
    st = {}
    for _ in range(int(timeout / 0.2)):
        st = client.get("/api/deps/status", headers=headers).json()
        if not st["running"]:
            return st
        time.sleep(0.2)
    return st


def test_routes_registered():
    """路由必须挂在 StaticFiles 之前，否则永远匹配不到。"""
    paths = {getattr(r, "path", "") for r in app.routes}
    for want in (
        "/api/plugins/installed",
        "/api/plugins/install-pypi",
        "/api/console/dev-mode",
        "/api/deps/status",
        "/api/deps/scan",
        "/api/deps/install",
        "/api/logs/download",
    ):
        assert want in paths, f"缺路由 {want}"


def test_dep_name_extraction():
    assert console_ext._dep_name("nonebot2[fastapi]>=2.0.0") == "nonebot2"
    assert console_ext._dep_name("PyJWT") == "PyJWT"
    assert console_ext._dep_name('foo; python_version<"3.11"') == "foo"


def test_package_name_validation():
    for ok in ("nonebot-plugin-status", "nonebot_plugin_x", "foo==1.2.3", "foo>=1.0", "nonebot-plugin-x[fastapi]"):
        assert console_ext.valid_package(ok), ok
    for bad in ("", "   ", "foo bar", "foo;rm -rf /", "rm -rf /", "a" * 200):
        assert not console_ext.valid_package(bad), bad
    assert console_ext.default_module("nonebot-plugin-status==1.0") == "nonebot_plugin_status"


def test_deps_status_shape(tmp_path, monkeypatch):
    headers = _auth(monkeypatch, tmp_path)
    assert client.get("/api/deps/status").status_code == 401   # 带 pip 输出/路径，要登录
    res = client.get("/api/deps/status", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    for key in ("running", "kind", "checked", "missing", "installed", "package", "log", "error"):
        assert key in data


def test_deps_scan_needs_auth():
    assert client.post("/api/deps/scan").status_code in (401, 403)


def test_deps_scan_finds_declared_deps(tmp_path, monkeypatch):
    """造一个插件目录，断言依赖名被扫出来、缺失项进 missing。"""
    headers = _auth(monkeypatch, tmp_path)
    data_home = tmp_path / "data"
    plugins_dir = data_home / "bot" / "src" / "plugins"
    plug = plugins_dir / "demo"
    plug.mkdir(parents=True)
    (plug / "requirements.txt").write_text("definitely-not-installed-pkg==0.0.1\n", encoding="utf-8")

    monkeypatch.setattr(platform_info, "data_home", lambda: data_home)
    monkeypatch.setattr(
        console_ext, "_bot_python", lambda settings: Path(sys.executable), raising=False
    )

    res = client.post("/api/deps/scan", headers=headers)
    assert res.status_code == 200 and res.json()["started"] is True

    st = _wait_done(headers)
    assert st["running"] is False
    assert st["checked"] >= 1, st
    assert any("definitely-not-installed-pkg" in d for d in st["missing"]), st
    assert json.dumps(st)  # 状态必须可序列化


def test_dev_mode_roundtrip(tmp_path, monkeypatch):
    headers = _auth(monkeypatch, tmp_path)
    assert client.get("/api/console/dev-mode").status_code == 401   # 本机状态不外泄
    assert client.get("/api/console/dev-mode", headers=headers).json()["developer_mode"] is False
    assert client.post("/api/console/dev-mode", json={"on": True}).status_code in (401, 403)

    res = client.post("/api/console/dev-mode", json={"on": True}, headers=headers)
    assert res.status_code == 200 and res.json()["developer_mode"] is True
    assert client.get("/api/console/dev-mode", headers=headers).json()["developer_mode"] is True
    assert (tmp_path / "console.json").exists()

    res = client.post("/api/console/dev-mode", json={"on": False}, headers=headers)
    assert res.json()["developer_mode"] is False


def test_install_pypi_needs_auth_and_dev_mode(tmp_path, monkeypatch):
    headers = _auth(monkeypatch, tmp_path)
    body = {"package": "nonebot-plugin-status"}
    assert client.post("/api/plugins/install-pypi", json=body).status_code in (401, 403)

    # 开发者模式没开 -> 403（跟桌面端「开发者模式关闭时禁用安装」一致）
    res = client.post("/api/plugins/install-pypi", json=body, headers=headers)
    assert res.status_code == 403, res.text

    client.post("/api/console/dev-mode", json={"on": True}, headers=headers)
    res = client.post("/api/plugins/install-pypi", json={"package": "foo bar"}, headers=headers)
    assert res.status_code == 400, res.text


def test_install_pypi_runs_and_reports(tmp_path, monkeypatch):
    """装成功要落 installed；pip 返回非 0 要落 error，而不是让接口 500。"""
    bot_mod = __import__("qbotmanager.core.bot", fromlist=["x"])
    headers = _auth(monkeypatch, tmp_path)
    client.post("/api/console/dev-mode", json={"on": True}, headers=headers)
    monkeypatch.setattr(console_ext, "_bot_python", lambda settings: Path(sys.executable), raising=False)
    monkeypatch.setattr(bot_mod, "read_plugins", lambda settings: [])
    monkeypatch.setattr(bot_mod, "write_plugins", lambda settings, plugins: None)

    monkeypatch.setattr(console_ext, "_pip_install", lambda py, dep, official=False: True)
    res = client.post(
        "/api/plugins/install-pypi", json={"package": "nonebot-plugin-status"}, headers=headers
    )
    assert res.status_code == 200 and res.json()["started"] is True
    st = _wait_done(headers)
    assert st["running"] is False
    assert st["kind"] == "plugin"
    assert st["installed"] == ["nonebot-plugin-status"], st

    monkeypatch.setattr(console_ext, "_pip_install", lambda py, dep, official=False: False)
    res = client.post(
        "/api/plugins/install-pypi", json={"package": "nonebot-plugin-x"}, headers=headers
    )
    assert res.status_code == 200
    st = _wait_done(headers)
    assert "pip 返回非 0" in st["error"], st
    assert json.dumps(st)


def test_install_pypi_without_bot_runtime(tmp_path, monkeypatch):
    """机器人运行时没部署时给一句人话，而不是抛异常。"""
    headers = _auth(monkeypatch, tmp_path)
    client.post("/api/console/dev-mode", json={"on": True}, headers=headers)
    monkeypatch.setattr(console_ext, "_bot_python", lambda settings: None, raising=False)
    res = client.post(
        "/api/plugins/install-pypi", json={"package": "nonebot-plugin-status"}, headers=headers
    )
    assert res.status_code == 200
    st = _wait_done(headers)
    assert "还没部署" in st["error"], st


def test_install_pypi_installs_with_bot_venv_and_records(tmp_path, monkeypatch):
    """断言：用机器人 venv 的 pip 装（不走 ensure_runtime），装完把模块名写进 pyproject。"""
    bot_mod = __import__("qbotmanager.core.bot", fromlist=["x"])
    headers = _auth(monkeypatch, tmp_path)
    client.post("/api/console/dev-mode", json={"on": True}, headers=headers)
    monkeypatch.setattr(console_ext, "_bot_python", lambda settings: Path(sys.executable), raising=False)

    calls = []

    def fake_pip(py, dep, official=False):
        calls.append((dep, official))
        return True

    written = {}

    def fake_write(settings, plugins):
        written["plugins"] = list(plugins)

    monkeypatch.setattr(console_ext, "_pip_install", fake_pip)
    monkeypatch.setattr(bot_mod, "read_plugins", lambda settings: [])
    monkeypatch.setattr(bot_mod, "write_plugins", fake_write)

    res = client.post(
        "/api/plugins/install-pypi",
        json={"package": "nonebot-plugin-demo", "module": "nonebot_plugin_demo"},
        headers=headers,
    )
    assert res.status_code == 200
    st = _wait_done(headers)
    assert not st["error"], st
    assert calls == [("nonebot-plugin-demo", False)], calls
    assert written.get("plugins") == ["nonebot_plugin_demo"], written
    assert st["installed"] == ["nonebot-plugin-demo"]
    assert any("pyproject" in ln for ln in st["log"])

    # 镜像源失败时自动切官方源
    calls.clear()
    monkeypatch.setattr(console_ext, "_pip_install", lambda py, dep, official=False: calls.append(official) or official)
    client.post("/api/plugins/install-pypi", json={"package": "nonebot-plugin-x"}, headers=headers)
    st = _wait_done(headers)
    assert calls == [False, True], calls
    assert not st["error"], st


def test_logs_download_404_when_missing(tmp_path, monkeypatch):
    headers = _auth(monkeypatch, tmp_path)      # 日志接口现在要求登录
    monkeypatch.setattr(platform_info, "log_home", lambda: tmp_path / "nologs")
    res = client.get("/api/logs/download", headers=headers)
    assert res.status_code == 404


def test_logs_download_returns_file(tmp_path, monkeypatch):
    headers = _auth(monkeypatch, tmp_path)      # 日志接口现在要求登录
    home = tmp_path / "logs"
    home.mkdir()
    (home / "headless.log").write_text("hello\n", encoding="utf-8")
    monkeypatch.setattr(platform_info, "log_home", lambda: home)
    res = client.get("/api/logs/download", headers=headers)
    assert res.status_code == 200
    assert "hello" in res.text
