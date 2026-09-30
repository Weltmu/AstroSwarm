# -*- coding: utf-8 -*-
"""工具动作桥测试（跑在 bot venv：有 nonebot；桌面构建 venv 没有）。

覆盖 2026-09-27 工坊地基的动作回执链路：
- ToolContext.bind_send 换绑 / 关闭动作；
- 普通能力包：动作先排队，工具返回后由主程序真执行，回执合并回结果；
- 动作失败 / 权限不够时结果里必须有 effect_errors（插件不能谎报成功）；
- 沙箱插件的动作也只能经主程序校验后执行，失败一样写回真相。
"""
import asyncio
import importlib
import json
import os
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
if not os.environ.get("QBM_POINTER_DIR"):
    os.environ["QBM_POINTER_DIR"] = str(Path(tempfile.mkdtemp(prefix="qbm_bridge_ptr_")))

AI_DIR = ROOT / "src" / "qbotmanager" / "assets" / "plugins" / "ai"
DATA_DIR = Path(tempfile.mkdtemp(prefix="qbm_bridge_data_"))


def _stub_localstore():
    """localstore 只用到三个取路径的函数，测试里换到临时目录。"""
    if "nonebot_plugin_localstore" in sys.modules:
        return
    mod = types.ModuleType("nonebot_plugin_localstore")
    mod.get_plugin_data_dir = lambda *a, **k: DATA_DIR
    mod.get_plugin_data_file = lambda *a, **k: DATA_DIR / str(a[0] if a else "data.json")
    mod.get_plugin_config_file = lambda *a, **k: DATA_DIR / str(a[0] if a else "config.json")
    sys.modules["nonebot_plugin_localstore"] = mod


def _bridge():
    """加载 tools_bridge，跳过 ai/__init__（NoneBot 插件入口，依赖 localstore）。"""
    _stub_localstore()
    if "qbotmanager.assets.plugins.ai" not in sys.modules:
        pkg = types.ModuleType("qbotmanager.assets.plugins.ai")
        pkg.__path__ = [str(AI_DIR)]
        sys.modules["qbotmanager.assets.plugins.ai"] = pkg
    return importlib.import_module("qbotmanager.assets.plugins.ai.tools_bridge")


def _runtime():
    from qbotmanager.core.agent.runtime import AgentRuntime
    return AgentRuntime()


def _register(runtime, handler, name="sender", permissions=("send_message",)):
    from qbotmanager.core.agent.tool import ToolSpec
    runtime.registry.register(ToolSpec(name=name, description="测试工具", parameters={},
                                       permissions=list(permissions), handler=handler))


def test_bind_send_swaps_and_disables():
    from qbotmanager.core.agent.tool import ToolContext

    ctx = ToolContext(permissions=[], send=lambda a, p: {"ok": True, "who": "orig"})
    assert ctx.send("x")["who"] == "orig"
    seen = []
    ctx.bind_send(lambda a, p: (seen.append((a, dict(p))),
                                {"ok": True, "queued": True})[1])
    assert ctx.send("send_message", {"text": "hi"})["queued"] is True
    assert seen == [("send_message", {"text": "hi"})]
    ctx.bind_send(None)
    assert ctx.send("x")["error"] == "action_unavailable"


def test_normal_tool_queues_action_and_main_process_runs_it(monkeypatch):
    from qbotmanager.core.agent.tool import ToolContext

    tb = _bridge()
    runtime = _runtime()
    calls = []

    async def fake_send(params, ctx):
        calls.append(dict(params))
        return {"ok": True, "action": "send_message"}

    monkeypatch.setitem(tb._ACTIONS, "send_message", fake_send)

    def handler(ctx, args):
        ctx.send("send_message", {"text": "hello"})
        return '{"ok": true}'

    _register(runtime, handler)
    ctx = ToolContext(permissions=["send_message"], platform="qq_official",
                      scene="group", user_id="1", group_id="2")
    out = json.loads(asyncio.run(
        tb.execute_tool_with_actions(runtime, "sender", {}, ctx)))
    assert out["ok"] is True
    assert calls == [{"text": "hello"}]
    assert ctx.effect_results == [{"ok": True, "action": "send_message"}]


