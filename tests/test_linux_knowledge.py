# -*- coding: utf-8 -*-
"""知识库接口回归：鉴权 / 空库不崩 / 标题兜底 / 超大拒绝 / 删除要确认与存在性。

跑法：$env:PYTHONPATH="D:\ai\QBotManager\src"; .\.test_venv\Scripts\python.exe -m pytest tests/test_linux_knowledge.py -q
"""
import os
import sys
import tempfile

import pytest

SANDBOX = tempfile.mkdtemp(prefix="sw-kb-")
os.environ["XDG_DATA_HOME"] = SANDBOX
os.environ["XDG_CONFIG_HOME"] = SANDBOX
sys.path.insert(0, r"D:\ai\QBotManager\src")

from fastapi.testclient import TestClient  # noqa: E402

from astroswarm_linux import headless_config, platform_info  # noqa: E402
from astroswarm_linux.api import app  # noqa: E402

client = TestClient(app)
TOKEN = "kb-token"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(platform_info, "config_home", lambda: tmp_path)
    monkeypatch.setattr(platform_info, "data_home", lambda: tmp_path)
    headless_config.save({**headless_config.load(), "account_token": TOKEN})
    return {"headers": {"Authorization": f"Bearer {TOKEN}"}}


def test_knowledge_requires_auth():
    assert client.get("/api/knowledge/list").status_code == 401
    assert client.post("/api/knowledge/add", json={"title": "t", "text": "x"}).status_code == 401
    assert client.post("/api/knowledge/delete", json={"id": "x", "confirm": True}).status_code == 401


def test_knowledge_list_empty(env):
    res = client.get("/api/knowledge/list", headers=env["headers"])
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] and body["items"] == [] and body["total"] == 0


def test_knowledge_add_then_list(env):
    res = client.post("/api/knowledge/add",
                      json={"title": "安装文档", "text": "第一步解压，第二步运行 install.sh。"},
                      headers=env["headers"])
    assert res.status_code == 200, res.text
    doc = res.json()["doc"]
    assert doc["id"] and doc["title"] == "安装文档"
    items = client.get("/api/knowledge/list", headers=env["headers"]).json()["items"]
    assert [i["title"] for i in items] == ["安装文档"]


def test_knowledge_add_empty_text_rejected(env):
    assert client.post("/api/knowledge/add", json={"title": "x", "text": "   "},
                       headers=env["headers"]).status_code == 400


def test_knowledge_add_title_falls_back_to_first_line(env):
    res = client.post("/api/knowledge/add",
                      json={"title": "", "text": "第一行就是标题\n后面是正文"},
                      headers=env["headers"])
    assert res.status_code == 200
    assert res.json()["doc"]["title"].startswith("第一行就是标题")


def test_knowledge_add_too_large_rejected(env):
    big = "字" * (2 * 1024 * 1024)
    res = client.post("/api/knowledge/add", json={"title": "大", "text": big},
                      headers=env["headers"])
    assert res.status_code == 400 and "太大" in res.text


def test_knowledge_delete_requires_confirm_and_existence(env):
    did = client.post("/api/knowledge/add", json={"title": "待删", "text": "内容"},
                      headers=env["headers"]).json()["doc"]["id"]
    assert client.post("/api/knowledge/delete", json={"id": did},
                       headers=env["headers"]).status_code == 400
    assert client.post("/api/knowledge/delete", json={"id": "../../x", "confirm": True},
                       headers=env["headers"]).status_code == 400
    assert client.post("/api/knowledge/delete", json={"id": "nope", "confirm": True},
                       headers=env["headers"]).status_code == 404
    res = client.post("/api/knowledge/delete", json={"id": did, "confirm": True},
                      headers=env["headers"])
    assert res.status_code == 200 and res.json()["needs_restart"] is True
    assert client.get("/api/knowledge/list", headers=env["headers"]).json()["items"] == []
