# -*- coding: utf-8 -*-
"""插件工坊 · 分享与投稿（M5）。

三条路，都是用户视角一句话能说清的：
- **导出 zip**：把装好的插件打包，发给朋友或者发群里；
- **导入 zip**：别人给的插件包，先过一遍同一套自动检查（语法/权限/沙箱试跑），
  不合格直接拒绝，绝不把来路不明的代码装进机器人；
- **上传到官网**：用星群账号把 zip 传给服务器，站长在官网审核台点通过之后，
  才会进插件市场（`category=社区插件`），所有用户都能一键装。

投稿状态（审核中 / 已上架 / 被驳回 + 原因）在工坊页面直接能看。
"""
import base64
import json
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

from .. import account
from ..license import SERVER_WEB
from . import generator, installer, validator

MAX_ZIP_BYTES = 5 * 1024 * 1024
UPLOAD_TIMEOUT = 60        # 传 zip 用长超时
SMALL_TIMEOUT = 20         # 发验证码 / 读列表这种小请求
_ALLOWED_EXT = (".json", ".py", ".md", ".txt")
_MAX_FILES = 40
MAX_AUTHOR_LEN = 32


class PublishError(RuntimeError):
    """分享/投稿失败（大白话说明）。"""


def export_zip(settings, pid: str) -> dict:
    """把已装的插件打包成 zip，放进 workshop/export/；返回路径。"""
    pid = str(pid or "").strip()
    src = installer.packs_root(settings) / pid
    if not pid or not src.is_dir():
        raise PublishError("先选一个已装的插件。")
    manifest = {}
    try:
        manifest = json.loads((src / "manifest.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        manifest = {}
    version = str(manifest.get("version") or "1.0.0")
    out_dir = installer.workshop_root(settings) / "export"
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{pid}-{version}.zip"
    count = 0
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(src.rglob("*")):
            if not path.is_file():
                continue
            if "__pycache__" in path.parts or path.suffix not in _ALLOWED_EXT:
                continue
            zf.write(path, path.relative_to(src).as_posix())
            count += 1
    return {"ok": True, "path": str(target), "bytes": target.stat().st_size,
            "files": count, "id": pid, "version": version,
            "name": manifest.get("name") or pid}


def files_of(settings, pid: str) -> dict:
    """读一个已装插件的文件内容（相对路径 → 文本），修复/导出共用。"""
    src = installer.packs_root(settings) / str(pid or "").strip()
    out = {}
    if not src.is_dir():
        return out
    for path in sorted(src.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        if path.suffix not in _ALLOWED_EXT:
            continue
        try:
            out[path.relative_to(src).as_posix()] = path.read_text(encoding="utf-8")
        except Exception:  # noqa: BLE001
            continue
    return out


def existing_tools_without(settings, pid: str) -> set:
    """已占用的工具名，但去掉 pid 这个插件自己的 —— 升级/修同一插件时不该跟自己撞名。"""
    tools = set(generator.collect_existing(settings)["tools"])
    try:
        manifest = json.loads(
            (installer.packs_root(settings) / str(pid or "") / "manifest.json")
            .read_text(encoding="utf-8"))
        for tool in (manifest.get("tools") or []):
            if isinstance(tool, dict) and tool.get("name"):
                tools.discard(str(tool["name"]))
    except Exception:  # noqa: BLE001
        pass
    return tools


def read_zip(zip_path) -> dict:
    """读一个插件 zip → {相对路径: 文本}；结构不对就抛 PublishError。"""
    path = Path(zip_path)
    if not path.is_file():
        raise PublishError("找不到这个 zip 文件。")
    if path.stat().st_size > MAX_ZIP_BYTES:
        raise PublishError("插件包太大了（上限 5MB）。")
    try:
        zf = zipfile.ZipFile(path)
    except Exception as exc:  # noqa: BLE001
        raise PublishError("这不是一个正常的 zip 文件。") from exc
    entries = {}
    with zf:
        infos = [i for i in zf.infolist() if not i.is_dir()]
        if len(infos) > _MAX_FILES:
            raise PublishError(f"插件里文件太多了（上限 {_MAX_FILES} 个）。")
        for info in infos:
            name = str(info.filename or "").replace("\\", "/")
            if not name or name.startswith("/") or ".." in name.split("/"):
                raise PublishError(f"插件包里有不安全的路径：{name}")
            if not name.lower().endswith(_ALLOWED_EXT):
                raise PublishError(f"插件包里只能有 json / py / md / txt，发现了 {name}")
            entries[name] = zf.read(info).decode("utf-8", "replace")
    tops = {n.split("/")[0] for n in entries}
    if "manifest.json" not in entries and len(tops) == 1:
        only = next(iter(tops))
        if only + "/manifest.json" in entries:
            entries = {n[len(only) + 1:]: v for n, v in entries.items()
                       if n.startswith(only + "/")}
    if "manifest.json" not in entries:
        raise PublishError("插件包里没有 manifest.json。")
    return entries


def import_zip(settings, zip_path, on_log=None) -> dict:
    """导入别人给的插件包：静态检查 + 沙箱试跑全过才装。"""
    log = on_log or (lambda msg: None)
    files = read_zip(zip_path)
    try:
        manifest = json.loads(files.get("manifest.json") or "{}")
    except Exception as exc:  # noqa: BLE001
        raise PublishError("manifest.json 不是合法的 JSON。") from exc
    if not isinstance(manifest, dict):
        raise PublishError("manifest.json 内容不对。")
    log("正在检查插件包…")
    issues = validator.validate_files(
        files, existing_tools_without(settings, str(manifest.get("id") or "")))
    bad = validator.errors(issues)
    if bad:
        raise PublishError("这个插件包没通过检查：" +
                           "；".join(str(i.get("plain")) for i in bad[:3]))
    log("正在沙箱里试跑…")
    plan = {"tools": manifest.get("tools") or [], "name": manifest.get("name") or ""}
    dry = generator.dry_run(files, plan)
    if validator.errors(dry):
        raise PublishError("这个插件包试跑没过：" +
                           "；".join(str(i.get("plain")) for i in validator.errors(dry)[:3]))
    pid = installer.unique_id(settings, str(manifest.get("id") or "imported_pack"))
    if pid != str(manifest.get("id") or ""):
        manifest["id"] = pid
        files["manifest.json"] = json.dumps(manifest, ensure_ascii=False, indent=2)
    result = installer.install(settings, pid, files, {
        "name": manifest.get("name") or pid,
        "need": "外部导入的插件包",
        "plan": plan,
        "model": "",
        "source": "imported",
    })
    result["name"] = manifest.get("name") or pid
    return result


def _post(path: str, payload: dict, token: str,
          timeout: int = UPLOAD_TIMEOUT) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        SERVER_WEB + path, data=body, method="POST",
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + token})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        try:
            data = json.loads(exc.read().decode("utf-8", "replace"))
        except Exception:  # noqa: BLE001
            data = {}
        raise PublishError(str(data.get("detail") or f"上传失败（HTTP {exc.code}）")) from exc
    except Exception as exc:  # noqa: BLE001
        raise PublishError("连不上星群服务器，检查一下网络。" + str(exc)[:120]) from exc


def _get(path: str, token: str) -> dict:
    req = urllib.request.Request(SERVER_WEB + path,
                                 headers={"Authorization": "Bearer " + token})
    try:
        with urllib.request.urlopen(req, timeout=UPLOAD_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        try:
            data = json.loads(exc.read().decode("utf-8", "replace"))
        except Exception:  # noqa: BLE001
            data = {}
        raise PublishError(str(data.get("detail") or f"读投稿失败（HTTP {exc.code}）")) from exc
    except Exception as exc:  # noqa: BLE001
        raise PublishError("连不上星群服务器，检查一下网络。" + str(exc)[:120]) from exc


def _token() -> tuple:
    data = account.load_account() or {}
    token = str(data.get("token") or "")
    if not token:
        raise PublishError("上传要用星群账号登录。到「设置 → 星群账号」登录一下再传。")
    return token, str(data.get("email") or "")


def account_email() -> str:
    """当前登录的星群账号邮箱（没登录返回空串）。"""
    return str((account.load_account() or {}).get("email") or "")


def mask_email(email: str) -> str:
    """邮箱打码：abcd@qq.com → ab**@qq.com（界面上给人看，别直接泼完整地址）。"""
    text = str(email or "").strip()
    if "@" not in text:
        return text or "（未登录）"
    name, _, domain = text.partition("@")
    keep = name[:2] if len(name) > 2 else name[:1]
    return f"{keep}**@{domain}"


def default_author() -> str:
    """默认作者名：账号邮箱前缀。"""
    email = account_email()
    return email.split("@")[0][:MAX_AUTHOR_LEN] if email else ""


def clean_author(name: str) -> str:
    """作者名清洗：去空白与控制字符，最多 32 字。"""
    text = " ".join(str(name or "").split())
    text = "".join(ch for ch in text if ch.isprintable())
    return text[:MAX_AUTHOR_LEN]


def request_upload_code(settings=None, on_log=None) -> dict:
    """上传前先要一条邮箱验证码：每次上传都要验，服务器每次都会发一封邮件。"""
    token, email = _token()
    data = _post("/api/account/plugins/upload-code", {}, token,
                 timeout=SMALL_TIMEOUT)
    return {"ok": True, "email": data.get("email") or email,
            "expires_in": int(data.get("expires_in") or 300),
            "message": data.get("message") or f"验证码已发到 {email}，5 分钟内有效。"}


def upload(settings, pid: str, note: str = "", code: str = "",
           username: str = "", on_log=None) -> dict:
    """把插件传给官网等站长审核（审核通过后才会进插件市场）。

    每次上传都要带一条邮箱验证码（服务器校验后即刻作废）：
    先调 request_upload_code() 发码，再把它填进来。
    """
    log = on_log or (lambda msg: None)
    token, email = _token()
    if not str(code or "").strip():
        raise PublishError("请先点「发送验证码」，把邮箱收到的 6 位码填上再传。")
    packed = export_zip(settings, pid)
    raw = Path(packed["path"]).read_bytes()
    manifest = {}
    try:
        manifest = json.loads(
            (installer.packs_root(settings) / pid / "manifest.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        manifest = {}
    log(f"正在上传「{packed['name']}」（{round(len(raw) / 1024)} KB）…")
    data = _post("/api/account/plugins/submit", {
        "name": packed["name"],
        "version": packed["version"],
        "description": str(manifest.get("description") or "")[:300],
        "kind": str(manifest.get("kind") or "tool-pack"),
        "note": str(note or "")[:300],
        "username": clean_author(username) or default_author(),
        "code": str(code or "").strip(),
        "zip_b64": base64.b64encode(raw).decode("ascii"),
    }, token)
    return {"ok": True, "id": data.get("id"), "status": data.get("status") or "pending",
            "message": data.get("message") or "已提交，等站长审核。",
            "email": email, "username": data.get("username") or username,
            "path": packed["path"], "bytes": packed["bytes"]}


def upload_file(settings, zip_path, note: str = "", code: str = "",
                username: str = "", on_log=None) -> dict:
    """上传本地选中的插件 zip（不用先装进机器人）。"""
    log = on_log or (lambda msg: None)
    token, email = _token()
    if not str(code or "").strip():
        raise PublishError("请先点「发送验证码」，把邮箱收到的 6 位码填上再传。")
    files = read_zip(zip_path)      # 先在本机过一遍结构检查，省得白跑一趟
    try:
        manifest = json.loads(files.get("manifest.json") or "{}")
    except Exception as exc:  # noqa: BLE001
        raise PublishError("manifest.json 不是合法的 JSON。") from exc
    if not isinstance(manifest, dict):
        raise PublishError("manifest.json 内容不对。")
    raw = Path(zip_path).read_bytes()
    log(f"正在上传「{manifest.get('name') or Path(zip_path).name}」"
        f"（{round(len(raw) / 1024)} KB）…")
    data = _post("/api/account/plugins/submit", {
        "name": str(manifest.get("name") or Path(zip_path).stem)[:60],
        "version": str(manifest.get("version") or "1.0.0")[:24],
        "description": str(manifest.get("description") or "")[:300],
        "kind": str(manifest.get("kind") or "tool-pack"),
        "note": str(note or "")[:300],
        "username": clean_author(username) or default_author(),
        "code": str(code or "").strip(),
        "zip_b64": base64.b64encode(raw).decode("ascii"),
    }, token)
    return {"ok": True, "id": data.get("id"), "status": data.get("status") or "pending",
            "message": data.get("message") or "已提交，等站长审核。",
            "email": email, "username": data.get("username") or username,
            "path": str(zip_path), "bytes": len(raw)}


def submissions() -> dict:
    """我的投稿列表（含审核状态、驳回原因）。"""
    token, _ = _token()
    data = _get("/api/account/plugins/submissions", token)
    return {"ok": True, "submissions": data.get("submissions") or []}


def withdraw(submission_id: int) -> dict:
    """撤回一条还没审的投稿。"""
    token, _ = _token()
    return _post("/api/account/plugins/submissions/withdraw",
                 {"id": int(submission_id)}, token)


def describe(items: list) -> list:
    """把投稿列表整理成界面直接能显示的行（大白话状态）。"""
    status_cn = {"pending": "审核中", "approved": "已上架", "rejected": "被驳回",
                 "withdrawn": "已撤回", "offline": "已下架"}
    out = []
    for row in items or []:
        when = ""
        try:
            when = time.strftime("%m-%d %H:%M", time.localtime(float(row.get("created_at") or 0)))
        except Exception:  # noqa: BLE001
            when = ""
        line = (f"{row.get('name') or row.get('plugin_id') or '未命名'} · v{row.get('version') or '?'}"
                f" · {status_cn.get(str(row.get('status')), row.get('status'))}")
        if when:
            line += f" · {when}"
        if row.get("status") == "rejected" and row.get("reason"):
            line += f" · 站长说：{row['reason']}"
        if row.get("status") == "approved" and row.get("final_id"):
            line += f" · 市场 id：{row['final_id']}"
        out.append({"id": row.get("id"), "text": line, "status": row.get("status")})
    return out
