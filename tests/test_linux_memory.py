# -*- coding: utf-8 -*-
"""记忆时间线接口回归：鉴权 / 空库不崩 / 越界 400 / 清空要确认 / 原子写 / 自动备份。

跑法：$env:PYTHONPATH="D:\ai\QBotManager\src"; .\.test_venv\Scripts\python.exe -m pytest tests/test_linux_memory.py -q
"""
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

SANDBOX = tempfile.mkdtemp(prefix="sw-mem-")
os.environ["XDG_DATA_HOME"] = SANDBOX
os.environ["XDG_CONFIG_HOME"] = SANDBOX
sys.path.insert(0, r"D:\ai\QBotManager\src")

from fastapi.testclient import TestClient  # noqa: E402

from astroswarm_linux import console_ext, headless_config, platform_info  # noqa: E402
from astroswarm_linux.api import app  # noqa: E402

client = TestClient(app)
TOKEN = "mem-token"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(platform_info, "config_home", lambda: tmp_path)
    headless_config.save({**headless_config.load(), "account_token": TOKEN})
    mem = tmp_path / "bot" / "data" / "ai" / "aichat_memory.json"
    monkeypatch.setattr(console_ext, "_memory_file", lambda: mem)
    return {"mem": mem, "headers": {"Authorization": f"Bearer {TOKEN}"}}


def _write(mem: Path, data):
    mem.parent.mkdir(parents=True, exist_ok=True)
    mem.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_memory_requires_auth():
    assert client.get("/api/memory/list").status_code == 401
    assert client.get("/api/memory/export").status_code == 401
    assert client.post("/api/memory/delete", json={"index": 0}).status_code == 401
    assert client.post("/api/memory/clear", json={"confirm": True}).status_code == 401


def test_memory_list_empty(env):
    """没有记忆库也要返回空结构，不能 500（新用户第一次打开就是这个状态）。"""
    res = client.get("/api/memory/list", headers=env["headers"])
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] and body["total"] == 0 and body["global"] == [] and body["users"] == []


def test_memory_list_groups(env):
    _write(env["mem"], {"global": ["喜欢喝美式"], "users": {"u1": ["a", "b"], "u2": ["c"]}})
    body = client.get("/api/memory/list", headers=env["headers"]).json()
    assert body["total"] == 4
    assert body["global"] == ["喜欢喝美式"]
    assert body["users"][0]["user"] == "u1" and body["users"][0]["count"] == 2


def test_memory_broken_file_reports_error(env):
    """坏文件必须报错，绝不静默当空（否则下一次保存就把用户记忆覆盖没了）。"""
    env["mem"].parent.mkdir(parents=True, exist_ok=True)
    env["mem"].write_text("{坏掉的内容", encoding="utf-8")
    res = client.get("/api/memory/list", headers=env["headers"])
    assert res.status_code == 500 and "解析失败" in res.text
    # 不能因为读失败就把原文件改掉
    assert env["mem"].read_text(encoding="utf-8") == "{坏掉的内容"


def test_memory_delete_bounds_and_backup(env):
    _write(env["mem"], {"global": ["g0", "g1"], "users": {"u1": ["x"]}})
    assert client.post("/api/memory/delete", json={"scope": "global", "index": 5},
                       headers=env["headers"]).status_code == 400
    assert client.post("/api/memory/delete", json={"scope": "user", "user": "nope", "index": 0},
                       headers=env["headers"]).status_code == 404
    res = client.post("/api/memory/delete", json={"scope": "global", "index": 0},
                      headers=env["headers"])
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["removed"] == "g0" and body["needs_restart"] is True
    assert body["backup"] and Path(body["backup"]).exists()
    left = json.loads(env["mem"].read_text(encoding="utf-8"))
    assert left["global"] == ["g1"] and left["users"] == {"u1": ["x"]}


def test_memory_delete_negative_index(env):
    _write(env["mem"], {"global": ["g0", "g1", "g2"], "users": {}})
    res = client.post("/api/memory/delete", json={"scope": "global", "index": -1},
                      headers=env["headers"])
    assert res.json()["removed"] == "g2"


def test_memory_clear_requires_confirm(env):
    _write(env["mem"], {"global": ["g0"], "users": {"u1": ["x"]}})
    assert client.post("/api/memory/clear", json={}, headers=env["headers"]).status_code == 400
    assert client.post("/api/memory/clear", json={"confirm": False},
                       headers=env["headers"]).status_code == 400
    assert json.loads(env["mem"].read_text(encoding="utf-8"))["global"] == ["g0"]
    res = client.post("/api/memory/clear", json={"confirm": True}, headers=env["headers"])
    assert res.status_code == 200 and res.json()["cleared"] == 2
    after = json.loads(env["mem"].read_text(encoding="utf-8"))
    assert after == {"global": [], "users": {}}
    assert res.json()["backup"] and Path(res.json()["backup"]).exists()


