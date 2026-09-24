import json
from pathlib import Path

import pytest

import qbotmanager
from qbotmanager.core.agent import registry
from qbotmanager.core.agent.runtime import get_runtime
from qbotmanager.core.agent.tool import (
    compile_persona,
    ToolContext,
    ToolPackManifest,
    ToolPermissionError,
    ToolSpec,
    validate_persona_card,
)

PACKS_DIR = Path(qbotmanager.__file__).resolve().parent / "assets" / "tool_packs"


class _FakeStore:
    def add_reminder(self, *args, **kwargs):
        return None

    def remember(self, *args, **kwargs):
        return None

    def fetch_memory(self, user):
        return "记忆：喜欢猫"


def _manifest_text(kind="tool-pack", persona="", behavior=None, tools=None):
    data = {
        "id": "demo-pack",
        "name": "演示能力包",
        "version": "1.0.0",
        "kind": kind,
        "description": "测试",
        "adapters": ["qq_official"],
        "min_version": "0.4.0",
        "permissions": ["timer"],
        "tools": tools if tools is not None else [
            {
                "name": "get_time",
                "description": "获取时间",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
                "permissions": ["timer"],
                "lifecycle": "none",
            }
        ],
    }
    if persona:
        data["persona"] = persona
    if behavior:
        data["behavior"] = behavior
    return json.dumps(data, ensure_ascii=False)


def test_manifest_parse_ok():
    m = ToolPackManifest.parse(_manifest_text())
    assert m.kind == "tool-pack" and m.tools[0]["name"] == "get_time"


def test_manifest_persona_pack():
    m = ToolPackManifest.parse(_manifest_text(kind="persona-pack", persona="你是测试人格"))
    assert m.persona == "你是测试人格"


def test_persona_card_parse_and_compile():
    """人格卡 v1：结构化字段可解析，directives/boundaries 强制追加到最后。"""
    card = {
        "format": "astroswarm-persona",
        "version": "1.0",
        "id": "com.demo.eva",
        "name": "测试人格",
        "kind": "persona-pack",
        "description": "测试卡",
        "adapters": ["qq_official"],
        "min_version": "0.4.0",
        "permissions": [],
        "tools": [],
        "identity": {"name": "测试人格", "worldview": "来自测试世界"},
        "personality": {"traits": ["冷静"], "tone": "简洁"},
        "speech": {"self_ref": "我", "style": "短句"},
        "directives": ["保护用户安全"],
        "boundaries": ["不讨论违法内容"],
    }
    assert validate_persona_card(card) is None
    m = ToolPackManifest.parse(card)
    assert m.identity["name"] == "测试人格"
    text = compile_persona(card)
    assert "你是测试人格" in text
    assert "来自测试世界" in text
    assert "保护用户安全" in text and "不讨论违法内容" in text
    # 安全边界必须在最后（防 prompt 注入：不可被卡内指令覆盖）
    assert text.index("不讨论违法内容") > text.index("保护用户安全")
    assert text.rstrip().endswith("不讨论违法内容")


def test_persona_card_validation():
    card = {
        "format": "astroswarm-persona",
        "version": "1.0",
        "id": "com.demo.x",
        "name": "X",
        "kind": "persona-pack",
        "description": "t",
        "adapters": ["qq_official"],
        "min_version": "0.4.0",
        "permissions": [],
        "tools": [],
        "system_prompt": "你是 X",
    }
    assert validate_persona_card(card) is None
    assert validate_persona_card({"format": "bad", "id": "a", "name": "b",
                                  "version": "1", "kind": "persona-pack"}) is not None
    assert validate_persona_card(
        {**card, "name": ""}) is not None
    assert validate_persona_card(
        {**card, "kind": "tool-pack"}) is not None
    assert validate_persona_card({**card, "system_prompt": "", "identity": {}}) is not None
    assert validate_persona_card({}) is not None


