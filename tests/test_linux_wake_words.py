# -*- coding: utf-8 -*-
"""A3 回归：POST /api/ai/wake-words（未登录 401 + 正常返回结构）。

背景：控制台 AI 大脑页的「按人格生成」按钮一直 POST 这个地址，而后端从来没有实现过，
点一次必弹「唤醒词生成失败：Not Found」。这里补的后端实现**不调用外部模型**
（确定性正则提取 + 档案默认词兜底），所以测试里也不能有任何网络依赖。
"""
import os
import sys
import tempfile

import pytest

SANDBOX = tempfile.mkdtemp(prefix="sw-wake-")
os.environ["XDG_DATA_HOME"] = SANDBOX
os.environ["XDG_CONFIG_HOME"] = SANDBOX
sys.path.insert(0, r"D:\ai\QBotManager\src")

from fastapi.testclient import TestClient  # noqa: E402

from astroswarm_linux import headless_config, platform_info  # noqa: E402
from astroswarm_linux.api import app  # noqa: E402

client = TestClient(app)
TOKEN = "wake-token"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(platform_info, "config_home", lambda: tmp_path)
    monkeypatch.setattr(platform_info, "data_home", lambda: tmp_path)
    headless_config.save({**headless_config.load(), "account_token": TOKEN})
    yield {"headers": {"Authorization": f"Bearer {TOKEN}"}}


def test_wake_words_requires_auth():
    """未登录必须 401（与其余 console_ext 接口同一个鉴权口径）。"""
    assert client.post("/api/ai/wake-words", json={}).status_code == 401


def test_wake_words_from_personality(env):
    """给了人格文本：按名字句式提取称呼，返回结构 {ok, words, source}。"""
    res = client.post(
        "/api/ai/wake-words",
        json={"personality": "你是李清菡，19 岁大学生，群友都叫我学姐"},
        headers=env["headers"],
    )
    assert res.status_code == 200, res.text
    d = res.json()
    assert d["ok"] is True
    assert isinstance(d["words"], list) and d["words"]
    assert "李清菡" in d["words"]
    assert "学姐" in d["words"]
    assert d["source"] == "persona"


def test_wake_words_http_always_returns_words(env):
    """无论有没有人格文本，HTTP 层永远 200 + 非空 words（按钮不会再弹 Not Found）。"""
    res = client.post("/api/ai/wake-words", json={"persona_mode": "eva"},
                      headers=env["headers"])
    assert res.status_code == 200, res.text
    d = res.json()
    assert d["ok"] is True
    assert isinstance(d["words"], list) and d["words"]
    assert all(isinstance(w, str) and w for w in d["words"])
    assert d["source"] in ("persona", "default")


def test_wake_words_defaults_when_persona_missing(env, monkeypatch):
    """人格文本彻底拿不到（读失败/空）→ 退回档案默认词（eva），不是空数组、不抛异常。"""
    from astroswarm_linux import console_ext

    class _Cfg:
        @staticmethod
        def read_personality(_settings):
            return ""

    monkeypatch.setattr(console_ext, "_ai_config_module", lambda: _Cfg)
    d = console_ext.wake_words("", "eva")
    assert d["ok"] is True
    assert d["words"] == ["EVA", "eva", "艾娃"]
    assert d["source"] == "default"


def test_wake_words_falls_back_when_persona_has_no_name(env):
    """人格文本里没有任何称呼句式 → 也是默认词，不是空数组。"""
    res = client.post("/api/ai/wake-words",
                      json={"personality": "一个安静的人，喜欢在深夜写代码。"},
                      headers=env["headers"])
    assert res.status_code == 200, res.text
    d = res.json()
    assert d["words"] and "李清菡" in d["words"]
    assert d["source"] == "default"
