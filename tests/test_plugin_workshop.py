# -*- coding: utf-8 -*-
"""AI 插件工坊测试：配置 / 校验 / 安装回滚 / 沙箱 / 通道裁剪 / 动作回执。"""
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
if not os.environ.get("QBM_POINTER_DIR"):
    os.environ["QBM_POINTER_DIR"] = str(tempfile.mkdtemp(prefix="qbm_ws_ptr_"))

from qbotmanager.core.agent import sandbox          # noqa: E402
from qbotmanager.core.agent.tool import (           # noqa: E402
    ToolContext,
    ToolSpec,
    ToolUnavailableError,
    merge_effect_report,
)
from qbotmanager.core.settings import Settings      # noqa: E402
from qbotmanager.core import workshop               # noqa: E402
from qbotmanager.core.workshop import config as ws_config   # noqa: E402
from qbotmanager.core.workshop import generator, installer, validator  # noqa: E402

GOOD_TOOL = '''
import json


def handle(ctx, args):
    city = str(args.get("city") or "").strip()
    if not city:
        return json.dumps({"ok": False, "error": "missing_city"}, ensure_ascii=False)
    res = ctx.send("http_request", {"url": "https://example.com/?q=" + city})
    if not res.get("ok"):
        return json.dumps({"ok": False, "error": "api_failed"}, ensure_ascii=False)
    return json.dumps({"ok": True, "city": city, "n": len(res.get("text") or "")},
                      ensure_ascii=False)
'''


def _settings(tmp: Path):
    s = Settings(tmp)
    s.ensure_dirs()
    return s


def _good_files(pid="weather_demo", adapters=("qq_official", "wechat_ilink"),
                permissions=("network",), code=GOOD_TOOL):
    manifest = {
        "id": pid, "name": "查天气", "version": "1.0.0", "kind": "tool-pack",
        "description": "查天气的插件", "adapters": list(adapters),
        "permissions": list(permissions), "sandbox": True,
        "tools": [{
            "name": "check_weather",
            "description": "用户问天气的时候用",
            "parameters": {"type": "object",
                           "properties": {"city": {"type": "string", "description": "城市"}},
                           "required": ["city"]},
            "permissions": list(permissions), "lifecycle": "none",
        }],
    }
    return {"manifest.json": json.dumps(manifest, ensure_ascii=False, indent=2),
            "tools/check_weather.py": code}


def _plan():
    return {"id": "weather_demo", "name": "查天气", "what": "查城市天气",
            "tools": [{"name": "check_weather", "desc": "查天气时用",
                       "example_args": {"city": "北京"}}],
            "adapters": ["qq_official", "wechat_ilink"], "permissions": ["network"],
            "channel_note": "QQ 和微信私聊都能用", "steps": ["调接口", "返回数据"]}


# ---- 工坊配置：强制强模型 ----


def test_workshop_config_rejects_weak_provider(tmp_path):
    s = _settings(tmp_path)
    with pytest.raises(ValueError):
        ws_config.save(s, {"provider": "custom", "api_key": "x", "model": "small"})
    ok, why = ws_config.is_ready(s)
    assert ok is False and why


def test_workshop_config_roundtrip(tmp_path):
    s = _settings(tmp_path)
    ws_config.save(s, {"provider": "deepseek", "api_key": "sk-test-1234567890"})
    st = workshop.status(s)
    assert st["ready"] is True
    assert st["provider"] == "deepseek"
    assert st["model"] == "deepseek-chat"
    assert "sk-test" not in st["api_key_masked"]
    assert ws_config.save(s, {"provider": "anthropic", "api_key": "k",
                              "model": "claude-x"})["model"] == "claude-x"


# ---- 校验 ----


def test_validator_accepts_good_pack():
    issues = validator.validate_files(_good_files(), set())
    assert [i for i in issues if i["level"] == "error"] == []


def test_validator_catches_bad_import_and_hardcoded_reply():
    bad = '''
import requests


def handle(ctx, args):
    return json.dumps({"ok": True, "reply": "已经帮你查好啦"})
'''
    issues = validator.validate_files(_good_files(code=bad), set())
    codes = {i["code"] for i in issues if i["level"] == "error"}
    assert "bad_import" in codes or "syntax_error" in codes
    assert "hardcoded_reply" in codes


