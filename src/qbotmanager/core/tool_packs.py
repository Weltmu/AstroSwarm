# -*- coding: utf-8 -*-
"""桌面端能力包管理：下载安装/卸载工具包、人设包、行为包。

与 Linux 无头版 tools.py 对齐：包安装到 <根>/tool_packs/<id>，
manifest.json 声明 kind（tool-pack / persona-pack / behavior-pack）；
机器人启动时由 bot.start_bot 注入 ASTROSWARM_TOOL_PACKS 等环境变量，
AgentRuntime 加载全部已装能力包（2026-09 起插件全部免费，不再按权益冻结）。
"""
import json
import shutil
import zipfile
from pathlib import Path

from . import ai_config
from .agent.tool import compile_persona
from . import license as lic_mod
from . import plugin_market

PACK_KINDS = ("tool-pack", "persona-pack", "behavior-pack")


def packs_dir(settings) -> Path:
    return Path(settings.root) / "tool_packs"


def _find_manifest(pack_dir: Path):
    """返回包目录下的 manifest.json（支持 zip 顶层目录容错）。"""
    m = pack_dir / "manifest.json"
    if m.exists():
        return m
    for sub in pack_dir.iterdir():
        if sub.is_dir() and (sub / "manifest.json").exists():
            return sub / "manifest.json"
    return None


# 2026-09 起：能力包随主仓库开源，插件商店一律免费 —— 不再有付费包，
# 也没有「会员到期冻结」。FREE_PACK_IDS 保留为「全部官方包 id」，是为了让
# 无头端 deploy._allowed_packs 等旧调用方直接沿用（语义 = 全部放行）。
FREE_PACK_IDS = {
    "eva", "liqinghan", "qweather",
    "proactive", "memory", "knowledge", "web-search",
    "timer", "group-manager", "reply-rhythm",
}
# 已无付费包；保留这个空集合，给外部脚本/旧代码一个稳定的判空入口
PAID_PACK_IDS: set = set()


def _entitled(settings, plugin_id: str) -> bool:
    """能不能装/加载该能力包 —— 插件已全部免费，恒为 True。"""
    return True


def installed(settings) -> list:
    """列出已装能力包（冻结标记为兼容保留，现在恒不冻结）。"""
    out = []
    root = packs_dir(settings)
    if not root.exists():
        return out
    for pack in sorted(root.iterdir()):
        manifest = _find_manifest(pack)
        if manifest is None:
            continue
        try:
            m = json.loads(manifest.read_text(encoding="utf-8"))
            pid = m.get("id") or ""
            out.append({
                "id": pid,
                "name": m.get("name"),
                "version": m.get("version"),
                "kind": m.get("kind"),
                "permissions": m.get("permissions") or [],
                "tools": [t.get("name") for t in (m.get("tools") or [])],
                "persona": m.get("persona") or "",
                "frozen": not _entitled(settings, pid) if pid else True,
            })
        except Exception:  # noqa: BLE001
            continue
    return out


def allowed_pack_ids(settings) -> list:
    """当前账号可加载的已装能力包 id（能力包已全部免费，装了即加载）。"""
    return [
        p["id"] for p in installed(settings)
        if p.get("id") and not p.get("frozen")
    ]


def install_pack(settings, entry: dict, zip_path=None, log=None) -> dict:
    """下载并安装能力包（插件已全部免费，不再按权益拦截）。"""
    pid = str((entry or {}).get("id") or "").strip()
    if not pid:
        raise RuntimeError("能力包缺少 id")
    access = plugin_market.plugin_access(entry, lic_mod.entitlements())
    if not access.get("allowed"):
        raise PermissionError(access.get("reason") or "当前账号无权安装该能力包")
    ver = str(entry.get("version") or "1.0.0")
    dest = Path(zip_path) if zip_path else None
    if dest is None:
        dest_dir = Path(settings.downloads_dir) / "plugins"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"{pid}-{ver}.zip"
        plugin_market.download_plugin(
            str(entry.get("url")), dest, entry.get("sha256"))
    if not dest.exists():
        raise RuntimeError("能力包压缩包不存在")
    root = packs_dir(settings)
    root.mkdir(parents=True, exist_ok=True)
    target = root / pid
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    try:
        with zipfile.ZipFile(dest) as archive:
            for name in archive.namelist():
                if name.startswith("/") or ".." in name.split("/"):
                    raise RuntimeError("能力包包含非法路径: " + name)
            archive.extractall(target)
        # 顶层目录容错：zip 内是 <pid>/manifest.json 时把内容上提
        manifest = _find_manifest(target)
        if manifest is not None and manifest.parent != target:
            sub = manifest.parent
            for f in list(sub.rglob("*")):
                rel = f.relative_to(sub)
                if f.is_dir():
                    (target / rel).mkdir(parents=True, exist_ok=True)
                else:
                    (target / rel).parent.mkdir(parents=True, exist_ok=True)
                    f.replace(target / rel)
            shutil.rmtree(sub)
        manifest = _find_manifest(target)
        if manifest is None:
            raise RuntimeError("能力包缺少 manifest.json 清单")
        data = json.loads(manifest.read_text(encoding="utf-8"))
        if data.get("kind") in ("persona-pack", "agent-pack"):
            persona_text = compile_persona(data)
            if persona_text:
                ai_config.save_personality(settings, persona_text)
    except Exception:
        shutil.rmtree(target, ignore_errors=True)
        raise
    finally:
        if zip_path is None:
            dest.unlink(missing_ok=True)
    if log:
        log(f"能力包已安装: {pid} → {target}")
    return {
        "ok": True,
        "id": pid,
        "name": data.get("name") or pid,
        "kind": data.get("kind") or "",
        "dir": str(target),
    }


