# -*- coding: utf-8 -*-
"""离线载荷分支的单元测试。

全部用临时目录造数据，不依赖真实的 D:\\ai\\QBotManager\\offline（构建机上有没有都不影响）。
"""
import tarfile
from pathlib import Path

from qbotmanager.core import dsh
from qbotmanager.core import offline_bundle as ob
from qbotmanager.core import python_runtime as pr
from qbotmanager.core.settings import Settings


def _mk_offline(tmp_path: Path) -> Path:
    d = tmp_path / "offline"
    (d / "wheels").mkdir(parents=True)
    (d / "dsh").mkdir(parents=True)
    (d / "python-3.12.10-embed-amd64.zip").write_bytes(b"PK\x05\x06" + b"\x00" * 18)
    (d / "node-v22.23.2-win-x64.zip").write_bytes(b"PK\x05\x06" + b"\x00" * 18)
    (d / "wheels" / "pip-24.0-py3-none-any.whl").write_bytes(b"")
    (d / "wheels" / "setuptools-70.0-py3-none-any.whl").write_bytes(b"")
    return d


def _use(tmp_path, monkeypatch) -> Path:
    d = _mk_offline(tmp_path)
    monkeypatch.setenv("QBM_OFFLINE_DIR", str(d))
    return d


def test_offline_dir_and_probes(tmp_path, monkeypatch):
    d = _use(tmp_path, monkeypatch)
    assert ob.offline_dir() == d
    assert ob.python_zip().name.startswith("python-3.12.10-embed")
    assert ob.node_zip().name.startswith("node-v22.23.2")
    assert ob.wheels_dir() == d / "wheels"


def test_missing_pieces_return_none(tmp_path, monkeypatch):
    empty = tmp_path / "empty_offline"
    empty.mkdir()
    monkeypatch.setenv("QBM_OFFLINE_DIR", str(empty))
    assert ob.wheels_dir() is None
    assert ob.dsh_payload() is None


def test_install_packages_prefers_offline_wheels(tmp_path, monkeypatch):
    d = _use(tmp_path, monkeypatch)
    s = Settings(tmp_path / "root")
    s.ensure_dirs()
    seen = {}

    monkeypatch.setattr(pr, "ensure_runtime", lambda settings, log=None, cancel_event=None: Path("python.exe"))

    def fake_run_stream(cmd, timeout=0, on_line=None, cancel_event=None):
        seen["cmd"] = cmd
        return 0, "Successfully installed"

    monkeypatch.setattr(pr, "run_stream", fake_run_stream)
    pr.install_with_fallback(s, ["nonebot2[fastapi]"])
    cmd = seen["cmd"]
    assert "--no-index" in cmd and "--find-links" in cmd
    assert str(d / "wheels") in cmd


def test_install_packages_falls_back_to_online(tmp_path, monkeypatch):
    _use(tmp_path, monkeypatch)
    s = Settings(tmp_path / "root")
    s.ensure_dirs()
    calls = []

    monkeypatch.setattr(pr, "ensure_runtime", lambda settings, log=None, cancel_event=None: Path("python.exe"))

    def fake_run_stream(cmd, timeout=0, on_line=None, cancel_event=None):
        calls.append(cmd)
        if "--no-index" in cmd:
            return 1, "ERROR: no matching distribution"
        return 0, "ok"

    monkeypatch.setattr(pr, "run_stream", fake_run_stream)
    pr.install_with_fallback(s, ["nonebot2[fastapi]"])
    assert len(calls) >= 2
    assert "--no-index" in calls[0]
    assert "--no-index" not in calls[1]


def _mk_payload(path: Path) -> Path:
    src = path / "stage"
    (src / "node_modules").mkdir(parents=True)
    (src / "node_modules" / ".keep").write_text("x", encoding="utf-8")
    (src / "package.json").write_text('{"name":"x"}', encoding="utf-8")
    # 真实载荷里带 dsh 本体：安装判定需要 node_modules/@deepseek-ai/dsh/lib/bin.js
    binjs = src / "node_modules" / "@deepseek-ai" / "dsh" / "lib" / "bin.js"
    binjs.parent.mkdir(parents=True, exist_ok=True)
    binjs.write_text("// dsh entry\n", encoding="utf-8")
    prof = src / "home" / "profiles" / "qqbot"
    prof.mkdir(parents=True)
    (prof / "package.json").write_text('{"name":"p"}', encoding="utf-8")
    out = path / "payload.tar.gz"
    with tarfile.open(out, "w:gz") as tf:
        for p in src.rglob("*"):
            if p.is_file():
                tf.add(str(p), arcname=p.relative_to(src).as_posix())
    return out


def test_dsh_install_from_payload_skips_npm(tmp_path, monkeypatch):
    d = _mk_offline(tmp_path)
    _mk_payload(d / "dsh")
    monkeypatch.setenv("QBM_OFFLINE_DIR", str(d))
    s = Settings(tmp_path / "root")
    s.ensure_dirs()
    s.dsh_node_exe = str(tmp_path / "node.exe")
    (tmp_path / "node.exe").write_bytes(b"")
    monkeypatch.setattr(dsh, "_ensure_node", lambda *a, **k: tmp_path / "node.exe")

    def boom(*a, **k):
        raise AssertionError("离线安装不应调用 npm / plugin add")

    monkeypatch.setattr(dsh, "run_stream", boom)
    monkeypatch.setattr(dsh, "run_capture", boom)

    dsh.install(s)
    assert dsh.is_installed(s) is True
    assert dsh.bridge_marker(s).read_text(encoding="utf-8").strip() == dsh.BRIDGE_VERSION