def test_failed_action_is_written_back(monkeypatch):
    from qbotmanager.core.agent.tool import ToolContext

    tb = _bridge()
    runtime = _runtime()

    async def fake_send(params, ctx):
        return {"ok": False, "error": "send_failed", "action": "send_message"}

    monkeypatch.setitem(tb._ACTIONS, "send_message", fake_send)

    def handler(ctx, args):
        ctx.send("send_message", {"text": "hello"})
        return '{"ok": true, "sent": true}'

    _register(runtime, handler)
    ctx = ToolContext(permissions=["send_message"], platform="qq_official", scene="group")
    out = json.loads(asyncio.run(
        tb.execute_tool_with_actions(runtime, "sender", {}, ctx)))
    assert out["ok"] is False
    assert out["effect_errors"] == [{"action": "send_message", "error": "send_failed"}]


def test_action_without_permission_is_denied_by_main_process():
    """走真实 do_action：微信私聊没有 group_admin，禁言必须被拒。"""
    from qbotmanager.core.agent.tool import ToolContext

    tb = _bridge()
    runtime = _runtime()

    def handler(ctx, args):
        ctx.send("mute_user", {"user_id": "42", "minutes": 5})
        return '{"ok": true, "done": "muted"}'

    _register(runtime, handler, name="muter", permissions=())
    ctx = ToolContext(permissions=[], platform="wechat_ilink", scene="private")
    out = json.loads(asyncio.run(
        tb.execute_tool_with_actions(runtime, "muter", {}, ctx)))
    assert out["ok"] is False
    assert out["effect_errors"][0]["action"] == "mute_user"
    assert out["effect_errors"][0]["error"] == "permission_denied"


SANDBOX_SENDER = '''
import json


def handle(ctx, args):
    res = ctx.send("send_message", {"text": "来自沙箱"})
    return json.dumps({"ok": bool(res.get("ok")), "reply": res}, ensure_ascii=False)
'''

SANDBOX_LIAR = '''
import json


def handle(ctx, args):
    res = ctx.send("send_message", {"text": "来自沙箱"})
    return json.dumps({"ok": True, "reply": res}, ensure_ascii=False)
'''


def _sandbox_pack(tmp: Path, code: str) -> Path:
    pack = tmp / "pack_sbx"
    (pack / "tools").mkdir(parents=True, exist_ok=True)
    manifest = {"id": "sbx_demo", "name": "沙箱发送", "version": "1.0.0",
                "kind": "tool-pack", "description": "测试沙箱动作桥",
                "adapters": [], "permissions": ["send_message"], "sandbox": True,
                "tools": [{"name": "sbx_sender", "description": "发一条消息",
                           "parameters": {}, "permissions": ["send_message"],
                           "lifecycle": "none"}]}
    (pack / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False),
                                        encoding="utf-8")
    (pack / "tools" / "sbx_sender.py").write_text(code, encoding="utf-8")
    return pack


def test_sandbox_tool_action_goes_through_main_process(tmp_path, monkeypatch):
    from qbotmanager.core.agent.tool import ToolContext

    tb = _bridge()
    runtime = _runtime()
    assert runtime.registry.load_pack(_sandbox_pack(tmp_path, SANDBOX_SENDER)) == 1
    seen = []

    async def fake_send(params, ctx):
        seen.append(dict(params))
        return {"ok": True, "action": "send_message", "source": ctx.source}

    monkeypatch.setitem(tb._ACTIONS, "send_message", fake_send)
    ctx = ToolContext(permissions=["send_message"], platform="qq_official",
                      scene="group", user_id="1", group_id="2")
    out = json.loads(asyncio.run(
        tb.execute_tool_with_actions(runtime, "sbx_sender", {}, ctx)))
    assert out["ok"] is True
    assert out["reply"]["ok"] is True
    assert seen == [{"text": "来自沙箱"}]


def test_sandbox_tool_cannot_hide_failed_action(tmp_path, monkeypatch):
    """沙箱里动作失败、插件硬说成功 → 结果被改回真相。"""
    from qbotmanager.core.agent.tool import ToolContext

    tb = _bridge()
    runtime = _runtime()
    assert runtime.registry.load_pack(_sandbox_pack(tmp_path, SANDBOX_LIAR)) == 1

    async def fake_send(params, ctx):
        return {"ok": False, "error": "window_closed", "action": "send_message"}

    monkeypatch.setitem(tb._ACTIONS, "send_message", fake_send)
    ctx = ToolContext(permissions=["send_message"], platform="qq_official", scene="group")
    out = json.loads(asyncio.run(
        tb.execute_tool_with_actions(runtime, "sbx_sender", {}, ctx)))
    assert out["ok"] is False
    assert out["effect_errors"][0]["error"] == "window_closed"
