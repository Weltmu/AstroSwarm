# -*- coding: utf-8 -*-
"""工坊插件校验：结构 / 语法 / 危险调用 / 权限一致 / 通道一致 / 查重。

每条问题都是 {"level": "error"|"warn", "code": ..., "plain": 大白话,
"detail": 技术细节}：error 会触发自动重写，warn 只提示用户。
"""
import ast
import json
import re

from ..agent.tool import ALLOWED_PERMISSIONS

ALLOWED_ADAPTERS = ("qq_official", "wechat_ilink", "feishu", "telegram", "qq")
GROUP_ADAPTERS = ("qq_official", "qq")
MAX_FILE_BYTES = 24_000
MAX_TOTAL_BYTES = 160_000
MAX_FILES = 14
MAX_TOOLS = 5

ALLOWED_IMPORTS = {
    "json", "re", "time", "datetime", "math", "random", "string", "collections",
    "itertools", "functools", "hashlib", "hmac", "base64", "binascii", "typing",
    "dataclasses", "enum", "statistics", "decimal", "unicodedata", "textwrap",
    "uuid", "csv", "difflib", "copy", "heapq", "bisect", "operator", "numbers",
    "fractions", "urllib",
}
ALLOWED_IMPORT_EXACT = {"urllib.parse"}
DENY_CALLS = {"open", "eval", "exec", "compile", "__import__", "print", "input"}
TALK_KEYS_HARD = {"reply", "say", "answer", "words"}
TALK_KEYS_SOFT = {"message", "text", "content", "voice"}

_CJK = re.compile(r"[\u4e00-\u9fff]")
_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{1,31}$")
_TOOL_RE = re.compile(r"^[a-z][a-z0-9_]{1,31}$")


def _issue(level, code, plain, detail=""):
    return {"level": level, "code": code, "plain": plain, "detail": detail}


def _iter_calls(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                yield func.id, node
            elif isinstance(func, ast.Attribute):
                yield func.attr, node


def _imported_modules(tree):
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.add(node.module)
    return names


def _hardcoded_reply(tree):
    """找"写死话术"：返回值里带中文的 reply/message 字段。"""
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values):
            if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
                continue
            name = key.value
            if name not in TALK_KEYS_HARD and name not in TALK_KEYS_SOFT:
                continue
            if isinstance(value, ast.Constant) and isinstance(value.value, str) \
                    and _CJK.search(value.value):
                hits.append((name, value.value[:40],
                             "error" if name in TALK_KEYS_HARD else "warn"))
    return hits


def _check_python(name: str, code: str, tool_meta: dict, adapters: list,
                  permissions: list) -> list:
    issues = []
    label = f"工具 {name}"
    if len(code.encode("utf-8")) > MAX_FILE_BYTES:
        issues.append(_issue("error", "file_too_large",
                             f"{label} 的代码太长了，AI 需要写短一点。"))
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        issues.append(_issue("error", "syntax_error",
                             f"{label} 的代码有语法错误，跑不起来。",
                             f"{exc.msg}（第 {exc.lineno} 行）"))
        return issues
    has_handle = any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "handle" and len(node.args.args) >= 2
        for node in tree.body)
    if not has_handle:
        issues.append(_issue("error", "missing_handle",
                             f"{label} 少了 handle(ctx, args) 函数。"))
    for module in sorted(_imported_modules(tree)):
        top = module.split(".")[0]
        if module in ALLOWED_IMPORT_EXACT:
            continue
        if top in ALLOWED_IMPORTS and module == top:
            continue
        issues.append(_issue("error", "bad_import",
                             f"{label} 用了沙箱不允许的库（{module}）。"
                             "联网要用 ctx.send(\"http_request\", ...)。",
                             module))
    for func_name, node in _iter_calls(tree):
        if func_name in DENY_CALLS:
            issues.append(_issue("error", "bad_call",
                                 f"{label} 里用了不允许的 {func_name}()。",
                                 f"第 {getattr(node, 'lineno', '?')} 行"))
        if func_name == "send" and node.args:
            first = node.args[0]
            action = first.value if isinstance(first, ast.Constant) else ""
            if action == "http_request" and "network" not in permissions:
                issues.append(_issue("error", "permission_missing",
                                     f"{label} 用了联网动作，但 manifest 没声明 network 权限。"))
            if action in ("memory_read", "memory_write") and "memory" not in permissions:
                issues.append(_issue("error", "permission_missing",
                                     f"{label} 用了记忆动作，但 manifest 没声明 memory 权限。"))
            if action == "reminder_add" and "timer" not in permissions:
                issues.append(_issue("error", "permission_missing",
                                     f"{label} 用了定时动作，但 manifest 没声明 timer 权限。"))
            if action in ("mute_user", "mute_all", "recall_message"):
                if "group_admin" not in permissions:
                    issues.append(_issue("error", "permission_missing",
                                         f"{label} 用了群管理动作，但 manifest 没声明 group_admin 权限。"))
                if not any(a in GROUP_ADAPTERS for a in adapters):
                    issues.append(_issue("error", "channel_mismatch",
                                         f"{label} 用了群管理动作，但插件没声明 QQ 通道。"))
    for key, sample, level in _hardcoded_reply(tree):
        if level == "error":
            issues.append(_issue("error", "hardcoded_reply",
                                 f"{label} 里写死了给用户看的话（{sample}）。"
                                 "工具只能返回数据，说话由 agent 负责。"))
        else:
            issues.append(_issue("warn", "possible_hardcoded_reply",
                                 f"{label} 的 {key} 字段像是写死的文案（{sample}），"
                                 "建议只返回数据。"))
    if tool_meta.get("description") and _CJK.search(str(tool_meta["description"])) is None:
        issues.append(_issue("warn", "description_not_chinese",
                             f"{label} 的说明不是中文，agent 不好判断什么时候用。"))
    return issues