def test_validator_catches_permission_and_channel_conflict():
    code = '''
import json


def handle(ctx, args):
    ctx.send("mute_user", {"user_id": "1", "group_id": "2", "minutes": 5})
    return json.dumps({"ok": True})
'''
    files = _good_files(adapters=("wechat_ilink",), permissions=(), code=code)
    issues = validator.validate_files(files, set())
    codes = {i["code"] for i in issues if i["level"] == "error"}
    assert "permission_missing" in codes
    assert "channel_mismatch" in codes


def test_validator_rejects_dup_tool_and_sandbox_off():
    files = _good_files()
    manifest = json.loads(files["manifest.json"])
    manifest["sandbox"] = False
    files["manifest.json"] = json.dumps(manifest, ensure_ascii=False)
    issues = validator.validate_files(files, {"check_weather"})
    codes = {i["code"] for i in issues if i["level"] == "error"}
    assert "sandbox_required" in codes
    assert "tool_exists" in codes


def test_prompts_contain_contract_and_hard_rules():
    from qbotmanager.core.workshop import prompts

    text = prompts.CODE_SYSTEM
    for needle in ("manifest.json", "handle(ctx, args)", "http_request",
                   "data_write", "微信只能私聊", "禁止任何中文话术"):
        assert needle in text


# ---- 安装 / 历史 / 回滚 / 卸载 ----


def test_install_history_rollback_uninstall(tmp_path):
    s = _settings(tmp_path)
    first = installer.install(s, "demo_pack", _good_files(pid="demo_pack"),
                              {"name": "查天气"})
    assert first["ok"] and first["backup"] == ""
    assert (Path(s.root) / "tool_packs" / "demo_pack" / "manifest.json").exists()
    second = installer.install(s, "demo_pack", _good_files(pid="demo_pack"),
                               {"name": "查天气"})
    assert second["backup"]
    assert len(installer.history(s, "demo_pack")) == 1
    assert installer.rollback(s, "demo_pack")["ok"]
    rows = installer.generated(s)
    assert rows and rows[0]["id"] == "demo_pack"
    assert installer.uninstall(s, "demo_pack")["ok"]
    assert not (Path(s.root) / "tool_packs" / "demo_pack").exists()
    assert len(installer.history(s, "demo_pack")) >= 2


def test_unique_id_avoids_clash(tmp_path):
    s = _settings(tmp_path)
    installer.install(s, "demo_pack", _good_files(pid="demo_pack"), {})
    assert installer.unique_id(s, "demo_pack") == "demo_pack-2"


# ---- 通道裁剪 + 动作回执（运行时短板）----


def test_registry_filters_by_channel():
    from qbotmanager.core.agent.registry import ToolRegistry

    reg = ToolRegistry()
    reg.register(ToolSpec(name="qq_only", description="d", parameters={},
                          permissions=[], handler=lambda c, a: "{}",
                          adapters=["qq_official"]))
    reg.register(ToolSpec(name="any_channel", description="d", parameters={},
                          permissions=[], handler=lambda c, a: "{}"))
    names_qq = {s["function"]["name"] for s in reg.schemas("qq_official")}
    names_wx = {s["function"]["name"] for s in reg.schemas("wechat")}
    assert names_qq == {"qq_only", "any_channel"}
    assert names_wx == {"any_channel"}
    assert len(reg.schemas()) == 2          # 不传 platform = 旧行为，不过滤


def test_registry_rejects_wrong_channel_and_reports_effect_failure():
    from qbotmanager.core.agent.registry import ToolRegistry

    reg = ToolRegistry()
    reg.register(ToolSpec(name="qq_only", description="d", parameters={},
                          permissions=[], handler=lambda c, a: '{"ok": true}',
                          adapters=["qq_official"]))
    ctx = ToolContext(permissions=[], platform="wechat", scene="private")
    with pytest.raises(ToolUnavailableError):
        reg.execute("qq_only", {}, ctx)

    def handler(c, a):
        c.send("send_message", {"text": "hi"})
        return '{"ok": true, "action": "send_message"}'
    reg.register(ToolSpec(name="sender", description="d", parameters={},
                          permissions=[], handler=handler))
    tool_ctx = ToolContext(permissions=[],
                           send=lambda action, params: {"ok": False,
                                                        "error": "send_failed"})
    out = json.loads(reg.execute("sender", {}, tool_ctx))
    assert out["ok"] is False
    assert out["effect_errors"][0]["error"] == "send_failed"
    assert merge_effect_report('{"ok": true}', [{"ok": True}]) == '{"ok": true}'


