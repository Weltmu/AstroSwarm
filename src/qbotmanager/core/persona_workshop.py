# -*- coding: utf-8 -*-
"""本地人设工坊：导入/校验/安装/启用/卸载用户自制人格卡（persona + tools）。

与插件市场分开：这里只处理用户本地上传的人设包，不经过服务器；
人设包 = 人格卡 v1（结构化字段或整段 system_prompt）+ 可选 tools/ 工具代码。
安装后写入 <安装根>/personas/<id>/，启用后由 AI 大脑页写入人格并注入 AgentRuntime。
"""
import json
import re
import shutil
import zipfile
from pathlib import Path

from . import ai_config
from .agent.tool import compile_persona, validate_persona_card

TEMPLATE_FILE = (
    Path(__file__).resolve().parent.parent
    / "assets" / "persona_template" / "persona-card-template.json"
)
GUIDE_FILE = TEMPLATE_FILE.parent / "persona-card-模板说明.md"


def personas_dir(settings) -> Path:
    return Path(settings.root) / "personas"


# 人设 id 会被直接当目录名用（install 的 copytree/rmtree、uninstall 的 rmtree、
# activate 的 _find_manifest 都拼 `root / id`），所以白名单必须放在**共用层**：
# Linux 控制台在网络入口另有一份同样的校验，桌面端这里是唯一防线。
_PID_RE = re.compile(r"^[A-Za-z0-9_\-\.]{1,64}$")


def valid_persona_id(value) -> bool:
    """人设 id 白名单：字母/数字/._-，1~64 位，且不含 `..`。"""
    pid = str(value or "").strip()
    return bool(_PID_RE.match(pid)) and pid not in (".", "..") and ".." not in pid


def _persona_dir(settings, pid) -> Path:
    """返回 `<人设根>/<id>`，把非法 id / 符号链接 / 越界路径挡在落盘之前。"""
    pid = str(pid or "").strip()
    if not valid_persona_id(pid):
        raise RuntimeError("人设 id 不合法：只允许字母/数字/._- 且 1~64 位，不能含 ..")
    root = personas_dir(settings)
    target = root / pid
    if target.is_symlink():
        raise RuntimeError("人设目录是符号链接，已拒绝操作")
    if target.resolve().parent != root.resolve():
        raise RuntimeError("人设路径越界，已拒绝操作")
    return target


def template_text() -> str:
    try:
        return TEMPLATE_FILE.read_text(encoding="utf-8")
    except OSError:
        return "{}"


def guide_text() -> str:
    try:
        return GUIDE_FILE.read_text(encoding="utf-8")
    except OSError:
        return "（模板说明缺失，请重新安装星群客户端）"


def _find_manifest(pack_dir: Path):
    m = pack_dir / "manifest.json"
    if m.exists():
        return m
    for sub in pack_dir.iterdir():
        if sub.is_dir() and (sub / "manifest.json").exists():
            return sub / "manifest.json"
    return None


def _normalize_top_dir(target: Path):
    """zip 里带顶层目录（<id>/manifest.json）时把内容上提。"""
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


def list_personas(settings) -> list:
    """列出本地已装人设包。"""
    out = []
    root = personas_dir(settings)
    if not root.exists():
        return out
    active = str(getattr(settings, "local_persona_id", "") or "")
    for pack in sorted(root.iterdir()):
        manifest = _find_manifest(pack)
        if manifest is None:
            continue
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        if validate_persona_card(data) is not None:
            continue
        out.append({
            "id": str(data.get("id") or ""),
            "name": str(data.get("name") or ""),
            "version": str(data.get("version") or ""),
            "summary": str(data.get("summary") or data.get("description") or ""),
            "tools": [t.get("name") for t in (data.get("tools") or [])],
            "active": str(data.get("id") or "") == active,
        })
    return out


