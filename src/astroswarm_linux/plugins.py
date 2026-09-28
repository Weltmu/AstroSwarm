"""消息插件安装管理（官方市场 zip → bot/src/plugins）。"""
import json
import shutil
import zipfile
from pathlib import Path

from qbotmanager.core import plugin_market

from . import deploy, platform_info


def bot_plugins_dir() -> Path:
    return deploy.build_settings().plugins_dir


def installed() -> list:
    out = []
    root = bot_plugins_dir()
    if root.exists():
        for pack in sorted(root.iterdir()):
            manifest = pack / "plugin.json"
            if manifest.exists():
                try:
                    m = json.loads(manifest.read_text(encoding="utf-8"))
                    out.append(
                        {
                            "id": m.get("id"),
                            "name": m.get("name"),
                            "version": m.get("version"),
                        }
                    )
                except Exception:  # noqa: BLE001
                    continue
    return out


def _normalize(target: Path) -> None:
    if (target / "plugin.json").exists():
        return
    for sub in target.iterdir():
        if sub.is_dir() and (sub / "plugin.json").exists():
            for f in list(sub.rglob("*")):
                rel = f.relative_to(sub)
                if f.is_dir():
                    (target / rel).mkdir(parents=True, exist_ok=True)
                else:
                    (target / rel).parent.mkdir(parents=True, exist_ok=True)
                    f.replace(target / rel)
            shutil.rmtree(sub)
            return
    raise ValueError("插件包缺少 plugin.json")


def install(entry: dict) -> dict:
    pid = str(entry.get("id") or "")
    ver = str(entry.get("version") or "1.0.0")
    dest = platform_info.data_home() / "downloads" / f"{pid}-{ver}.zip"
    dest.parent.mkdir(parents=True, exist_ok=True)
    plugin_market.download_plugin(str(entry.get("url")), dest, entry.get("sha256"))
    manifest = plugin_market.read_plugin_manifest(dest)
    err = plugin_market.validate_plugin_manifest(manifest)
    if err:
        raise ValueError(err)
    target = bot_plugins_dir() / pid
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    with zipfile.ZipFile(dest) as archive:
        for name in archive.namelist():
            if name.startswith("/") or ".." in name.split("/"):
                raise ValueError("插件包包含非法路径")
        archive.extractall(target)
    _normalize(target)
    dest.unlink(missing_ok=True)
    return {"ok": True, "id": pid}


def uninstall(plugin_id: str) -> dict:
    target = bot_plugins_dir() / plugin_id
    if target.exists():
        shutil.rmtree(target)
    return {"ok": True, "id": plugin_id}