def test_persona_field_takes_precedence():
    """旧格式 persona 整段提示词优先于 system_prompt 与结构化字段。"""
    m = ToolPackManifest.parse({
        "id": "p", "name": "P", "version": "1.0.0", "kind": "persona-pack",
        "description": "t", "adapters": ["qq_official"], "min_version": "0.4.0",
        "permissions": [], "tools": [],
        "persona": "旧格式人格全文",
        "system_prompt": "新格式人格全文",
        "identity": {"name": "结构化名字"},
        "directives": ["边界一"],
    })
    text = compile_persona(m)
    assert text.startswith("旧格式人格全文")
    assert "新格式人格全文" not in text
    assert text.rstrip().endswith("边界一")


def test_manifest_behavior_pack():
    m = ToolPackManifest.parse(
        _manifest_text(
            kind="behavior-pack",
            behavior={"activity_delay": {"idle_probability": 0.2}},
        )
    )
    assert m.kind == "behavior-pack"
    assert m.behavior["activity_delay"]["idle_probability"] == 0.2


def test_manifest_rejects_bad_kind():
    with pytest.raises(ValueError):
        ToolPackManifest.parse(_manifest_text(kind="plugin"))


def test_registry_register_schemas_execute():
    r = registry.ToolRegistry()
    r.register(ToolSpec(name="ping", description="ping", parameters={}, permissions=[], handler=lambda ctx, args: "pong"))
    assert r.schemas()[0]["function"]["name"] == "ping"
    assert r.execute("ping", {}, ToolContext(permissions=set())) == "pong"


def test_registry_permission_denied():
    r = registry.ToolRegistry()
    r.register(ToolSpec(name="ban", description="禁言", parameters={}, permissions=["group_admin"], handler=lambda ctx, args: "ok"))
    with pytest.raises(ToolPermissionError):
        r.execute("ban", {}, ToolContext(permissions=set()))


def test_registry_load_pack_and_unload(tmp_path):
    pack = tmp_path / "demo-pack"
    (pack / "tools").mkdir(parents=True)
    (pack / "manifest.json").write_text(_manifest_text(), encoding="utf-8")
    (pack / "tools" / "get_time.py").write_text(
        "def handle(ctx, args):\n    return '2026-08-21'\n",
        encoding="utf-8",
    )
    r = registry.ToolRegistry()
    assert r.load_pack(pack) == 1
    assert r.execute("get_time", {}, ToolContext(permissions={"timer"})) == "2026-08-21"
    assert r.unload_pack("demo-pack") == 1
    assert r.schemas() == []


def test_registry_load_behavior_pack_and_unload(tmp_path):
    pack = tmp_path / "reply-rhythm"
    pack.mkdir(parents=True)
    behavior = {
        "activity_delay": {
            "busy_long_probability": 0.35,
            "busy_long_seconds": [180, 900],
        }
    }
    (pack / "manifest.json").write_text(
        _manifest_text(kind="behavior-pack", behavior=behavior, tools=[]),
        encoding="utf-8",
    )
    r = registry.ToolRegistry()
    assert r.load_pack(pack) == 1
    assert r.behavior("demo-pack") == behavior
    assert r.unload_pack("demo-pack") == 1
    assert r.behavior("demo-pack") is None