def test_memory_export_json_and_md(env):
    _write(env["mem"], {"global": ["喜欢喝美式"], "users": {"u1": ["在杭州"]}})
    r1 = client.get("/api/memory/export", headers=env["headers"])
    assert r1.status_code == 200 and "attachment" in r1.headers["content-disposition"]
    assert json.loads(r1.text)["global"] == ["喜欢喝美式"]
    r2 = client.get("/api/memory/export?fmt=md", headers=env["headers"])
    assert r2.status_code == 200 and "喜欢喝美式" in r2.text and "u1" in r2.text
    # <a download> 走 token 查询参数
    r3 = client.get(f"/api/memory/export?token={TOKEN}")
    assert r3.status_code == 200


def test_memory_write_is_atomic(env):
    _write(env["mem"], {"global": ["g0"], "users": {}})
    client.post("/api/memory/delete", json={"scope": "global", "index": 0}, headers=env["headers"])
    leftovers = [p.name for p in env["mem"].parent.glob("*.tmp*")]
    assert leftovers == [], leftovers


# ---------------------------------------------------- 破坏性缺省（回归：缺省参数不能删掉数据）

def test_memory_delete_requires_explicit_index(env):
    """不传 index 以前缺省 -1 → 静默删掉最后一条；现在必须 400，且一条都不能少。"""
    _write(env["mem"], {"global": ["g0", "g1", "g2"], "users": {"u1": ["x"]}})
    headers = env["headers"]

    for body in ({}, {"scope": "global"}, {"scope": "global", "index": None},
                 {"scope": "global", "index": "abc"}, {"scope": "global", "index": True}):
        res = client.post("/api/memory/delete", json=body, headers=headers)
        assert res.status_code == 400, (body, res.status_code, res.text)
    left = json.loads(env["mem"].read_text(encoding="utf-8"))
    assert left["global"] == ["g0", "g1", "g2"] and left["users"] == {"u1": ["x"]}


def test_memory_delete_scope_whitelist(env):
    """scope 无白名单时 `{"scope":"admin"}` 会按 global 删掉一条；现在必须 400。"""
    _write(env["mem"], {"global": ["g0", "g1"], "users": {}})
    res = client.post("/api/memory/delete", json={"scope": "admin", "index": 0},
                      headers=env["headers"])
    assert res.status_code == 400 and "scope" in res.text
    assert json.loads(env["mem"].read_text(encoding="utf-8"))["global"] == ["g0", "g1"]
    # 函数层也不能被绕过（selftest / 别的调用方直接调 memory_delete）
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as ei:
        console_ext.memory_delete("admin", "", 0)
    assert ei.value.status_code == 400


def test_memory_delete_user_scope_requires_user(env):
    _write(env["mem"], {"global": ["g0"], "users": {"u1": ["x"]}})
    for body in ({"scope": "user", "index": 0}, {"scope": "user", "user": "", "index": 0},
                 {"scope": "user", "user": None, "index": 0}):
        res = client.post("/api/memory/delete", json=body, headers=env["headers"])
        assert res.status_code == 400, (body, res.text)
    assert json.loads(env["mem"].read_text(encoding="utf-8"))["users"] == {"u1": ["x"]}


def test_memory_backup_names_do_not_collide(env):
    """同一秒里连续删除，备份名不能互相覆盖（以前只到秒，4 次删只剩 1 份备份）。"""
    _write(env["mem"], {"global": ["g0", "g1", "g2", "g3"], "users": {}})
    names = []
    for _ in range(4):
        res = client.post("/api/memory/delete", json={"scope": "global", "index": 0},
                          headers=env["headers"])
        assert res.status_code == 200, res.text
        names.append(res.json()["backup"])
    assert len(set(names)) == 4, names
    assert all(Path(n).exists() for n in names)
    assert len(list(env["mem"].parent.glob("aichat_memory.json.bak.*"))) == 4


def test_memory_concurrent_deletes_do_not_lose_updates(env):
    """8 个线程同时删 index=0：必须正好少 8 条，且文件仍是合法 JSON。

    以前没有锁：读-改-写互相覆盖，10 线程删 50 条只删掉 1 条，还会因固定 tmp 名
    撞 PermissionError / 写出坏 JSON。
    """
    import threading

    items = ["g%d" % i for i in range(50)]
    _write(env["mem"], {"global": list(items), "users": {}})
    errors = []

    def worker():
        try:
            console_ext.memory_delete("global", "", 0)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert not errors, errors

    data = json.loads(env["mem"].read_text(encoding="utf-8"))   # 必须是合法 JSON
    assert len(data["global"]) == 42, len(data["global"])
    # 没有被删重（还是 42 条互不相同的记录）
    assert len(set(data["global"])) == 42
    assert [p.name for p in env["mem"].parent.glob("*.tmp*")] == []