def install_persona(settings, source_path, log=None) -> dict:
    """导入人设：支持单 JSON 或 zip（manifest.json + tools/）。"""
    source = Path(source_path)
    if not source.exists():
        raise RuntimeError("文件不存在")
    root = personas_dir(settings)
    root.mkdir(parents=True, exist_ok=True)
    if source.suffix.lower() == ".zip":
        with zipfile.ZipFile(source) as archive:
            for name in archive.namelist():
                if name.startswith("/") or ".." in name.split("/"):
                    raise RuntimeError("压缩包包含非法路径: " + name)
            # 先解到临时目录，校验通过再落位
            tmp = root / ".import_tmp"
            if tmp.exists():
                shutil.rmtree(tmp)
            tmp.mkdir(parents=True)
            try:
                archive.extractall(tmp)
                _normalize_top_dir(tmp)
                manifest = _find_manifest(tmp)
                if manifest is None:
                    raise RuntimeError("压缩包里缺少 manifest.json")
                data = json.loads(manifest.read_text(encoding="utf-8"))
                err = validate_persona_card(data)
                if err:
                    raise RuntimeError("人设校验失败：" + err)
                pid = str(data["id"])
                target = _persona_dir(settings, pid)
                if target.exists():
                    shutil.rmtree(target)
                shutil.copytree(tmp, target)
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
    else:
        try:
            data = json.loads(source.read_text(encoding="utf-8"))
        except (ValueError, OSError) as e:
            raise RuntimeError("JSON 解析失败：" + str(e)) from e
        err = validate_persona_card(data)
        if err:
            raise RuntimeError("人设校验失败：" + err)
        pid = str(data["id"])
        target = _persona_dir(settings, pid)
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True)
        (target / "manifest.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    if log:
        log(f"人设已安装: {data.get('name')} ({pid})")
    return {
        "ok": True,
        "id": pid,
        "name": data.get("name"),
        "version": data.get("version"),
        "tools": [t.get("name") for t in (data.get("tools") or [])],
    }


def uninstall_persona(settings, pid: str) -> dict:
    target = _persona_dir(settings, pid)
    if target.exists():
        shutil.rmtree(target)
    if str(getattr(settings, "local_persona_id", "") or "") == pid:
        settings.local_persona_id = ""
        try:
            settings.save()
        except OSError:
            pass
    return {"ok": True, "id": pid}


def activate_persona(settings, pid: str) -> dict:
    """启用本地人设：写入人格到 AI 配置 + 标记启用 + 关闭硬编码档案接管。"""
    pid = str(pid or "").strip()
    manifest = _find_manifest(_persona_dir(settings, pid))
    if manifest is None:
        raise RuntimeError("人设不存在：" + pid)
    data = json.loads(manifest.read_text(encoding="utf-8"))
    err = validate_persona_card(data)
    if err:
        raise RuntimeError("人设校验失败：" + err)
    text = compile_persona(data)
    if not text:
        raise RuntimeError("人设内容为空")
    ai_config.save_personality(settings, text)
    settings.local_persona_id = pid
    # 本地人设走 AI 插件人格通道；硬编码的李清菡/EVA 档案接管关闭，避免双人格
    settings.agent_profile_enabled = False
    try:
        settings.save()
    except OSError as e:
        raise RuntimeError("保存设置失败：" + str(e)) from e
    return {"ok": True, "id": pid, "name": data.get("name")}


def deactivate_persona(settings) -> dict:
    settings.local_persona_id = ""
    try:
        settings.save()
    except OSError as e:
        raise RuntimeError("保存设置失败：" + str(e)) from e
    return {"ok": True}


def pack_env(settings) -> dict:
    """机器人进程环境变量：本地人设目录 + 仅允许加载已启用的人设工具。"""
    env = {"ASTROSWARM_PERSONAS": str(personas_dir(settings))}
    active = str(getattr(settings, "local_persona_id", "") or "")
    allowed = []
    if active:
        manifest = _find_manifest(personas_dir(settings) / active)
        if manifest is not None:
            allowed = [active]
    env["ASTROSWARM_PERSONAS_ALLOWED"] = ",".join(allowed)
    return env