def test_registry_load_pack_records_meta_and_sandbox(tmp_path):
    from qbotmanager.core.agent.registry import ToolRegistry

    pack = tmp_path / "sandboxed"
    (pack / "tools").mkdir(parents=True)
    manifest = json.loads(_good_files(pid="sandboxed")["manifest.json"])
    (pack / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False),
                                        encoding="utf-8")
    (pack / "tools" / "check_weather.py").write_text(GOOD_TOOL, encoding="utf-8")
    reg = ToolRegistry()
    assert reg.load_pack(pack) == 1
    meta = reg.pack_meta("sandboxed")
    assert meta["sandbox"] is True and meta["version"] == "1.0.0"
    ctx = ToolContext(permissions=["network"], platform="qq_official", scene="group")
    with pytest.raises(ToolUnavailableError):
        reg.execute("check_weather", {}, ctx)      # 沙箱工具必须走 execute_async


# ---- 沙箱 ----


def _sandbox_pack(tmp: Path, code: str, name="demo"):
    pack = tmp / f"pack_{name}"
    (pack / "tools").mkdir(parents=True, exist_ok=True)
    (pack / "manifest.json").write_text("{}", encoding="utf-8")
    (pack / "tools" / f"{name}.py").write_text(code, encoding="utf-8")
    return pack


def test_sandbox_blocks_imports_and_file_access(tmp_path):
    code = '''
import json


def handle(ctx, args):
    out = {"ok": True, "can": ctx.can("network"), "src": ctx.source}
    res = ctx.send("http_request", {"url": "https://example.com"})
    out["http"] = bool(res.get("ok"))
    try:
        import socket
        out["socket"] = "allowed"
    except ImportError as exc:
        out["socket"] = str(exc)[:30]
    try:
        open("x.txt", "w")
        out["open"] = "allowed"
    except PermissionError as exc:
        out["open"] = str(exc)[:20]
    return json.dumps(out, ensure_ascii=False)
'''
    pack = _sandbox_pack(tmp_path, code)
    ctx = ToolContext(permissions=["network"], platform="qq_official", scene="group",
                      user_id="1", group_id="2")

    async def host(action, params, tool_ctx):
        return {"ok": True, "action": action, "text": "abc"}
    out = json.loads(asyncio.run(sandbox.run_tool(pack, "demo", {}, ctx, host,
                                                  timeout=20)))
    assert out["can"] is True and out["src"] == "qq_official:group"
    assert out["http"] is True
    assert out["socket"].startswith("sandbox_denied")
    assert out["open"].startswith("sandbox_denied")


def test_sandbox_timeout_kills_and_raises(tmp_path):
    code = '''
import json


def handle(ctx, args):
    while True:
        pass
    return json.dumps({"ok": True})
'''
    pack = _sandbox_pack(tmp_path, code)
    ctx = ToolContext(permissions=[], platform="qq_official", scene="group")

    async def host(action, params, tool_ctx):
        return {"ok": True}
    with pytest.raises(sandbox.SandboxTimeout):
        asyncio.run(sandbox.run_tool(pack, "demo", {}, ctx, host, timeout=3))


def test_sandbox_tool_exception_is_reported(tmp_path):
    code = '''
import json


def handle(ctx, args):
    raise ValueError("boom")
'''
    pack = _sandbox_pack(tmp_path, code)
    ctx = ToolContext(permissions=[], platform="wechat", scene="private")

    async def host(action, params, tool_ctx):
        return {"ok": True}
    with pytest.raises(sandbox.SandboxError) as info:
        asyncio.run(sandbox.run_tool(pack, "demo", {}, ctx, host, timeout=15))
    assert "boom" in str(info.value)


# ---- 完整流水线（模型打桩，不打真接口）----


