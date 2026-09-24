# -*- coding: utf-8 -*-
"""无头端人设工坊接口（console_ext 的 /api/persona/*）。

覆盖：未登录 401、导入（JSON / Markdown 文本 / zip）→ 列表 → 启用 → 停用 → 卸载，
以及安全边界：id 白名单（`../`、绝对路径、超长）、路径穿越、卸载必须二次确认。

风格与 tests/test_linux_console_ext.py 一致：TestClient + monkeypatch，不碰真实数据目录。
"""
import base64
import json
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from astroswarm_linux import console_ext, headless_config, platform_info
from astroswarm_linux.api import app

client = TestClient(app)

ROUTES = (
    ("get", "/api/persona/template"),
    ("get", "/api/persona/guide"),
    ("get", "/api/persona/list"),
    ("post", "/api/persona/import"),
    ("post", "/api/persona/activate"),
    ("post", "/api/persona/deactivate"),
    ("post", "/api/persona/uninstall"),
)


def _card(pid="com.demo.rose", name="玫瑰"):
    return {
        "format": "astroswarm-persona",
        "version": "1.0",
        "id": pid,
        "name": name,
        "kind": "persona-pack",
        "summary": "测试人设",
        "identity": {"name": name, "worldview": "测试世界"},
        "personality": {"traits": ["冷静"], "tone": "简洁"},
        "directives": ["保护用户"],
        "boundaries": ["不聊违法内容"],
    }


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """隔离环境：数据根 / 配置根都指向 tmp_path，指针文件也别写进用户目录。"""
    data = tmp_path / "data"
    cfg = tmp_path / "cfg"
    cfg.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(platform_info, "data_home", lambda: data)
    monkeypatch.setattr(platform_info, "config_home", lambda: cfg)
    # Settings.save() 会写「安装根指针」（默认在 %APPDATA%），测试里挪走
    from qbotmanager.core import settings as settings_mod

    monkeypatch.setattr(settings_mod, "POINTER_DIR", tmp_path / "ptr", raising=False)
    monkeypatch.setattr(settings_mod, "POINTER_FILE", tmp_path / "ptr" / "settings.json", raising=False)
    monkeypatch.setattr(settings_mod, "RECENT_FILE", tmp_path / "ptr" / "recent.json", raising=False)

    token = "test-token"
    headless_config.save({**headless_config.load(), "account_token": token})
    return {
        "data": data,
        "personas": data / "personas",
        "headers": {"Authorization": f"Bearer {token}"},
    }


def _import(env, **body):
    return client.post("/api/persona/import", json=body, headers=env["headers"])


def _import_json(env, card=None, filename="rose.json"):
    return _import(env, filename=filename, content=json.dumps(card or _card(), ensure_ascii=False))


def test_routes_registered():
    paths = {getattr(r, "path", "") for r in app.routes}
    for _, path in ROUTES:
        assert path in paths, f"缺路由 {path}"


def test_all_persona_routes_need_auth(env):
    """未登录一律 401（下载模板走 ?token= 也一样）。"""
    for method, path in ROUTES:
        if method == "post":
            res = client.post(path, json={})
        else:
            res = client.get(path)
        assert res.status_code in (401, 403), f"{path} 未鉴权就能访问：{res.status_code}"
    assert client.get("/api/persona/template?token=wrong").status_code in (401, 403)


def test_id_whitelist_rejects_traversal_and_absolute():
    for ok in ("com.demo.rose", "rose", "rose-1.0", "A_b.c"):
        assert console_ext.valid_persona_id(ok), ok
    for bad in ("../rose", "..", ".", "/etc/passwd", "a/b", "a\\b", "a" * 80, "", "a..b",
                "C:\\Windows\\system32"):
        assert not console_ext.valid_persona_id(bad), bad