def validate_files(files: dict, existing_tools: set) -> list:
    """检查一份待安装的插件文件集合。"""
    issues = []
    if not isinstance(files, dict) or not files:
        return [_issue("error", "empty_files", "AI 没有输出任何文件。")]
    if len(files) > MAX_FILES:
        issues.append(_issue("error", "too_many_files",
                             "文件太多了，一个插件最多十来个文件。"))
    total = sum(len(str(v).encode("utf-8")) for v in files.values())
    if total > MAX_TOTAL_BYTES:
        issues.append(_issue("error", "too_large", "插件整体太大了，AI 要精简。"))
    manifest_text = files.get("manifest.json")
    if not manifest_text:
        issues.append(_issue("error", "no_manifest", "缺少 manifest.json。"))
        return issues
    try:
        manifest = json.loads(manifest_text)
    except Exception as exc:  # noqa: BLE001
        issues.append(_issue("error", "bad_manifest_json",
                             "manifest.json 不是合法 JSON。", str(exc)[:200]))
        return issues
    if not isinstance(manifest, dict):
        issues.append(_issue("error", "bad_manifest_json", "manifest.json 必须是对象。"))
        return issues
    pid = str(manifest.get("id") or "")
    if not _ID_RE.match(pid):
        issues.append(_issue("error", "bad_id",
                             "插件 id 要用小写字母/数字/中划线（2~32 位）。", pid))
    if str(manifest.get("kind") or "") != "tool-pack":
        issues.append(_issue("error", "bad_kind", "kind 必须是 tool-pack。"))
    if not str(manifest.get("name") or "").strip():
        issues.append(_issue("error", "no_name", "插件缺少中文名字。"))
    if not str(manifest.get("version") or "").strip():
        issues.append(_issue("error", "no_version", "插件缺少版本号。"))
    if not manifest.get("sandbox"):
        issues.append(_issue("error", "sandbox_required",
                             "工坊生成的插件必须声明 sandbox: true（只能在沙箱里跑）。"))
    adapters = [str(a) for a in (manifest.get("adapters") or [])]
    if not adapters:
        issues.append(_issue("error", "no_adapters",
                             "没写支持哪些通道（adapters）。"))
    for a in adapters:
        if a not in ALLOWED_ADAPTERS:
            issues.append(_issue("error", "bad_adapter",
                                 f"通道 {a} 不认识（可用：{'/'.join(ALLOWED_ADAPTERS)}）。"))
    permissions = [str(p) for p in (manifest.get("permissions") or [])]
    for p in permissions:
        if p not in ALLOWED_PERMISSIONS:
            issues.append(_issue("error", "bad_permission",
                                 f"权限 {p} 不在允许列表里。"))
    if "group_admin" in permissions and not any(a in GROUP_ADAPTERS for a in adapters):
        issues.append(_issue("error", "channel_mismatch",
                             "声明了群管理权限，但没用 QQ 通道。"))
    tools = manifest.get("tools") or []
    if not isinstance(tools, list) or not tools:
        issues.append(_issue("error", "no_tools", "插件里一个工具都没有。"))
        return issues
    if len(tools) > MAX_TOOLS:
        issues.append(_issue("error", "too_many_tools",
                             f"工具太多（{len(tools)} 个），一个插件最多 {MAX_TOOLS} 个。"))
    seen = set()
    for tool in tools:
        if not isinstance(tool, dict):
            issues.append(_issue("error", "bad_tool", "tools 里有一项不是对象。"))
            continue
        name = str(tool.get("name") or "")
        if not _TOOL_RE.match(name):
            issues.append(_issue("error", "bad_tool_name",
                                 f"工具名 {name or '空'} 不合法（小写字母/数字/下划线）。"))
            continue
        if name in seen:
            issues.append(_issue("error", "dup_tool", f"工具名 {name} 重复了。"))
        seen.add(name)
        if name in (existing_tools or set()):
            issues.append(_issue("error", "tool_exists",
                                 f"工具名 {name} 已被别的插件占用，AI 要换个名字或加前缀。"))
        params = tool.get("parameters")
        if not isinstance(params, dict) or params.get("type") != "object" \
                or not isinstance(params.get("properties"), dict):
            issues.append(_issue("error", "bad_parameters",
                                 f"{name} 的参数不是标准 JSON Schema（要 type=object + properties）。"))
        if not str(tool.get("description") or "").strip():
            issues.append(_issue("error", "no_tool_desc",
                                 f"{name} 没写「什么时候用它」的说明。"))
        path = f"tools/{name}.py"
        code = files.get(path)
        if not code:
            issues.append(_issue("error", "no_tool_file", f"缺少文件 {path}。"))
            continue
        issues.extend(_check_python(name, code, tool, adapters, permissions
                                    + [str(p) for p in (tool.get("permissions") or [])]))
    return issues


