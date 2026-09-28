import os
from pathlib import Path

from astroswarm_linux import platform_info


def test_machine_id_reads_etc(tmp_path, monkeypatch):
    src = tmp_path / "machine-id"
    src.write_text("abc123\n", encoding="utf-8")
    monkeypatch.setattr(platform_info, "MACHINE_ID_PATHS", [str(src)])
    assert platform_info.machine_id() == "abc123"


def test_machine_id_fallback_hostname(monkeypatch):
    monkeypatch.setattr(platform_info, "MACHINE_ID_PATHS", [])
    monkeypatch.setattr(
        platform_info,
        "socket",
        type("S", (), {"gethostname": staticmethod(lambda: "myhost")})(),
    )
    assert platform_info.machine_id() == "myhost"


def test_xdg_homes(monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", "/tmp/d")
    monkeypatch.setenv("XDG_CONFIG_HOME", "/tmp/c")
    assert platform_info.data_home() == Path("/tmp/d") / "astroswarm"
    assert platform_info.config_home() == Path("/tmp/c") / "astroswarm"
