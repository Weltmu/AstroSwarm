"""Python 运行时探测与虚拟环境创建。"""
import shutil
import subprocess
import sys
from pathlib import Path


def find_python3() -> str:
    return shutil.which("python3") or sys.executable


def ensure_venv(python: str, venv_dir: Path, log) -> Path:
    venv_dir = Path(venv_dir)
    bin_py = (
        venv_dir / "bin" / "python"
        if sys.platform != "win32"
        else venv_dir / "Scripts" / "python.exe"
    )
    if bin_py.exists():
        return bin_py
    venv_dir.parent.mkdir(parents=True, exist_ok=True)
    log(f"creating venv at {venv_dir}")
    subprocess.run(
        [python, "-m", "venv", str(venv_dir)],
        check=True,
        capture_output=True,
    )
    return bin_py
