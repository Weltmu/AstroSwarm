# -*- coding: utf-8 -*-
"""第三方插件 zip 的安全边界：路径穿越 / 绝对路径 / 盘符 / 符号链接 / 成员数 / 解压后体积。

只看压缩包大小是不够的：0.19MB 的包实测能解出 200MB，所以必须限制解压后总量。
"""
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from qbotmanager.core import plugins as P  # noqa: E402
from qbotmanager.core.settings import Settings  # noqa: E402


def _settings() -> Settings:
    tmp = Path(tempfile.mkdtemp(prefix="qbm_zip_"))
    s = Settings(tmp)
    s.ensure_dirs()
    return s


def _zip(root: Path, entries, symlink=False) -> Path:
    path = root / "pack.zip"
    with zipfile.ZipFile(path, "w") as z:
        for name, data in entries:
            info = zipfile.ZipInfo(name)
            if symlink:
                info.external_attr = (0xA1FF << 16)      # 0xA000 = 符号链接
            z.writestr(info, data)
    return path


def test_normal_zip_extracts_to_top_dir():
    s = _settings()
    z = _zip(s.root, [("demo/manifest.json", "{}"), ("demo/tools/a.py", "x = 1")])
    out = P.extract_zip_plugin(s, z)
    assert out.is_dir() and out.name == "demo"
    assert (out / "tools" / "a.py").exists()


def test_zip_slip_rejected():
    s = _settings()
    for label, entries in {
        "上级目录": [("../evil.py", "x")],
        "绝对路径": [("/etc/passwd", "x")],
        "Windows 盘符": [("C:/Windows/x.py", "x")],
        "深层穿越": [("demo/../../evil.py", "x")],
    }.items():
        z = _zip(s.root, entries)
        try:
            P.extract_zip_plugin(s, z)
        except RuntimeError as exc:
            assert "非法路径" in str(exc), (label, exc)
        else:
            raise AssertionError(f"{label} 没有被拒绝")
        assert not (s.root / "evil.py").exists(), label


def test_zip_symlink_rejected():
    s = _settings()
    z = _zip(s.root, [("demo/link", "/etc/passwd")], symlink=True)
    try:
        P.extract_zip_plugin(s, z)
    except RuntimeError as exc:
        assert "符号链接" in str(exc)
    else:
        raise AssertionError("符号链接 zip 没有被拒绝")


def test_zip_member_count_limited():
    s = _settings()
    z = _zip(s.root, [(f"demo/f{i}.py", "x") for i in range(P.ZIP_MAX_MEMBERS + 3)])
    try:
        P.extract_zip_plugin(s, z)
    except RuntimeError as exc:
        assert "成员太多" in str(exc)
    else:
        raise AssertionError("成员过多的 zip 没有被拒绝")


def test_zip_size_limited():
    s = _settings()
    z = _zip(s.root, [("demo/big.bin", "0" * (P.ZIP_MAX_SINGLE + 1024))])
    try:
        P.extract_zip_plugin(s, z)
    except RuntimeError as exc:
        assert "过大" in str(exc)
    else:
        raise AssertionError("超大 zip 没有被拒绝")


def test_empty_zip_rejected():
    s = _settings()
    z = _zip(s.root, [])
    try:
        P.extract_zip_plugin(s, z)
    except RuntimeError as exc:
        assert "空" in str(exc)
    else:
        raise AssertionError("空 zip 没有被拒绝")