def test_import_list_activate_deactivate_uninstall(env):
    # 空目录先来一次列表：不报错、空数组
    data = client.get("/api/persona/list", headers=env["headers"]).json()
    assert data["ok"] is True and data["items"] == []

    res = _import_json(env)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] and body["id"] == "com.demo.rose"
    # 落盘位置必须与桌面端一致：<数据根>/personas/<id>/manifest.json
    assert (env["personas"] / "com.demo.rose" / "manifest.json").exists()

    items = client.get("/api/persona/list", headers=env["headers"]).json()["items"]
    assert [i["id"] for i in items] == ["com.demo.rose"]
    assert items[0]["name"] == "玫瑰" and items[0]["active"] is False
    assert items[0]["source"] == "本地导入" and items[0]["updated_at"]

    res = client.post("/api/persona/activate", json={"id": "com.demo.rose"}, headers=env["headers"])
    assert res.status_code == 200, res.text
    assert res.json()["needs_restart"] is True
    assert "玫瑰" in res.json()["personality"]
    # 启用后立刻可见于列表（active）+ 无头配置记下启用中的人设 + 关掉硬编码档案
    items = client.get("/api/persona/list", headers=env["headers"]).json()["items"]
    assert items[0]["active"] is True
    cfg = headless_config.load()
    assert cfg["local_persona_id"] == "com.demo.rose"
    assert cfg["agent_profile_enabled"] is False
    # 人格确实写进了机器人侧 aichat_manager.json
    from qbotmanager.core import ai_config

    assert "玫瑰" in ai_config.read_personality(console_ext._persona_settings())

    res = client.post("/api/persona/deactivate", headers=env["headers"])
    assert res.status_code == 200 and res.json()["needs_restart"] is True
    assert headless_config.load()["local_persona_id"] == ""
    assert client.get("/api/persona/list", headers=env["headers"]).json()["items"][0]["active"] is False

    res = client.post("/api/persona/uninstall",
                      json={"id": "com.demo.rose", "confirm": True}, headers=env["headers"])
    assert res.status_code == 200, res.text
    assert client.get("/api/persona/list", headers=env["headers"]).json()["items"] == []
    assert not (env["personas"] / "com.demo.rose").exists()


def test_import_markdown_text(env):
    """模板说明里的「整段人设文字」写法：包成人格卡后也能导入并启用。"""
    res = _import(env, filename="我的助手.md", name="小助手",
                  content="# 小助手\n\n你是一个简洁的助手，只给关键信息。")
    assert res.status_code == 200, res.text
    pid = res.json()["id"]
    assert pid.startswith("persona-")        # 中文名不能当目录名 → 退回时间戳 id
    card = json.loads((env["personas"] / pid / "manifest.json").read_text(encoding="utf-8"))
    assert card["system_prompt"].startswith("# 小助手") and card["name"] == "小助手"
    assert client.post("/api/persona/activate", json={"id": pid},
                       headers=env["headers"]).status_code == 200


def test_import_zip_with_tools(env):
    card = _card(pid="com.demo.sage", name="贤者")
    card["tools"] = [{"name": "hello", "description": "打招呼",
                      "parameters": {"type": "object", "properties": {}, "required": []},
                      "permissions": []}]
    buf_path = env["data"] / "sage.zip"
    buf_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(buf_path, "w") as z:
        z.writestr("sage/manifest.json", json.dumps(card, ensure_ascii=False))
        z.writestr("sage/tools/hello.py", "def handle(ctx, args):\n    return 'hi'\n")

    res = _import(env, filename="sage.zip",
                  content_b64=base64.b64encode(buf_path.read_bytes()).decode())
    assert res.status_code == 200, res.text
    assert res.json()["tools"] == ["hello"]
    assert (env["personas"] / "com.demo.sage" / "tools" / "hello.py").exists()


def test_import_rejects_bad_cards(env):
    # id 穿越：persona_workshop 自己不校验 id，接口层必须先挡（否则会写/删到人设目录之外）
    res = _import_json(env, card={**_card(), "id": "../../evil"})
    assert res.status_code == 400 and "id" in res.text
    res = _import_json(env, card={**_card(), "id": "/tmp/evil"})
    assert res.status_code == 400
    # 不是 JSON、内容为空、缺字段
    assert _import(env, filename="x.json", content="{不是 json").status_code == 400
    assert _import(env, filename="x.json", content="   ").status_code == 400
    assert _import(env, filename="x.json", content=json.dumps({"id": "ok"})).status_code == 400
    assert _import(env, filename="x.json").status_code == 400          # 没给内容
    # zip 里的 manifest id 穿越
    bad_zip = env["data"] / "bad.zip"
    with zipfile.ZipFile(bad_zip, "w") as z:
        z.writestr("manifest.json", json.dumps({**_card(), "id": "../evil"}, ensure_ascii=False))
    res = _import(env, filename="bad.zip",
                  content_b64=base64.b64encode(bad_zip.read_bytes()).decode())
    assert res.status_code == 400
    # 一个都没落盘，且人设目录外没被写东西
    assert not env["personas"].exists() or list(env["personas"].iterdir()) == []
    assert not (env["data"] / "evil").exists()


