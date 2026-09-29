import sys

from astroswarm_linux import runtime


def test_find_python3(monkeypatch):
    monkeypatch.setattr(
        runtime.shutil,
        "which",
        lambda name: "/usr/bin/python3" if name == "python3" else None,
    )
    assert runtime.find_python3() == "/usr/bin/python3"


def test_ensure_venv_creates_python(tmp_path):
    py = runtime.find_python3()
    venv_dir = tmp_path / "venv"
    result = runtime.ensure_venv(py, venv_dir, lambda m: None)
    expected = (
        venv_dir / "bin" / "python"
        if sys.platform != "win32"
        else venv_dir / "Scripts" / "python.exe"
    )
    assert result == expected and result.exists()
