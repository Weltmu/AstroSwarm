# -*- coding: utf-8 -*-
"""本地人设工坊测试：模板、JSON/zip 导入、启用/停用/卸载、运行时环境变量。"""
import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
if not os.environ.get("QBM_POINTER_DIR"):
    os.environ["QBM_POINTER_DIR"] = str(Path(tempfile.mkdtemp(prefix="qbm_test_ptr_")))

from qbotmanager.core import persona_workshop  # noqa: E402
from qbotmanager.core.settings import Settings  # noqa: E402


def _card(pid="com.demo.rose", name="玫瑰"):
    return {
        "format": "astroswarm-persona",
        "version": "1.0",
        "id": pid,
        "name": name,
        "summary": "测试人设",
        "kind": "persona-pack",
        "description": "测试",
        "adapters": ["qq_official"],
        "min_version": "0.4.0",
        "permissions": [],
        "tools": [],
        "identity": {"name": name, "worldview": "测试世界"},
        "personality": {"traits": ["冷静"], "tone": "简洁"},
        "speech": {"self_ref": "我"},
        "directives": ["保护用户"],
        "boundaries": ["不聊违法内容"],
        "system_prompt": "",
    }


def test_template_valid_and_importable():
    text = persona_workshop.template_text()
    data = json.loads(text)
    assert data["format"] == "astroswarm-persona"
    from qbotmanager.core.agent.tool import (
        ToolPackManifest, compile_persona, validate_persona_card,
    )
    assert validate_persona_card(data) is None
    m = ToolPackManifest.parse(data)
    assert m.identity["name"] == "角色名"
    assert compile_persona(data)  # 注释字段不影响编译
    guide = persona_workshop.guide_text()
    assert "两种写法" in guide and "完整示例" in guide
    print("OK persona template")


def test_install_json_and_list():
    tmp = Path(tempfile.mkdtemp(prefix="qbm_pw_json_"))
    s = Settings(tmp)
    s.ensure_dirs()
    card = _card()
    src = tmp / "rose.json"
    src.write_text(json.dumps(card, ensure_ascii=False), encoding="utf-8")
    res = persona_workshop.install_persona(s, src)
    assert res["ok"] and res["id"] == "com.demo.rose"
    items = persona_workshop.list_personas(s)
    assert len(items) == 1 and items[0]["name"] == "玫瑰"
    assert items[0]["active"] is False
    assert (persona_workshop.personas_dir(s) / "com.demo.rose"
            / "manifest.json").exists()
    print("OK persona install_json")


def test_install_zip_with_tools():
    tmp = Path(tempfile.mkdtemp(prefix="qbm_pw_zip_"))
    s = Settings(tmp)
    s.ensure_dirs()
    card = _card(pid="com.demo.sage", name="贤者")
    card["tools"] = [{
        "name": "hello",
        "description": "打招呼",
        "parameters": {"type": "object", "properties": {}, "required": []},
        "permissions": [],
    }]
    zpath = tmp / "sage.zip"
    with zipfile.ZipFile(zpath, "w") as z:
        z.writestr("sage/manifest.json", json.dumps(card, ensure_ascii=False))
        z.writestr("sage/tools/hello.py",
                   "def handle(ctx, args):\n    return 'hi'\n")
    res = persona_workshop.install_persona(s, zpath)
    assert res["ok"] and res["tools"] == ["hello"]
    items = persona_workshop.list_personas(s)
    assert items[0]["tools"] == ["hello"]
    assert (persona_workshop.personas_dir(s) / "com.demo.sage"
            / "tools" / "hello.py").exists()
    print("OK persona install_zip_tools")


def test_install_rejects_invalid():
    tmp = Path(tempfile.mkdtemp(prefix="qbm_pw_bad_"))
    s = Settings(tmp)
    s.ensure_dirs()
    bad = tmp / "bad.json"
    bad.write_text(json.dumps({"id": "x", "kind": "tool-pack"}), encoding="utf-8")
    try:
        persona_workshop.install_persona(s, bad)
        raise AssertionError("非法人设应被拒绝")
    except RuntimeError:
        pass
    assert persona_workshop.list_personas(s) == []
    print("OK persona reject_invalid")