@pytest.mark.parametrize("pid", ["../rose", "/etc/passwd", "..", "a" * 80, "a/b"])
def test_bad_id_rejected_on_activate_and_uninstall(env, pid):
    _import_json(env)
    for path in ("/api/persona/activate", "/api/persona/uninstall"):
        res = client.post(path, json={"id": pid, "confirm": True}, headers=env["headers"])
        assert res.status_code == 400, f"{path} {pid} -> {res.status_code}"
    # 合法人设没被动过
    assert (env["personas"] / "com.demo.rose").exists()


def test_uninstall_requires_confirm(env):
    """卸载不可撤销：没有 confirm=true 一律不执行（前端 window.confirm 的后端兜底）。"""
    _import_json(env)
    for body in ({"id": "com.demo.rose"}, {"id": "com.demo.rose", "confirm": False}):
        res = client.post("/api/persona/uninstall", json=body, headers=env["headers"])
        assert res.status_code == 400, res.text
        assert "confirm" in res.text
        assert (env["personas"] / "com.demo.rose").exists()
    # 确认后才真的删
    assert client.post("/api/persona/uninstall", json={"id": "com.demo.rose", "confirm": True},
                       headers=env["headers"]).status_code == 200
    assert not (env["personas"] / "com.demo.rose").exists()


def test_uninstall_missing_persona_404(env):
    env["personas"].mkdir(parents=True, exist_ok=True)
    res = client.post("/api/persona/uninstall",
                      json={"id": "com.demo.nope", "confirm": True}, headers=env["headers"])
    assert res.status_code == 404


def test_uninstall_refuses_symlink_escape(env, tmp_path):
    """符号链接指向人设目录之外时，不允许顺着链接删掉外面的东西。"""
    env["personas"].mkdir(parents=True, exist_ok=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("别删我", encoding="utf-8")
    link = env["personas"] / "com.evil.link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("此平台不支持创建符号链接（Windows 需要开发者模式）")
    res = client.post("/api/persona/uninstall", json={"id": "com.evil.link", "confirm": True},
                      headers=env["headers"])
    assert res.status_code == 400, res.text
    assert (outside / "keep.txt").exists()


def test_template_and_guide(env):
    res = client.get("/api/persona/template", headers=env["headers"])
    assert res.status_code == 200
    assert "persona-card-template.json" in res.headers["content-disposition"]
    assert json.loads(res.text)["format"] == "astroswarm-persona"

    res = client.get("/api/persona/template?fmt=md", headers=env["headers"])
    assert res.status_code == 200 and "persona-card-guide.md" in res.headers["content-disposition"]

    guide = client.get("/api/persona/guide", headers=env["headers"]).json()
    assert guide["ok"] and guide["chars"] > 100 and "两种写法" in guide["text"]
    # 下载类接口也要能走 ?token=（浏览器的 <a download> 带不了 header）
    assert client.get("/api/persona/template",
                      params={"token": headless_config.load()["account_token"]}).status_code == 200


def test_activate_missing_persona_404(env):
    env["personas"].mkdir(parents=True, exist_ok=True)
    res = client.post("/api/persona/activate", json={"id": "com.demo.nope"}, headers=env["headers"])
    assert res.status_code == 404


def test_bot_env_gets_active_persona(env, monkeypatch):
    """启用的人设要进机器人进程环境（人设自带工具靠 ASTROSWARM_PERSONAS_ALLOWED 才加载）。"""
    from astroswarm_linux import deploy
    from qbotmanager.core import persona_workshop

    _import_json(env)
    client.post("/api/persona/activate", json={"id": "com.demo.rose"}, headers=env["headers"])
    s = deploy.build_settings()
    assert s.local_persona_id == "com.demo.rose"
    env_vars = persona_workshop.pack_env(s)
    assert env_vars["ASTROSWARM_PERSONAS_ALLOWED"] == "com.demo.rose"
    assert env_vars["ASTROSWARM_PERSONAS"].endswith("personas")


if __name__ == "__main__":
    print("请用 pytest 运行：pytest tests/test_linux_persona_workshop.py -q")