def test_persona_pack_bundled_behavior(tmp_path):
    pack = tmp_path / "demo-persona"
    bundled = pack / "bundled" / "reply-rhythm"
    bundled.mkdir(parents=True)
    behavior = {"activity_delay": {"idle_probability": 0.1}}
    (pack / "manifest.json").write_text(
        json.dumps(
            {
                "id": "demo-persona",
                "name": "演示人设包",
                "version": "1.0.0",
                "kind": "persona-pack",
                "description": "测试",
                "adapters": ["qq_official"],
                "min_version": "0.4.0",
                "permissions": [],
                "bundled_packs": ["reply-rhythm"],
                "persona": "你是测试人格",
                "tools": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (bundled / "manifest.json").write_text(
        json.dumps(
            {
                "id": "reply-rhythm",
                "name": "回复节奏能力包",
                "version": "1.0.0",
                "kind": "behavior-pack",
                "description": "测试",
                "adapters": ["qq_official"],
                "min_version": "0.4.0",
                "permissions": [],
                "behavior": behavior,
                "tools": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    r = registry.ToolRegistry()
    assert r.load_pack(pack) == 1
    assert r.behavior("reply-rhythm") == behavior
    # 卸载人设包时捆绑行为一并移除
    assert r.unload_pack("demo-persona") == 1
    assert r.behavior("reply-rhythm") is None


def test_runtime_builtin_time():
    rt = get_runtime()
    names = {s["function"]["name"] for s in rt.schemas()}
    assert "get_current_time" in names
    assert rt.execute("get_current_time", {}, ToolContext(permissions=set()))


def test_official_packs_load_and_execute():
    if not (PACKS_DIR / "group-manager" / "manifest.json").exists():
        pytest.skip("官方能力包不在当前源码树里")
    r = registry.ToolRegistry()
    total = 0
    for pack in sorted(PACKS_DIR.iterdir()):
        if (pack / "manifest.json").exists():
            total += r.load_pack(pack)
    assert total >= 9
    sent = []
    ctx = ToolContext(
        store=_FakeStore(),
        send=lambda action, params: sent.append((action, params)),
        permissions={"group_admin", "send_message", "timer", "memory", "network"},
    )
    out = json.loads(r.execute(
        "mute_user", {"group_id": "1", "user_id": "2", "minutes": 5}, ctx
    ))
    assert out["ok"] is True and out["action"] == "mute_user"
    out = json.loads(r.execute(
        "mute_all", {"group_id": "1", "minutes": 60}, ctx
    ))
    assert out["ok"] is True and out["action"] == "mute_all"
    # 防御性上限：传超大分钟数会被钳到 30 天
    out = json.loads(r.execute(
        "mute_user", {"group_id": "1", "user_id": "2", "minutes": 999999}, ctx
    ))
    assert out["minutes"] == 43200
    out = json.loads(r.execute("set_reminder", {"minutes": 5, "text": "开会"}, ctx))
    assert out["ok"] is True and out["minutes"] == 5
    out = json.loads(r.execute("remember", {"fact": "喜欢猫"}, ctx))
    assert out["ok"] is True and out["stored"] is True
    out = json.loads(r.execute("product_faq", {"question": "怎么购买"}, ctx))
    # 插件已全部免费（开源）：不再引导去爱发电付款
    assert out["ok"] is True and "插件市场" in out["answer"]
    out = json.loads(r.execute("product_faq", {"question": "价格是多少"}, ctx))
    assert out["ok"] is True and "免费" in out["answer"]
    out = json.loads(r.execute("fetch_memory", {"user": "u"}, ctx))
    assert out["ok"] is True
    assert r.execute("get_activity_suggestion", {}, ctx)
    # 联网搜索能力包：真实执行一次，成功返回结果、失败也返回可读文本
    search_result = r.execute("web_search", {"query": "AstrBot"}, ctx)
    assert search_result and not search_result.startswith("Traceback")
    # 官方行为包：李清菡人设包捆绑回复节奏
    assert r.behavior("reply-rhythm") is not None
    assert r.behavior("reply-rhythm")["activity_delay"]["busy_long_seconds"] == [180, 900]
    assert sent and sent[0][0] == "mute_user"


def test_web_search_empty_query():
    if not (PACKS_DIR / "web-search" / "manifest.json").exists():
        pytest.skip("付费能力包不在当前源码树里（不随公开仓库分发）")
    r = registry.ToolRegistry()
    total = 0
    for pack in sorted(PACKS_DIR.iterdir()):
        if (pack / "manifest.json").exists() and pack.name == "web-search":
            total += r.load_pack(pack)
    assert total == 1
    out = json.loads(r.execute(
        "web_search", {}, ToolContext(permissions={"network"})
    ))
    assert out == {"ok": False, "error": "empty_query"}
