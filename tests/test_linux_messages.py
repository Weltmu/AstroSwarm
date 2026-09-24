# -*- coding: utf-8 -*-
"""消息中心与首页统计接口回归：鉴权 / 空数据不崩 / 只透标量字段 / 上限保护。

跑法：$env:PYTHONPATH="D:\ai\QBotManager\src"; .\.test_venv\Scripts\python.exe -m pytest tests/test_linux_messages.py -q
"""
import json
import os
import sys
import tempfile

import pytest

SANDBOX = tempfile.mkdtemp(prefix="sw-msg-")
os.environ["XDG_DATA_HOME"] = SANDBOX
os.environ["XDG_CONFIG_HOME"] = SANDBOX
sys.path.insert(0, r"D:\ai\QBotManager\src")

from fastapi.testclient import TestClient  # noqa: E402

from astroswarm_linux import console_ext, headless_config, platform_info  # noqa: E402
from astroswarm_linux.api import app  # noqa: E402

client = TestClient(app)
TOKEN = "msg-token"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(platform_info, "config_home", lambda: tmp_path)
    monkeypatch.setattr(platform_info, "data_home", lambda: tmp_path)
    headless_config.save({**headless_config.load(), "account_token": TOKEN})
    return {"headers": {"Authorization": f"Bearer {TOKEN}"}}


def test_messages_requires_auth():
    assert client.get("/api/messages/list").status_code == 401
    assert client.get("/api/stats/summary").status_code == 401


def test_messages_empty(env):
    res = client.get("/api/messages/list", headers=env["headers"])
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] and body["conversations"] == [] and body["total"] == 0


def test_stats_empty_returns_zeros(env):
    """新装机器上首页必须显示 0 而不是报错（以前是永远「—」）。"""
    res = client.get("/api/stats/summary", headers=env["headers"])
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] is True
    for k in ("messages", "mcp_servers", "memory_global", "memory_users", "identity_binds"):
        assert k in body, body
        assert isinstance(body[k], int), (k, body[k])
    assert body["messages"] == 0


def test_messages_scalar_only(env):
    """列表只能带标量字段：一条会话里可能挂着整段聊天记录，绝不能整段吐出来。"""
    payload = {
        "conv:1": {"count": 3, "ts": 1700000000, "title": "张三",
                   "messages": [{"text": "很长的一段对话" * 100}]},
    }
    monkeypatch_target = console_ext._settings
    import types

    fake = types.SimpleNamespace(
        context_file=lambda s: "<fake>/context.json",
        load_conversations=lambda s, limit=200: [
            {"count": 3, "ts": 1700000000, "title": "张三",
             "messages": [{"text": "很长的一段对话" * 100}]},
            "不是字典的脏数据",
        ],
        load_dsh_conversations=lambda s, limit=20: [{"key": "dsh:1", "count": 2, "ts": 1}],
    )
    orig = console_ext._message_store
    console_ext._message_store = lambda: fake
    try:
        res = client.get("/api/messages/list", headers=env["headers"])
    finally:
        console_ext._message_store = orig
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["total"] == 1                      # 脏数据被跳过
    item = body["conversations"][0]
    assert "messages" not in item, item             # 正文不外泄
    assert set(item.keys()) <= {"count", "key", "title", "name", "platform", "scene",
                                "room", "ts", "last", "last_text"}
    assert item["title"] == "张三" and item["count"] == 3
    assert body["dsh"][0]["key"] == "dsh:1"
    assert monkeypatch_target is not None


def test_messages_keeps_scene_room_and_synthesizes_key(env):
    """scene/room 必须在返回里，并按它们还原出 key。

    以前白名单没放 scene/room：多个 QQ 会话在界面上全显示成「QQ 会话」，
    分不清是哪个群、哪个好友。key 则用来给前端做去重与稳定 rowkey。
    """
    import types

    fake = types.SimpleNamespace(
        context_file=lambda s: "<fake>/context.json",
        load_conversations=lambda s, limit=200: [
            {"platform": "qq", "scene": "group", "room": "123456", "count": 9, "last": "在的"},
            {"platform": "qq", "scene": "private", "room": "654321", "count": 2, "last": "收到"},
            {"platform": "wechat", "scene": "private", "room": "wxid_abc", "count": 1, "last": "你好"},
        ],
        load_dsh_conversations=lambda s, limit=20: [],
    )
    orig = console_ext._message_store
    console_ext._message_store = lambda: fake
    try:
        res = client.get("/api/messages/list", headers=env["headers"])
    finally:
        console_ext._message_store = orig
    assert res.status_code == 200, res.text
    convs = res.json()["conversations"]
    assert [(c["platform"], c["scene"], c["room"]) for c in convs] == [
        ("qq", "group", "123456"),
        ("qq", "private", "654321"),
        ("wechat", "private", "wxid_abc"),
    ]
    # key 由 platform+scene+room 还原，且与 message_store._parse_key 互逆
    assert [c["key"] for c in convs] == ["group_123456", "654321", "wechat:private:wxid_abc"]


def test_conversation_key_roundtrips_with_parse_key():
    """_conversation_key 造出来的 key，喂回 message_store._parse_key 必须得到同一组值。"""
    from qbotmanager.core.message_store import _parse_key

    for platform, scene, room in (("qq", "group", "123456"), ("qq", "private", "654321"),
                                  ("wechat", "private", "wxid_abc"),
                                  ("feishu", "group", "oc_x")):
        key = console_ext._conversation_key(platform, scene, room)
        assert _parse_key(key)[1:] == (scene, room), (platform, scene, room, key)
    assert console_ext._conversation_key("qq", "private", "") == ""   # 没房间号就不造 key


def test_messages_limit_is_clamped(env):
    seen = {}

    def fake_load(s, limit=200):
        seen["limit"] = limit
        return []

    import types

    fake = types.SimpleNamespace(load_conversations=fake_load,
                                 load_dsh_conversations=lambda s, limit=20: [],
                                 context_file=lambda s: "<fake>/context.json")
    orig = console_ext._message_store
    console_ext._message_store = lambda: fake
    try:
        assert client.get("/api/messages/list?limit=99999", headers=env["headers"]).status_code == 200
        assert seen["limit"] == 500                # 上限保护
        client.get("/api/messages/list?limit=0", headers=env["headers"])
        assert seen["limit"] == 50                 # 非法值回落默认
    finally:
        console_ext._message_store = orig
