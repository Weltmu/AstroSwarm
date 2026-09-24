"""工具包管理：安装/卸载/列表（含授权校验）。"""
import json
import logging
import shutil
import zipfile
from pathlib import Path

from qbotmanager.core.plugin_market import download_plugin

from . import auth, deploy, headless_config, platform_info

logger = logging.getLogger(__name__)


def packs_dir() -> Path:
    return platform_info.data_home() / "tool_packs"


def installed() -> list:
    out = []
    root = packs_dir()
    if root.exists():
        for pack in sorted(root.iterdir()):
            manifest = pack / "manifest.json"
            if not manifest.exists():
                for sub in pack.iterdir():
                    if sub.is_dir() and (sub / "manifest.json").exists():
                        manifest = sub / "manifest.json"
                        break
            if manifest.exists():
                try:
                    m = json.loads(manifest.read_text(encoding="utf-8"))
                    out.append(
                        {
                            "id": m.get("id"),
                            "name": m.get("name"),
                            "version": m.get("version"),
                            "kind": m.get("kind"),
                            "permissions": m.get("permissions") or [],
                            "tools": [t.get("name") for t in (m.get("tools") or [])],
                            "persona": m.get("persona") or "",
                            "frozen": not _entitled(m.get("id") or ""),
                        }
                    )
                except Exception:  # noqa: BLE001
                    continue
    return out


def _entitled(plugin_id: str) -> bool:
    """能不能装/加载该能力包。

    2026-09 起插件全部免费（随主仓库开源）：不再看账号签名、档位或单独购买，
    恒为 True。函数名保留是为了兼容旧调用方（deploy._allowed_packs 等）。
    """
    return True


def install(entry: dict) -> dict:
    pid = str(entry.get("id") or "")
    if not pid:
        raise ValueError("缺少插件 id")
    ver = str(entry.get("version") or "1.0.0")
    dest = packs_dir() / f"{pid}-{ver}.zip"
    download_plugin(str(entry.get("url")), dest, entry.get("sha256"))
    target = packs_dir() / pid
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    with zipfile.ZipFile(dest) as archive:
        for name in archive.namelist():
            if name.startswith("/") or ".." in name.split("/"):
                raise ValueError("工具包包含非法路径")
        archive.extractall(target)
    if not (target / "manifest.json").exists():
        for sub in target.iterdir():
            if sub.is_dir() and (sub / "manifest.json").exists():
                for f in list(sub.rglob("*")):
                    rel = f.relative_to(sub)
                    if f.is_dir():
                        (target / rel).mkdir(parents=True, exist_ok=True)
                    else:
                        (target / rel).parent.mkdir(parents=True, exist_ok=True)
                        f.replace(target / rel)
                shutil.rmtree(sub)
                break
    try:
        manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
        if manifest.get("kind") == "persona-pack":
            from qbotmanager.core import ai_config
            from qbotmanager.core.agent.tool import compile_persona

            persona_text = compile_persona(manifest)
            if persona_text:
                ai_config.save_personality(deploy.build_settings(), persona_text)
    except Exception as e:  # noqa: BLE001
        # 人设包装失败不能 except: pass：包上去了人设没生效，用户只会觉得"机器人变笨了"
        logger.warning("人设包 %s 安装后应用人设失败（包已装，人设未生效）: %s", pid, e)
    dest.unlink(missing_ok=True)
    return {"ok": True, "id": pid}


def uninstall(pack_id: str) -> dict:
    target = packs_dir() / pack_id
    if target.exists():
        shutil.rmtree(target)
    return {"ok": True, "id": pack_id}
