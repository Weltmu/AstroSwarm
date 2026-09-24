# -*- coding: utf-8 -*-
"""MCP 配置读写、本地 zip 安装的安全边界（dev 模式/confirm/zip slip/大小/id）。"""
import base64
import io
import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path

import pytest

SANDBOX = tempfile.mkdtemp(prefix="sw-p5-")
os.environ["XDG_DATA_HOME"] = SANDBOX
os.environ["XDG_CONFIG_HOME"] = SANDBOX
sys.path.insert(0, r"D:\ai\QBotManager\src")

from fastapi.testclient import TestClient  # noqa: E402

from astroswarm_linux import console_ext, headless_config, platform_info  # noqa: E402
from astroswarm_linux import tools as hl_tools  # noqa: E402
from astroswarm_linux.api import app  # noqa: E402

client = TestClient(app)
TOKEN = "mcp-token"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(platform_info, "config_home", lambda: tmp_path)
    monkeypatch.setattr(platform_info, "data_home", lambda: tmp_path)
    headless_config.save({**headless_config.load(), "account_token": TOKEN})
    console_ext.set_dev_mode(False)
    yield {"headers": {"Authorization": f"Bearer {TOKEN}"}, "tmp": tmp_path}
    console_ext.set_dev_mode(False)


def make_zip(entries, symlink=None, compress=False):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED if compress else zipfile.ZIP_STORED) as z:
        for name, content in entries.items():
            z.writestr(name, content)
        if symlink:
            info = zipfile.ZipInfo(symlink)
            info.external_attr = (0o120777 << 16)
            z.writestr(info, "/etc/passwd")
    return base64.b64encode(buf.getvalue()).decode()


CARD = {"id": "com.demo.pack", "name": "演示包", "version": "1.0.0", "kind": "tool-pack"}


def test_p5_requires_auth():
    assert client.get("/api/mcp/config").status_code == 401
    assert client.post("/api/mcp/save", json={"enabled": True, "servers": {}}).status_code == 401
    assert client.post("/api/tools/install-zip", json={}).status_code == 401


def test_mcp_roundtrip(env):
    res = client.get("/api/mcp/config", headers=env["headers"])
    assert res.status_code == 200, res.text
    assert "mcp" in res.json()

    bad = client.post("/api/mcp/save", headers=env["headers"],
                      json={"enabled": True, "servers": {"x": {"type": "stdio"}}})
    assert bad.status_code == 400 and "command" in bad.text

    bad2 = client.post("/api/mcp/save", headers=env["headers"],
                       json={"enabled": True, "servers": {"x": {"type": "sse"}}})
    assert bad2.status_code == 400 and "url" in bad2.text

    ok = client.post("/api/mcp/save", headers=env["headers"], json={
        "enabled": True,
        "servers": {"demo": {"type": "sse", "url": "http://127.0.0.1:8000/sse", "enabled": True}},
    })
    assert ok.status_code == 200, ok.text
    assert ok.json()["needs_restart"] is True and ok.json()["servers"] == 1
    again = client.get("/api/mcp/config", headers=env["headers"]).json()["mcp"]
    assert again.get("enabled") is True
    assert "demo" in (again.get("servers") or {})


def test_zip_install_requires_dev_mode_and_confirm(env):
    payload = {"filename": "p.zip", "content_b64": make_zip({"manifest.json": json.dumps(CARD)}),
               "confirm": True}
    assert client.post("/api/tools/install-zip", json=payload,
                       headers=env["headers"]).status_code == 403      # 未开开发者模式
    console_ext.set_dev_mode(True)
    payload_no_confirm = dict(payload, confirm=False)
    assert client.post("/api/tools/install-zip", json=payload_no_confirm,
                       headers=env["headers"]).status_code == 400      # 没确认


def test_zip_install_rejects_zip_slip(env):
    console_ext.set_dev_mode(True)
    evil = make_zip({"manifest.json": json.dumps(CARD), "../evil.sh": "rm -rf /"})
    res = client.post("/api/tools/install-zip",
                      json={"filename": "p.zip", "content_b64": evil, "confirm": True},
                      headers=env["headers"])
    assert res.status_code == 400 and "越界路径" in res.text

    absolute = make_zip({"manifest.json": json.dumps(CARD), "/etc/evil": "x"})
    assert client.post("/api/tools/install-zip",
                       json={"filename": "p.zip", "content_b64": absolute, "confirm": True},
                       headers=env["headers"]).status_code == 400

    link = make_zip({"manifest.json": json.dumps(CARD)}, symlink="link")
    assert client.post("/api/tools/install-zip",
                       json={"filename": "p.zip", "content_b64": link, "confirm": True},
                       headers=env["headers"]).status_code == 400


