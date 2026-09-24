# -*- coding: utf-8 -*-
"""桌面端能力包测试：安装/卸载、权益拦截、人设包写入、启动环境变量。"""
import json
import os
import sys
import tempfile
import time
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
if not os.environ.get("QBM_POINTER_DIR"):
    os.environ["QBM_POINTER_DIR"] = str(Path(tempfile.mkdtemp(prefix="qbm_test_ptr_")))


def _trust_plan(lic_mod):
    """短接权益签名校验：这些用例只测档位/到期逻辑，签名本身另有专项测试

    （见 test_entitlement_signature_is_required）。
    """
    lic_mod.verify_entitlement = lambda *a, **k: True


def _make_manifest_pack(root: Path, pid: str, config: dict | None = None) -> Path:
    """造一个带参数 schema 的能力包目录，返回包目录。"""
    pack = root / pid
    pack.mkdir(parents=True, exist_ok=True)
    manifest = {
        "id": pid, "name": f"{pid} 包", "version": "1.0.0", "kind": "tool-pack",
        "description": "测试用", "tools": [{"name": "t", "description": "工具"}],
    }
    if config:
        manifest["config"] = config
    (pack / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return pack


def test_pack_detail_and_config_roundtrip():
    """能力包参数：schema 渲染 → 校验 → 落盘 → 重新读回（与无头端同一套规则）。"""
    from qbotmanager.core import tool_packs
    from qbotmanager.core.settings import Settings

    tmp = Path(tempfile.mkdtemp(prefix="qbm_detail_"))
    s = Settings(tmp)
    s.ensure_dirs()
    packs = tool_packs.packs_dir(s)
    packs.mkdir(parents=True, exist_ok=True)
    _make_manifest_pack(packs, "demo", {"fields": [
        {"key": "enable", "label": "开启", "type": "bool", "default": True},
        {"key": "interval", "label": "间隔", "type": "number",
         "default": 30, "min": 5, "max": 240},
        {"key": "mode", "label": "模式", "type": "enum",
         "default": "soft", "options": ["soft", "hard"]},
    ]})

    detail = tool_packs.pack_detail(s, "demo")
    assert detail["installed"] is True
    assert [f["key"] for f in detail["fields"]] == ["enable", "interval", "mode"]
    assert detail["values"] == {"enable": True, "interval": 30, "mode": "soft"}
    assert detail["features"], "详情页要有「功能」列表"

    res = tool_packs.save_pack_config(
        s, "demo", {"interval": 90, "mode": "hard", "enable": False})
    assert res["changed"] == {"interval": 90, "mode": "hard", "enable": False}
    saved = json.loads(
        tool_packs.pack_config_path(s, "demo").read_text(encoding="utf-8"))
    assert saved == {"interval": 90, "mode": "hard", "enable": False}
    assert tool_packs.pack_detail(s, "demo")["values"]["interval"] == 90

    # 越界 / 类型不对 / 不在 schema 里的键
    for bad in ({"interval": 999}, {"interval": "abc"}, {"mode": "x"}):
        try:
            tool_packs.save_pack_config(s, "demo", bad)
            raise AssertionError(f"{bad} 应该被拒绝")
        except ValueError:
            pass
    assert tool_packs.save_pack_config(s, "demo", {"不存在的键": 1})["changed"] == {}

    # 未安装的包不能改参数；包标识非法要挡住
    try:
        tool_packs.save_pack_config(s, "not-installed", {"a": 1})
        raise AssertionError("未安装的包不该允许改参数")
    except RuntimeError:
        pass
    for bad_id in ("../x", "a/b", ""):
        try:
            tool_packs.pack_detail(s, bad_id)
            raise AssertionError(f"{bad_id!r} 应该被拒绝")
        except ValueError:
            pass


def _make_pack(path, pid, kind="tool-pack", persona=None):
    manifest = {
        "id": pid,
        "name": pid,
        "version": "1.0.0",
        "kind": kind,
        "adapters": ["qq_official"],
        "permissions": [],
        "tools": [],
    }
    if kind == "persona-pack":
        manifest["persona"] = persona or "测试人格"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(f"{pid}/manifest.json", json.dumps(manifest, ensure_ascii=False))
        z.writestr(
            f"{pid}/tools/hello.py",
            "def handle(ctx, args):\n    return 'hi'\n",
        )


def test_install_uninstall_and_env():
    from qbotmanager.core import license as lic

    _trust_plan(lic)
    from qbotmanager.core import tool_packs
    from qbotmanager.core.settings import Settings

    tmp = Path(tempfile.mkdtemp(prefix="qbm_pack_"))
    s = Settings(tmp)
    s.ensure_dirs()
    orig = lic.license_file
    try:
        lic.license_file = lambda: tmp / "license.json"
        lic.save_license({"machine_id": "TEST", "key": "TR1-X"})
        z = tmp / "p.zip"
        _make_pack(z, "group-manager")
        entry = {
            "id": "group-manager", "version": "1.0.0", "tier": "member",
            "url": "http://x/p.zip", "sha256": "",
        }
        # 月费档不再解锁全部付费包：没单独买过就该被拒
        lic.save_plan("monthly", time.time() + 86400)
        with pytest.raises(PermissionError):
            tool_packs.install_pack(s, entry, zip_path=z)

        # 单独买断过（owned_plugins 里有它）→ 免费版也能装
        lic.save_plan("monthly", time.time() + 86400, ["group-manager"])
        res = tool_packs.install_pack(s, entry, zip_path=z)
        assert res["ok"] and res["kind"] == "tool-pack"
        assert (tool_packs.packs_dir(s) / "group-manager"
                / "manifest.json").exists()
        assert tool_packs.allowed_pack_ids(s) == ["group-manager"]
        env = tool_packs.pack_env(s)
        assert "group-manager" in env["ASTROSWARM_TOOL_PACKS_ALLOWED"]
        assert str(tool_packs.packs_dir(s)) == env["ASTROSWARM_TOOL_PACKS"]

        tool_packs.uninstall_pack(s, "group-manager")
        assert tool_packs.installed(s) == []
        assert tool_packs.allowed_pack_ids(s) == []
    finally:
        lic.license_file = orig
    print("OK pack install_uninstall_env")


def test_install_requires_member_or_owned():
    from qbotmanager.core import license as lic

    _trust_plan(lic)
    from qbotmanager.core import tool_packs
    from qbotmanager.core.settings import Settings

    tmp = Path(tempfile.mkdtemp(prefix="qbm_pack_perm_"))
    s = Settings(tmp)
    s.ensure_dirs()
    orig = lic.license_file
    try:
        lic.license_file = lambda: tmp / "license.json"
        lic.save_license({"machine_id": "TEST", "key": "TR1-X"})
        lic.save_plan("none", 0, [])
        z = tmp / "p.zip"
        _make_pack(z, "group-manager")
        entry = {
            "id": "group-manager", "version": "1.0.0", "tier": "member",
            "url": "http://x/p.zip", "sha256": "",
        }
        try:
            tool_packs.install_pack(s, entry, zip_path=z)
            raise AssertionError("免费用户不应能安装会员能力包")
        except PermissionError:
            pass
        assert tool_packs.installed(s) == []

        # 单独购买后免费版可装
        lic.save_plan("none", 0, ["group-manager"])
        res = tool_packs.install_pack(s, entry, zip_path=z)
        assert res["ok"] is True
        assert tool_packs.allowed_pack_ids(s) == ["group-manager"]
    finally:
        lic.license_file = orig
    print("OK pack permission_gate")


def test_persona_pack_writes_personality():
    from qbotmanager.core import ai_config
    from qbotmanager.core import license as lic

    _trust_plan(lic)
    from qbotmanager.core import tool_packs
    from qbotmanager.core.settings import Settings

    tmp = Path(tempfile.mkdtemp(prefix="qbm_pack_persona_"))
    s = Settings(tmp)
    s.ensure_dirs()
    orig = lic.license_file
    captured = {}
    orig_save = ai_config.save_personality
    ai_config.save_personality = lambda settings, text: (
        captured.update(text=str(text)) or True)
    try:
        lic.license_file = lambda: tmp / "license.json"
        lic.save_license({"machine_id": "TEST", "key": "TR1-X"})
        lic.save_plan("none", 0, [])
        z = tmp / "p.zip"
        _make_pack(z, "liqinghan", kind="persona-pack", persona="我是李清菡")
        entry = {
            "id": "liqinghan", "version": "1.0.0", "tier": "free",
            "url": "http://x/p.zip", "sha256": "",
        }
        res = tool_packs.install_pack(s, entry, zip_path=z)
        assert res["kind"] == "persona-pack"
        assert captured.get("text") == "我是李清菡"
    finally:
        lic.license_file = orig
        ai_config.save_personality = orig_save
    print("OK pack persona_personality")


def test_pack_env_reply_rhythm():
    from qbotmanager.core import license as lic

    _trust_plan(lic)
    from qbotmanager.core import tool_packs
    from qbotmanager.core.settings import Settings

    tmp = Path(tempfile.mkdtemp(prefix="qbm_pack_rhythm_"))
    s = Settings(tmp)
    s.ensure_dirs()
    root = tool_packs.packs_dir(s)
    (root / "reply-rhythm").mkdir(parents=True, exist_ok=True)
    (root / "reply-rhythm" / "behavior.json").write_text(
        '{"min": 1, "max": 5}', encoding="utf-8")
    env = tool_packs.pack_env(s)
    assert env["ASTROSWARM_REPLY_RHYTHM"].endswith(
        "reply-rhythm" + os.sep + "behavior.json")
    print("OK pack reply_rhythm_env")


def test_store_tools_return_structured_data():
    """能力包工具只返回结构化 JSON 数据，不写死中文回复话术。"""
    import importlib.util
    import json

    tools_root = (Path(__file__).resolve().parents[1]
                  / "src" / "qbotmanager" / "assets" / "tool_packs")

    def load(pack, name):
        path = tools_root / pack / "tools" / f"{name}.py"
        if not path.exists():
            pytest.skip(f"能力包 {pack} 不在当前源码树里（付费包不随公开仓库分发）")
        spec = importlib.util.spec_from_file_location(f"{pack}_{name}", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    class FakeCtx:
        def __init__(self, permissions=()):
            self._perms = set(permissions)
            self.store = None
            self.sent = []

        def can(self, perm):
            return perm in self._perms

        def send(self, *args, **kwargs):
            self.sent.append((args, kwargs))

    # 定时提醒：存储不可用也返回结构化错误，而不是"提醒存储不可用"
    mod = load("timer", "set_reminder")
    out = json.loads(mod.handle(FakeCtx(), {"minutes": 5, "text": "喝水"}))
    assert out == {"ok": False, "error": "store_unavailable"}, out

    # 群管理：权限不足是错误码；成功返回结构化结果
    mod = load("group-manager", "mute_user")
    out = json.loads(mod.handle(
        FakeCtx(), {"user_id": "1", "group_id": "2", "minutes": 5}))
    assert out == {"ok": False, "error": "permission_denied",
                   "permission": "group_admin"}, out
    ctx = FakeCtx(permissions=["group_admin"])
    out = json.loads(mod.handle(
        ctx, {"user_id": "1", "group_id": "2", "minutes": 5}))
    assert out["ok"] is True and out["action"] == "mute_user"
    assert out["minutes"] == 5 and out["user_id"] == "1"

    mod = load("group-manager", "recall_message")
    out = json.loads(mod.handle(
        FakeCtx(permissions=["group_admin"]), {"message_id": "m1"}))
    assert out["ok"] is True and out["message_id"] == "m1", out

    # 记忆：不可用返回错误码
    mod = load("memory", "remember")
    out = json.loads(mod.handle(FakeCtx(), {"fact": "x"}))
    assert out == {"ok": False, "error": "store_unavailable"}, out

    # 主动聊天：返回结构化建议种子
    mod = load("proactive", "get_activity_suggestion")
    out = json.loads(mod.handle(FakeCtx(), {}))
    assert out["ok"] is True and "suggestion" in out, out

    # 产品知识库：命中返回数据，未命中返回错误码（话术交给 agent）
    mod = load("knowledge", "product_faq")
    out = json.loads(mod.handle(FakeCtx(), {"question": "价格是多少"}))
    assert out["ok"] is True and out["matched"] == "价格", out
    out = json.loads(mod.handle(FakeCtx(), {"question": "完全无关的问题xyz"}))
    assert out == {"ok": False, "error": "no_answer"}, out

    # 联网搜索：空查询返回错误码
    mod = load("web-search", "web_search")
    out = json.loads(mod.handle(FakeCtx(), {"query": "  "}))
    assert out == {"ok": False, "error": "empty_query"}, out
    print("OK pack tools_structured_data")


if __name__ == "__main__":
    test_install_uninstall_and_env()
    test_install_requires_member_or_owned()
    test_persona_pack_writes_personality()
    test_pack_env_reply_rhythm()
    test_store_tools_return_structured_data()