def errors(issues: list) -> list:
    return [i for i in issues if i.get("level") == "error"]


def to_plain(issues: list) -> list:
    out = []
    for item in issues:
        text = str(item.get("plain") or item.get("code"))
        if text not in out:
            out.append(text)
    return out


CHANNEL_LABELS = {
    "qq_official": ("QQ 群", "QQ 私聊"),
    "qq": ("QQ 群（个人号）", "QQ 私聊（个人号）"),
    "wechat_ilink": ("微信私聊",),
    "feishu": ("飞书私聊",),
    "telegram": ("纸飞机私聊",),
}


def plain_report(manifest: dict) -> dict:
    """安装前给用户看的大白话说明。"""
    adapters = [str(a) for a in (manifest.get("adapters") or [])]
    scopes = []
    for a in adapters:
        for label in CHANNEL_LABELS.get(a, (a,)):
            if label not in scopes:
                scopes.append(label)
    permissions = [str(p) for p in (manifest.get("permissions") or [])]
    notes = []
    if "network" in permissions:
        notes.append("它要联网：会把关键词发给外部网站查（只能查公开网址，进不了你电脑）。")
    if "group_admin" in permissions:
        notes.append("它要群管理权限：机器人得是群管理员才能禁言/撤回。")
    if "timer" in permissions:
        notes.append("它能设定时提醒：到点由机器人主动发消息。")
    if "memory" in permissions:
        notes.append("它能读写长期记忆：记住用户说过的事。")
    if "wechat_ilink" in adapters:
        notes.append("微信只能私聊，而且主动消息只有 30 分钟窗口。")
    if not adapters or set(adapters) == {"wechat_ilink"}:
        notes.append("这个插件在群里用不了。")
    notes.append("它只能在沙箱里跑：碰不到你的文件、系统和其他插件的数据。")
    return {
        "id": str(manifest.get("id") or ""),
        "name": str(manifest.get("name") or ""),
        "used_in": scopes,
        "permissions": permissions,
        "notes": notes,
    }
