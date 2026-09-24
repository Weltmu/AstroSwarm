"""systemd 自启：生成 unit 文本并安装。"""
import os
from pathlib import Path


def unit_text(root: Path, port: int) -> str:
    root = Path(root)
    user = os.environ.get("USER") or os.environ.get("USERNAME") or "root"
    return f"""[Unit]
Description=AstroSwarm Headless
After=network.target

[Service]
Type=simple
User={user}
WorkingDirectory={root}
ExecStart={root / "bin" / "astroswarm"} serve --host 127.0.0.1 --port {port}
Restart=on-failure
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
"""


def install(
    unit_name: str,
    text: str,
    systemd_dir: Path,
    wants_dir: Path | None = None,
    enable: bool = True,
) -> None:
    systemd_dir = Path(systemd_dir)
    systemd_dir.mkdir(parents=True, exist_ok=True)
    unit_path = systemd_dir / unit_name
    unit_path.write_text(text, encoding="utf-8")
    if not enable:
        return
    if wants_dir is None:
        wants_dir = systemd_dir.parent / "multi-user.target.wants"
    wants_dir = Path(wants_dir)
    wants_dir.mkdir(parents=True, exist_ok=True)
    link = wants_dir / unit_name
    if link.exists() or link.is_symlink():
        link.unlink()
    try:
        link.symlink_to(unit_path)
    except OSError:
        # 不支持符号链接的环境（如 Windows 测试）退化为复制
        link.write_text(text, encoding="utf-8")
