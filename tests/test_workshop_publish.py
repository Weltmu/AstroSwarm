# -*- coding: utf-8 -*-
"""工坊分享与投稿：导出 / 导入 / 运行期报错自修复（M3 + M5）。"""
import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
if not os.environ.get("QBM_POINTER_DIR"):
    os.environ["QBM_POINTER_DIR"] = str(tempfile.mkdtemp(prefix="qbm_ws_pub_ptr_"))

from qbotmanager.core import workshop                       # noqa: E402
from qbotmanager.core.settings import Settings              # noqa: E402
from qbotmanager.core.workshop import (                     # noqa: E402
    generator,
    installer,
    publisher,
    repair,
    validator,
)

TOOL = '''
import json


def handle(ctx, args):
    city = str(args.get("city") or "").strip()
    if not city:
        return json.dumps({"ok": False, "error": "missing_city"}, ensure_ascii=False)
    return json.dumps({"ok": True, "city": city}, ensure_ascii=False)
'''

FIXED_TOOL = '''
import json


def handle(ctx, args):
    return json.dumps({"ok": True, "fixed": True}, ensure_ascii=False)
'''


def _settings(tmp: Path):
    s = Settings(tmp)
    s.ensure_dirs()
    return s


def _files(pid="weather_demo", tool="check_weather", code=TOOL):
    manifest = {
        "id": pid, "name": "查天气", "version": "1.0.0", "kind": "tool-pack",
        "description": "查天气的插件", "adapters": ["qq_official"],
        "permissions": [], "sandbox": True,
        "tools": [{
            "name": tool,
            "description": "用户问天气的时候用",
            "parameters": {"type": "object",
                           "properties": {"city": {"type": "string", "description": "城市"}},
                           "required": ["city"]},
            "permissions": [], "lifecycle": "none",
        }],
    }
    return {"manifest.json": json.dumps(manifest, ensure_ascii=False, indent=2),
            "tools/%s.py" % tool: code}


def _install(s, pid="weather_demo", tool="check_weather", code=TOOL):
    return installer.install(s, pid, _files(pid, tool, code), {
        "name": "查天气", "source": "workshop", "need": "查天气",
        "plan": {"id": pid, "name": "查天气", "tools": [{"name": tool}]},
    })


def _zip(tmp: Path, files: dict, name="pack.zip") -> Path:
    path = tmp / name
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel, content in files.items():
            zf.writestr(rel, content)
    return path


# ---- 导出 / 导入 ----


def test_export_zip_contains_manifest_and_tools(tmp_path):
    s = _settings(tmp_path)
    _install(s)
    out = publisher.export_zip(s, "weather_demo")
    assert out["ok"] and Path(out["path"]).is_file()
    with zipfile.ZipFile(out["path"]) as zf:
        names = set(zf.namelist())
    assert "manifest.json" in names and "tools/check_weather.py" in names


def test_export_missing_pack_raises(tmp_path):
    s = _settings(tmp_path)
    with pytest.raises(publisher.PublishError):
        publisher.export_zip(s, "not_there")


def test_import_zip_installs_valid_pack(tmp_path):
    src = _settings(tmp_path / "a")
    _install(src)
    packed = publisher.export_zip(src, "weather_demo")
    dst = _settings(tmp_path / "b")
    res = publisher.import_zip(dst, packed["path"])
    assert res["ok"] and res["id"] == "weather_demo"
    assert (Path(dst.root) / "tool_packs" / "weather_demo" / "manifest.json").is_file()


def test_import_zip_rejects_path_traversal(tmp_path):
    s = _settings(tmp_path)
    bad = _zip(tmp_path, {"../evil.py": "x = 1",
                          "manifest.json": json.dumps({"id": "evil", "tools": []})})
    with pytest.raises(publisher.PublishError):
        publisher.import_zip(s, bad)


def test_import_zip_rejects_unsafe_code(tmp_path):
    s = _settings(tmp_path)
    bad_code = "import requests\n\n\ndef handle(ctx, args):\n    return '{}'\n"
    bad = _zip(tmp_path, _files(code=bad_code), "bad.zip")
    with pytest.raises(publisher.PublishError):
        publisher.import_zip(s, bad)
    assert not (Path(s.root) / "tool_packs" / "weather_demo").exists()