def test_build_pipeline_with_stub_model(tmp_path, monkeypatch):
    s = _settings(tmp_path)
    ws_config.save(s, {"provider": "deepseek", "api_key": "sk-x", "model": "deepseek-chat"})
    calls = {"n": 0}

    def fake_call_model(settings, system, user, timeout=0):
        calls["n"] += 1
        if "规划师" in system:
            return json.dumps(_plan(), ensure_ascii=False)
        return json.dumps({"manifest": json.loads(_good_files()["manifest.json"]),
                           "tools": {"check_weather.py": GOOD_TOOL},
                           "notes": "查天气插件"}, ensure_ascii=False)

    monkeypatch.setattr(generator, "call_model", fake_call_model)
    logs = []
    built = workshop.build(s, "帮我加个查天气的功能", channels=["qq_official"],
                           on_log=logs.append)
    assert built["ok"] is True
    assert built["plan"]["name"] == "查天气"
    assert "manifest.json" in built["files"]
    assert built["report"]["permissions"] == ["network"]
    assert any("沙箱" in note for note in built["report"]["notes"])
    assert calls["n"] == 2                      # 方案 + 代码，没有多余修复
    assert logs
    installed = workshop.install(s, built)
    assert installed["ok"] is True
    assert (Path(s.root) / "tool_packs" / "weather_demo" / "tools"
            / "check_weather.py").exists()


def test_build_repairs_bad_code_once(tmp_path, monkeypatch):
    s = _settings(tmp_path)
    ws_config.save(s, {"provider": "deepseek", "api_key": "sk-x", "model": "deepseek-chat"})
    state = {"code_calls": 0}
    bad_code = "import os\n\n\ndef handle(ctx, args):\n    return '{}'\n"

    def fake_call_model(settings, system, user, timeout=0):
        if "规划师" in system:
            return json.dumps(_plan(), ensure_ascii=False)
        if "修复" in system:
            return json.dumps({"manifest": json.loads(_good_files()["manifest.json"]),
                               "tools": {"check_weather.py": GOOD_TOOL}},
                              ensure_ascii=False)
        state["code_calls"] += 1
        code = bad_code if state["code_calls"] == 1 else GOOD_TOOL
        return json.dumps({"manifest": json.loads(_good_files()["manifest.json"]),
                           "tools": {"check_weather.py": code}},
                          ensure_ascii=False)

    monkeypatch.setattr(generator, "call_model", fake_call_model)
    built = workshop.build(s, "查天气", channels=["qq_official"])
    assert built["attempts"] >= 1
    assert built["ok"] is True


def test_build_refuses_without_model(tmp_path):
    s = _settings(tmp_path)
    with pytest.raises(workshop.generator.WorkshopError):
        workshop.build(s, "随便做个插件")


def test_ai_plugin_files_compile():
    """内置 AI 插件（含新桥接层）必须能编译（运行时环境有 nonebot）。"""
    ai_dir = Path(__file__).resolve().parents[1] / "src" / "qbotmanager" / "assets" / "plugins" / "ai"
    for path in ai_dir.rglob("*.py"):
        compile(path.read_text(encoding="utf-8"), str(path), "exec")


def test_installed_pack_loads_and_runs_in_sandbox(tmp_path, monkeypatch):
    """装完就真能用：安装 → 运行时加载 → 按通道可见 → 沙箱子进程里跑出结果。"""
    from qbotmanager.core.agent.runtime import AgentRuntime

    s = _settings(tmp_path)
    ws_config.save(s, {"provider": "deepseek", "api_key": "sk-x", "model": "deepseek-chat"})

    def fake_call_model(settings, system, user, timeout=0):
        if "规划师" in system:
            return json.dumps(_plan(), ensure_ascii=False)
        return json.dumps({"manifest": json.loads(_good_files()["manifest.json"]),
                           "tools": {"check_weather.py": GOOD_TOOL},
                           "notes": "查天气插件"}, ensure_ascii=False)

    monkeypatch.setattr(generator, "call_model", fake_call_model)
    built = workshop.build(s, "查天气", channels=["qq_official", "wechat_ilink"])
    assert built["ok"] is True
    assert workshop.install(s, built)["ok"] is True

    runtime = AgentRuntime()
    assert runtime.load_packs(Path(s.root) / "tool_packs") >= 1
    assert "check_weather" in runtime.tool_names()
    names = {item["function"]["name"] for item in runtime.schemas("qq_official")}
    assert "check_weather" in names

    calls = []

    async def host(action, params, ctx):
        calls.append((action, dict(params)))
        return {"ok": True, "action": action, "text": "北京 晴 26℃"}

    ctx = ToolContext(permissions=["network"], platform="qq_official", scene="group")
    out = json.loads(asyncio.run(runtime.execute_async(
        "check_weather", {"city": "北京"}, ctx, host=host)))
    assert out["ok"] is True and out["city"] == "北京"
    assert calls and calls[0][0] == "http_request"
    assert "example.com" in calls[0][1]["url"]