def test_activate_deactivate_uninstall_and_env():
    tmp = Path(tempfile.mkdtemp(prefix="qbm_pw_act_"))
    s = Settings(tmp)
    s.ensure_dirs()
    captured = {}
    from qbotmanager.core import ai_config
    orig = ai_config.save_personality
    ai_config.save_personality = lambda settings, text: (
        captured.update(text=str(text)) or True)
    try:
        src = tmp / "rose.json"
        src.write_text(json.dumps(_card(), ensure_ascii=False), encoding="utf-8")
        persona_workshop.install_persona(s, src)
        res = persona_workshop.activate_persona(s, "com.demo.rose")
        assert res["ok"] and s.local_persona_id == "com.demo.rose"
        assert s.agent_profile_enabled is False, "启用本地人设应关闭硬编码档案"
        assert "玫瑰" in captured.get("text", "")
        assert captured["text"].rstrip().endswith("不聊违法内容")
        env = persona_workshop.pack_env(s)
        assert env["ASTROSWARM_PERSONAS_ALLOWED"] == "com.demo.rose"
        assert env["ASTROSWARM_PERSONAS"].endswith("personas")
        assert persona_workshop.list_personas(s)[0]["active"] is True

        persona_workshop.deactivate_persona(s)
        assert s.local_persona_id == ""
        assert persona_workshop.pack_env(s)["ASTROSWARM_PERSONAS_ALLOWED"] == ""

        persona_workshop.uninstall_persona(s, "com.demo.rose")
        assert persona_workshop.list_personas(s) == []
        assert not (persona_workshop.personas_dir(s) / "com.demo.rose").exists()
    finally:
        ai_config.save_personality = orig
    print("OK persona activate_deactivate_uninstall")


def test_rejects_path_traversal_id():
    """人设 id 直接当目录名用：`../x` 这种必须被共用层挡掉（桌面端/无头端都靠它）。"""
    tmp = Path(tempfile.mkdtemp(prefix="qbm_pw_trav_"))
    s = Settings(tmp)
    s.ensure_dirs()
    outside = tmp / "evil"
    outside.mkdir(parents=True, exist_ok=True)
    (outside / "keep.txt").write_text("关键数据", encoding="utf-8")

    bad = tmp / "bad.json"
    bad.write_text(json.dumps(_card(pid="../evil"), ensure_ascii=False),
                   encoding="utf-8")
    try:
        persona_workshop.install_persona(s, bad)
        raise AssertionError("JSON 里的路径穿越 id 必须被拒绝")
    except RuntimeError as e:
        assert "id" in str(e)

    zpath = tmp / "bad.zip"
    with zipfile.ZipFile(zpath, "w") as z:
        z.writestr("manifest.json",
                   json.dumps(_card(pid="../../evil2"), ensure_ascii=False))
    try:
        persona_workshop.install_persona(s, zpath)
        raise AssertionError("zip 里的路径穿越 id 必须被拒绝")
    except RuntimeError:
        pass

    for call in (lambda: persona_workshop.uninstall_persona(s, "../evil"),
                 lambda: persona_workshop.activate_persona(s, "../evil")):
        try:
            call()
            raise AssertionError("非法 id 必须被拒绝")
        except RuntimeError:
            pass

    assert (outside / "keep.txt").read_text(encoding="utf-8") == "关键数据"
    assert persona_workshop.list_personas(s) == []
    print("OK persona reject_path_traversal")


if __name__ == "__main__":
    test_template_valid_and_importable()
    test_install_json_and_list()
    test_install_zip_with_tools()
    test_install_rejects_invalid()
    test_rejects_path_traversal_id()
    test_activate_deactivate_uninstall_and_env()