def test_import_same_pack_twice_is_allowed(tmp_path):
    """第二次导入 = 升级：工具名不该跟自己撞名。"""
    s = _settings(tmp_path)
    _install(s)
    packed = publisher.export_zip(s, "weather_demo")
    res = publisher.import_zip(s, packed["path"])
    assert res["ok"]


# ---- 运行期报错 ----


def test_runtime_error_record_and_pending(tmp_path):
    s = _settings(tmp_path)
    _install(s)
    repair.record(s, "weather_demo", "check_weather", "TypeError: boom")
    rows = repair.pending(s)
    assert rows and rows[0]["id"] == "weather_demo" and rows[0]["count"] == 1
    assert "boom" in rows[0]["error"]
    repair.mark_fixed(s, "weather_demo")
    assert repair.pending(s) == []


def test_record_for_pack_ignores_non_workshop(tmp_path):
    """官方包 / 手动拷进去的包没有工坊元信息，不该记（记了也没法让 AI 修）。"""
    s = _settings(tmp_path)
    pack_dir = Path(s.root) / "tool_packs" / "official_pack"
    (pack_dir / "tools").mkdir(parents=True)
    (pack_dir / "manifest.json").write_text(
        json.dumps({"id": "official_pack", "tools": [{"name": "check_weather"}]},
                   ensure_ascii=False), encoding="utf-8")
    assert repair.record_for_pack(pack_dir, "check_weather", "boom") is False
    assert repair.pending(s) == []


def test_record_for_pack_ignores_imported_pack(tmp_path):
    """别人给的插件包（source=imported）也不进自修复回路。"""
    s = _settings(tmp_path)
    installer.install(s, "imported_pack", _files("imported_pack"),
                      {"name": "导入的", "source": "imported"})
    pack_dir = Path(s.root) / "tool_packs" / "imported_pack"
    assert repair.record_for_pack(pack_dir, "check_weather", "boom") is False
    assert repair.pending(s) == []


def test_record_for_pack_records_workshop_pack(tmp_path):
    s = _settings(tmp_path)
    _install(s)
    pack_dir = Path(s.root) / "tool_packs" / "weather_demo"
    assert repair.record_for_pack(pack_dir, "check_weather", "RuntimeError: boom") is True
    assert repair.pending(s)[0]["tool"] == "check_weather"


def test_fix_from_errors_keeps_id_and_passes_checks(tmp_path, monkeypatch):
    s = _settings(tmp_path)
    _install(s)
    repair.record(s, "weather_demo", "check_weather", "TypeError: boom")

    def fake_model(settings, system, user, timeout=240):
        return json.dumps({
            "manifest": {
                "id": "renamed_by_model", "name": "查天气", "version": "1.0.1",
                "kind": "tool-pack", "description": "查天气的插件",
                "adapters": ["qq_official"], "permissions": [], "sandbox": True,
                "tools": [{
                    "name": "check_weather",
                    "description": "用户问天气的时候用",
                    "parameters": {"type": "object",
                                   "properties": {"city": {"type": "string",
                                                           "description": "城市"}},
                                   "required": ["city"]},
                    "permissions": [], "lifecycle": "none",
                }],
            },
            "tools": {"check_weather": FIXED_TOOL},
            "notes": "",
        }, ensure_ascii=False)

    monkeypatch.setattr(generator, "call_model", fake_model)
    out = repair.fix(s, "weather_demo")
    assert out["ok"] is True, out.get("issues")
    assert json.loads(out["files"]["manifest.json"])["id"] == "weather_demo"
    assert validator.errors(out["issues"]) == []


def test_fix_without_errors_raises(tmp_path):
    s = _settings(tmp_path)
    _install(s)
    with pytest.raises(repair.RepairError):
        repair.fix(s, "weather_demo")


# ---- 投稿状态文案 ----


def test_describe_renders_status_lines():
    rows = publisher.describe([
        {"id": 1, "name": "查天气", "version": "1.0.0", "status": "pending",
         "created_at": 1700000000},
        {"id": 2, "name": "签到", "version": "2.0.0", "status": "rejected",
         "reason": "还有写死话术", "created_at": 1700000000},
        {"id": 3, "name": "点歌", "version": "1.2.0", "status": "approved",
         "final_id": "u-song", "created_at": 1700000000},
    ])
    assert "审核中" in rows[0]["text"]
    assert "被驳回" in rows[1]["text"] and "写死话术" in rows[1]["text"]
    assert "已上架" in rows[2]["text"] and "u-song" in rows[2]["text"]