def uninstall_pack(settings, pack_id: str) -> dict:
    target = packs_dir(settings) / pack_id
    if target.exists():
        shutil.rmtree(target)
    return {"ok": True, "id": pack_id}


def pack_env(settings) -> dict:
    """机器人进程环境变量：能力包目录 + 允许加载列表 + 回复节奏行为文件。"""
    root = packs_dir(settings)
    allowed = allowed_pack_ids(settings)
    env = {
        "ASTROSWARM_TOOL_PACKS": str(root),
        "ASTROSWARM_TOOL_PACKS_ALLOWED": ",".join(allowed),
    }
    rhythm = root / "reply-rhythm" / "behavior.json"
    if rhythm.exists():
        env["ASTROSWARM_REPLY_RHYTHM"] = str(rhythm)
    # 主动聊天能力包：装了并允许加载后让 ai 插件导入它的实现
    if "proactive" in allowed:
        env["ASTROSWARM_PACK_PROACTIVE"] = "1"
    return env


# ---- 能力包详情与参数 ----
# schema 与无头端 console_ext.pack_detail / save_pack_config 完全一致：
#   manifest.config.fields = [{key, label, type(bool|number|enum/text), default, min, max, step, options, help}]
#   没有 fields 时按 manifest.behavior 的键自动造一份
# 用户改的值写在 <tool_packs>/<pid>/config.json，运行时缺项用默认值。
def _flatten(d) -> dict:
    """包里的 behavior/config 可能是 {"proactive": {...}} 这种单键包装，摊平一层。"""
    if isinstance(d, dict) and len(d) == 1:
        v = next(iter(d.values()))
        if isinstance(v, dict):
            return v
    return d if isinstance(d, dict) else {}


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def pack_fields(manifest: dict) -> list:
    """参数 schema：manifest.config.fields（没有就按 behavior 的键造一份）。"""
    fields = ((manifest or {}).get("config") or {}).get("fields") or []
    if fields:
        return list(fields)
    out = []
    for _, block in ((manifest or {}).get("behavior") or {}).items():
        if isinstance(block, dict):
            for key, value in block.items():
                if isinstance(value, bool):
                    kind = "bool"
                elif isinstance(value, (int, float)):
                    kind = "number"
                else:
                    kind = "text"
                out.append({"key": key, "label": key, "type": kind, "default": value})
    return out


def pack_features(manifest: dict) -> list:
    """详情页的「功能」列表：从 tools / behavior / schedule 派生。"""
    manifest = manifest or {}
    feats = []
    for tool in manifest.get("tools") or []:
        if isinstance(tool, dict):
            feats.append({"title": str(tool.get("name") or ""),
                          "desc": str(tool.get("description") or "")})
    for name, block in (manifest.get("behavior") or {}).items():
        if isinstance(block, dict):
            feats.append({"title": str(name),
                          "desc": "行为参数：" + "、".join(block.keys())})
    for name, block in (manifest.get("schedule") or {}).items():
        if isinstance(block, dict):
            feats.append({"title": f"计划任务 · {name}",
                          "desc": "、".join(f"{k}={v}" for k, v in block.items())})
    return [f for f in feats if f["title"]]


def pack_config_path(settings, pack_id: str) -> Path:
    return packs_dir(settings) / str(pack_id) / "config.json"