def test_zip_install_rejects_bad_manifest_and_id(env):
    console_ext.set_dev_mode(True)
    no_manifest = make_zip({"readme.txt": "hi"})
    r1 = client.post("/api/tools/install-zip",
                     json={"filename": "p.zip", "content_b64": no_manifest, "confirm": True},
                     headers=env["headers"])
    assert r1.status_code == 400 and "manifest.json" in r1.text

    bad_id = make_zip({"manifest.json": json.dumps({**CARD, "id": "../../evil"})})
    r2 = client.post("/api/tools/install-zip",
                     json={"filename": "p.zip", "content_b64": bad_id, "confirm": True},
                     headers=env["headers"])
    assert r2.status_code == 400 and "id 不合法" in r2.text

    not_zip = base64.b64encode(b"this is not a zip").decode()
    assert client.post("/api/tools/install-zip",
                       json={"filename": "p.zip", "content_b64": not_zip, "confirm": True},
                       headers=env["headers"]).status_code == 400
    assert client.post("/api/tools/install-zip",
                       json={"filename": "p.txt", "content_b64": not_zip, "confirm": True},
                       headers=env["headers"]).status_code == 400


# ---------------------------------------------------------------- 成功路径（回归）
# 这条以前完全没有：老版本 install_tool_pack_zip 里写的是 `tool_packs_mod.install_pack`，
# 而 console_ext **从没导入过这个名字** → 每次调用必 500，10 条拒绝路径测试全绿也没发现。

def test_zip_install_success_path(env):
    """合法 zip + dev 模式 + confirm → 200，包真的落到 tool_packs/<id>/，临时目录被清掉。"""
    console_ext.set_dev_mode(True)
    pack = make_zip({
        "manifest.json": json.dumps(CARD, ensure_ascii=False),
        "tools/hello.py": "def hello():\n    return 'hi'\n",
    })
    before = set(Path(tempfile.gettempdir()).glob("sw-zip-*"))

    res = client.post("/api/tools/install-zip",
                      json={"filename": "pack.zip", "content_b64": pack, "confirm": True},
                      headers=env["headers"])
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] is True and body["pack"]["id"] == CARD["id"]
    assert body["needs_restart"] is True

    # ① 能力包真的装上了（manifest + 包内工具都在）
    pack_dir = env["tmp"] / "tool_packs" / CARD["id"]
    assert (pack_dir / "manifest.json").exists(), list(env["tmp"].rglob("*"))
    assert (pack_dir / "tools" / "hello.py").exists()
    assert json.loads((pack_dir / "manifest.json").read_text(encoding="utf-8"))["id"] == CARD["id"]

    # ② 解压用的临时目录必须清掉（里面有上传的原始 zip）
    leftovers = set(Path(tempfile.gettempdir()).glob("sw-zip-*")) - before
    assert leftovers == set(), leftovers

    # ③ 装完能在「已装能力包」列表里看到
    assert CARD["id"] in {p["id"] for p in hl_tools.installed()}


def test_zip_install_permission_error_is_403(env, monkeypatch):
    """权益不足（没买这个包）要 403，不能兜成 500 让前端以为服务端坏了。"""
    console_ext.set_dev_mode(True)
    import qbotmanager.core.tool_packs as tp

    def deny(settings, entry, zip_path=None, log=None):
        raise PermissionError("需要单独购买该插件")

    monkeypatch.setattr(tp, "install_pack", deny)
    res = client.post("/api/tools/install-zip",
                      json={"filename": "pack.zip",
                            "content_b64": make_zip({"manifest.json": json.dumps(CARD)}),
                            "confirm": True},
                      headers=env["headers"])
    assert res.status_code == 403, res.text
    assert "无权安装" in res.text


def test_zip_install_rejects_bomb(env):
    """解压炸弹：上传的 zip 很小，但解压后远超阈值 → 400（安装前就拦）。"""
    console_ext.set_dev_mode(True)
    headers = env["headers"]

    big = make_zip({"manifest.json": json.dumps(CARD), "data/blob.bin": b"\0" * (101 * 1024 * 1024)},
                   compress=True)
    r1 = client.post("/api/tools/install-zip",
                     json={"filename": "p.zip", "content_b64": big, "confirm": True},
                     headers=headers)
    assert r1.status_code == 400 and "解压后太大" in r1.text, r1.text
    assert not (env["tmp"] / "tool_packs" / CARD["id"]).exists()

    # 单成员压缩比异常（5MB 全零 → 压缩后几 KB，压缩比约 1000:1）
    ratio = make_zip({"manifest.json": json.dumps(CARD), "data/blob.bin": b"\0" * (5 * 1024 * 1024)},
                     compress=True)
    r2 = client.post("/api/tools/install-zip",
                     json={"filename": "p.zip", "content_b64": ratio, "confirm": True},
                     headers=headers)
    assert r2.status_code == 400 and "压缩比" in r2.text, r2.text
    # 小包不受影响（别把正常包也拦了）
    ok = client.post("/api/tools/install-zip",
                     json={"filename": "p.zip",
                           "content_b64": make_zip({"manifest.json": json.dumps(CARD)}),
                           "confirm": True},
                     headers=headers)
    assert ok.status_code == 200, ok.text