def pack_detail(settings, pack_id: str) -> dict:
    """某个能力包的详情（已装就读 manifest + config 与 behavior 的默认值）。"""
    pid = str(pack_id or "").strip()
    if not pid or "/" in pid or "\\" in pid or ".." in pid:
        raise ValueError("插件标识不合法")
    d = packs_dir(settings) / pid
    manifest = _read_json(d / "manifest.json")
    installed = bool(manifest)
    cfg = _flatten(_read_json(d / "config.json"))
    behavior = _flatten(_read_json(d / "behavior.json"))
    fields = pack_fields(manifest)
    defaults = {str(f["key"]): f["default"] for f in fields if "default" in f}
    for key, value in (behavior or {}).items():
        defaults.setdefault(key, value)
    return {
        "ok": True,
        "id": pid,
        "installed": installed,
        "name": manifest.get("name") or pid,
        "version": manifest.get("version") or "",
        "kind": manifest.get("kind") or "",
        "tier": manifest.get("tier") or "",
        "description": manifest.get("description") or "",
        "adapters": manifest.get("adapters") or [],
        "permissions": manifest.get("permissions") or [],
        "features": pack_features(manifest) if installed else [],
        "fields": fields,
        "defaults": defaults,
        "values": {**defaults, **cfg},
        "has_user_config": bool(cfg),
        "dir": str(d),
    }


def coerce_field(field: dict, raw):
    """按 schema 校验/转换一个值；不合法抛 ValueError（与无头端 _coerce 同规则）。"""
    key = str((field or {}).get("key") or "")
    ftype = str((field or {}).get("type") or "text")
    label = str((field or {}).get("label") or key)
    if ftype == "bool":
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, (int, float)):
            return bool(raw)
        if isinstance(raw, str):
            return raw.strip().lower() in ("1", "true", "on", "yes", "是")
        raise ValueError(f"{label}：要是开关值")
    if ftype == "number":
        try:
            val = float(raw)
        except (TypeError, ValueError):
            raise ValueError(f"{label}：要是数字") from None
        lo, hi = field.get("min"), field.get("max")
        if lo is not None and val < float(lo):
            raise ValueError(f"{label}：不能小于 {lo}")
        if hi is not None and val > float(hi):
            raise ValueError(f"{label}：不能大于 {hi}")
        if val == int(val) and float(field.get("step") or 1) >= 1:
            return int(val)
        return val
    if ftype in ("enum", "select"):
        options = field.get("options") or []
        vals = [o.get("value") if isinstance(o, dict) else o for o in options]
        if vals and raw not in vals:
            raise ValueError(f"{label}：只能是 {'/'.join(str(v) for v in vals)}")
        return raw
    return str(raw if raw is not None else "")


def save_pack_config(settings, pack_id: str, patch: dict) -> dict:
    """把用户改的参数写进 <tool_packs>/<pid>/config.json（只认 schema 里声明过的键）。"""
    detail = pack_detail(settings, pack_id)
    if not detail["installed"]:
        raise RuntimeError("这个能力包还没安装，装完才能改参数")
    if not isinstance(patch, dict) or not patch:
        raise ValueError("没有要改的参数")
    by_key = {str(f.get("key")): f for f in detail["fields"]}
    path = pack_config_path(settings, detail["id"])
    cur = _flatten(_read_json(path))
    changed = {}
    for key, raw in patch.items():
        field = by_key.get(str(key))
        if field is None:
            continue                      # 没在 schema 里的键直接忽略
        val = coerce_field(field, raw)
        if cur.get(key) != val:
            changed[str(key)] = val
        cur[str(key)] = val
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(cur, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    return {"ok": True, "id": detail["id"], "changed": changed,
            "values": cur, "path": str(path)}


# ---- 和风天气工具包配置（QWEATHER_* 环境变量注入）----
QW_CONFIG_NAME = "qweather.json"


def qweather_config_path(settings) -> Path:
    return Path(settings.root) / QW_CONFIG_NAME


def load_qweather_config(settings) -> dict:
    """读取 <根>/qweather.json；不存在/损坏返回空 dict。"""
    p = qweather_config_path(settings)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    return {
        k: str(data.get(k) or "")
        for k in ("project_id", "credential_id", "private_key_path", "api_host")
    }


def save_qweather_config(settings, project_id="", credential_id="",
                         private_key_path="", api_host="") -> dict:
    """保存和风天气配置（项目ID/凭据ID/私钥路径/API Host）。"""
    data = {
        "project_id": str(project_id or "").strip(),
        "credential_id": str(credential_id or "").strip(),
        "private_key_path": str(private_key_path or "").strip(),
        "api_host": str(api_host or "").strip(),
    }
    qweather_config_path(settings).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True}


def qweather_env(settings) -> dict:
    """把 qweather.json 配置映射成机器人进程的 QWEATHER_* 环境变量。"""
    data = load_qweather_config(settings)
    env = {}
    if data.get("project_id"):
        env["QWEATHER_PROJECT_ID"] = data["project_id"]
    if data.get("credential_id"):
        env["QWEATHER_CREDENTIAL_ID"] = data["credential_id"]
    if data.get("private_key_path"):
        env["QWEATHER_PRIVATE_KEY_PATH"] = data["private_key_path"]
    if data.get("api_host"):
        env["QWEATHER_API_HOST"] = data["api_host"]
    return env
