# -*- coding: utf-8 -*-
"""工坊生成流程：需求 → 方案 → 生成 → 自动检查 → 自动重写(≤2) → 沙箱干跑。

设计要点：
- 生成模型独立于「AI 大脑」（core/workshop/config.py），且强制强模型；
- 两段式：先出方案给用户看，再写代码（一次写对概率高很多）；
- 检查不过自动让 AI 重写（最多 2 次），错误全部转成大白话；
- 干跑在真沙箱里跑（动作全部拒绝），保证不会真的发消息/联网。
"""
import asyncio
import json
import re
import shutil
import tempfile
import time
from pathlib import Path
from urllib.request import Request, urlopen

from ..agent.sandbox import run_tool
from ..agent.tool import ToolContext
from . import config as ws_config
from . import installer, prompts
from .validator import errors, plain_report, to_plain, validate_files

MODEL_TIMEOUT = 240
MAX_REPAIRS = 2


class WorkshopError(RuntimeError):
    """工坊错误：plain 是给用户看的大白话，detail 是技术细节。"""

    def __init__(self, plain: str, detail: str = ""):
        super().__init__(plain)
        self.plain = plain
        self.detail = detail


# ---- 模型调用（OpenAI 兼容 + Anthropic）----


def _post_json(url: str, payload: dict, headers: dict, timeout: int) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    for key, value in headers.items():
        req.add_header(key, value)
    with urlopen(req, timeout=timeout) as resp:  # noqa: S310 —— 只连用户自己配的服务商
        return json.loads(resp.read().decode("utf-8", "replace"))


def call_model(settings, system: str, user: str, timeout: int = MODEL_TIMEOUT) -> str:
    """按工坊配置调模型；失败抛 WorkshopError（大白话 + 细节）。"""
    cfg = ws_config.resolved(settings)
    key = str(cfg.get("provider") or "")
    if key not in ws_config.PROVIDER_KEYS:
        raise WorkshopError(
            f"插件工坊还没配模型（必须用强模型：{ws_config.AGENT_CAPABLE_HINT}）。")
    if not cfg.get("api_key"):
        raise WorkshopError("插件工坊的 API Key 是空的，先在工坊页里填上。")
    api_url = str(cfg.get("api_url") or "").rstrip("/")
    model = str(cfg.get("model") or "")
    try:
        if cfg.get("protocol") == "anthropic":
            data = _post_json(
                api_url + "/v1/messages",
                {"model": model, "max_tokens": 8000, "system": system,
                 "messages": [{"role": "user", "content": user}]},
                {"x-api-key": cfg["api_key"], "anthropic-version": "2023-06-01"},
                timeout)
            parts = data.get("content") or []
            text = "".join(str(p.get("text") or "") for p in parts
                           if isinstance(p, dict))
        else:
            data = _post_json(
                api_url + "/chat/completions",
                {"model": model, "temperature": 0.3, "max_tokens": 8000,
                 "messages": [{"role": "system", "content": system},
                              {"role": "user", "content": user}]},
                {"Authorization": "Bearer " + cfg["api_key"]},
                timeout)
            text = str(((data.get("choices") or [{}])[0]
                        .get("message") or {}).get("content") or "")
    except WorkshopError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise WorkshopError(
            "连不上生成模型。请检查工坊的 API Key / 网络 / 模型名是否对。",
            str(exc)[:300]) from exc
    if not text.strip():
        raise WorkshopError("模型返回了空内容，再试一次；还不行就换个模型。")
    return text


_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def parse_json(text: str) -> dict:
    """从模型输出里抠出 JSON（容忍 ```json 代码块和前后废话）。"""
    raw = str(text or "").strip()
    match = _FENCE.search(raw)
    if match:
        raw = match.group(1).strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end <= start:
        raise WorkshopError("AI 没有按格式返回 JSON，重试或换个模型。", raw[:400])
    chunk = raw[start:end + 1]
    try:
        data = json.loads(chunk)
    except Exception as exc:  # noqa: BLE001
        raise WorkshopError("AI 返回的 JSON 不完整（多半是被截断了），重试或换个模型。",
                            f"{exc} | {chunk[:300]}") from exc
    if not isinstance(data, dict):
        raise WorkshopError("AI 返回的顶层不是 JSON 对象。", chunk[:300])
    return data


# ---- 已有插件：查重用的工具名 / id（只读 manifest，不加载代码）----


def collect_existing(settings) -> dict:
    tools, ids = set(), set()
    root = installer.packs_root(settings)
    if root.exists():
        for pack in sorted(root.iterdir()):
            manifest = pack / "manifest.json"
            if not manifest.exists():
                continue
            ids.add(pack.name)
            try:
                data = json.loads(manifest.read_text(encoding="utf-8"))
                for tool in (data.get("tools") or []):
                    if isinstance(tool, dict) and tool.get("name"):
                        tools.add(str(tool["name"]))
            except Exception:  # noqa: BLE001
                continue
    return {"tools": sorted(tools), "ids": sorted(ids)}


# ---- 三个步骤 ----


def make_plan(settings, need: str, channels: list) -> dict:
    existing = collect_existing(settings)
    cfg = ws_config.resolved(settings)
    prompt = prompts.plan_prompt(need, existing["tools"], channels)
    text = call_model(settings, prompts.PLAN_SYSTEM, prompt)
    plan = parse_json(text)
    plan["id"] = installer.unique_id(settings, str(plan.get("id") or "ai_pack"))
    plan.setdefault("name", plan["id"])
    plan.setdefault("what", "")
    plan.setdefault("tools", [])
    plan.setdefault("adapters", [])
    plan.setdefault("permissions", [])
    plan["model"] = f"{cfg.get('provider_name')} · {cfg.get('model')}"
    return plan


def files_from_payload(payload: dict) -> dict:
    """把模型给的 {manifest, tools} 组装成 {相对路径: 内容}。"""
    manifest = payload.get("manifest")
    tools = payload.get("tools")
    if not isinstance(manifest, dict) or not isinstance(tools, dict):
        raise WorkshopError("AI 输出的插件结构不对（缺 manifest 或 tools）。",
                            json.dumps(payload, ensure_ascii=False)[:400])
    manifest.setdefault("kind", "tool-pack")
    manifest.setdefault("version", "1.0.0")
    manifest["sandbox"] = True
    files = {"manifest.json": json.dumps(manifest, ensure_ascii=False, indent=2)}
    for name, code in tools.items():
        fname = str(name).replace("\\", "/").split("/")[-1]
        if not fname.endswith(".py"):
            fname += ".py"
        files[f"tools/{fname}"] = str(code)
    for tool in (manifest.get("tools") or []):
        if isinstance(tool, dict) and tool.get("name"):
            files.setdefault(f"tools/{tool['name']}.py", "import json\n\n\n"
                             "def handle(ctx, args):\n"
                             "    return json.dumps({\"ok\": False, "
                             "\"error\": \"not_implemented\"}, ensure_ascii=False)\n")
    return files


def generate_files(settings, need: str, plan: dict) -> dict:
    existing = collect_existing(settings)
    text = call_model(settings, prompts.CODE_SYSTEM,
                      prompts.code_prompt(need, plan, existing["tools"]))
    return files_from_payload(parse_json(text))


def repair_files(settings, files: dict, issues: list) -> dict:
    plain = to_plain(issues)[:12]
    technical = [{"code": i.get("code"), "detail": str(i.get("detail"))[:200]}
                 for i in issues if i.get("detail")][:12]
    text = call_model(settings, prompts.REPAIR_SYSTEM,
                      prompts.repair_prompt(files, plain + technical))
    return files_from_payload(parse_json(text))


def dry_run(files: dict, plan: dict, timeout: int = 12) -> list:
    """在真沙箱里跑一遍：动作全部拒绝，只验证"能跑、返回 JSON"。"""
    issues = []
    tmp = Path(tempfile.mkdtemp(prefix="ws_dry_"))
    try:
        for rel, content in files.items():
            path = tmp / str(rel).replace("\\", "/")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(str(content), encoding="utf-8")
        ctx = ToolContext(
            permissions={"send_message", "group_admin", "timer", "memory",
                         "network", "media"},
            platform="qq_official", scene="group", user_id="0", group_id="0",
            nickname="测试", is_superuser=True)

        async def host(action, params, ctx_):
            return {"ok": False, "error": "dry_run", "action": action}

        examples = {}
        for tool in (plan.get("tools") or []):
            if isinstance(tool, dict) and tool.get("name"):
                examples[str(tool["name"])] = tool.get("example_args") or {}
        names = [t.get("name") for t in (plan.get("tools") or [])
                 if isinstance(t, dict) and t.get("name")]
        if not names:
            names = [p.stem for p in (tmp / "tools").glob("*.py")]
        for name in names:
            args = examples.get(str(name)) or {}

            async def _one():
                return await run_tool(tmp, str(name), args, ctx, host,
                                      timeout=timeout)
            try:
                out = asyncio.run(_one())
            except Exception as exc:  # noqa: BLE001
                issues.append({"level": "error", "code": "dry_run_failed",
                               "plain": f"工具 {name} 试跑报错（跑不起来）。",
                               "detail": str(exc)[:300]})
                continue
            try:
                data = json.loads(out)
            except Exception:  # noqa: BLE001
                issues.append({"level": "error", "code": "dry_run_bad_json",
                               "plain": f"工具 {name} 没有返回合法 JSON。",
                               "detail": str(out)[:200]})
                continue
            if not isinstance(data, dict) or "ok" not in data:
                issues.append({"level": "error", "code": "dry_run_no_ok",
                               "plain": f"工具 {name} 的返回值缺少 ok 字段。",
                               "detail": str(data)[:200]})
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return issues


def build(settings, need: str, plan: dict | None = None, channels: list | None = None,
          on_log=None, max_repairs: int = MAX_REPAIRS,
          do_dry_run: bool = True) -> dict:
    """跑完整条流水线（不安装）；返回 {"ok", "plan", "files", "issues", ...}。"""
    log = on_log or (lambda msg: None)
    ok, why = ws_config.is_ready(settings)
    if not ok:
        raise WorkshopError(why)
    channels = list(channels or [])
    if plan is None:
        log("正在让 AI 出方案…")
        plan = make_plan(settings, need, channels)
    log(f"方案：{plan.get('name')} · {plan.get('what') or ''}")
    log("正在生成插件代码…")
    files = generate_files(settings, need, plan)
    issues = []
    attempts = 0
    while attempts <= max_repairs:
        existing = collect_existing(settings)
        issues = validate_files(files, set(existing["tools"]))
        if not errors(issues):
            break
        attempts += 1
        if attempts > max_repairs:
            break
        log(f"自动检查发现 {len(errors(issues))} 个问题，让 AI 改第 {attempts} 遍…")
        try:
            files = repair_files(settings, files, errors(issues))
        except WorkshopError as exc:
            raise WorkshopError("AI 重写失败：" + exc.plain, exc.detail) from exc
    if errors(issues):
        manifest = {}
        try:
            manifest = json.loads(files.get("manifest.json") or "{}")
        except Exception:  # noqa: BLE001
            manifest = {}
        return {"ok": False, "plan": plan, "files": files, "issues": issues,
                "attempts": attempts, "report": plain_report(manifest)
                if manifest else {}, "need": need}
    if do_dry_run:
        log("正在沙箱里试跑…")
        dry = dry_run(files, plan)
        issues = issues + dry
        if errors(dry) and attempts < max_repairs:
            attempts += 1
            log("试跑没过，让 AI 再改一遍…")
            files = repair_files(settings, files, errors(dry))
            existing = collect_existing(settings)
            issues = validate_files(files, set(existing["tools"])) + dry_run(files, plan)
    try:
        manifest = json.loads(files.get("manifest.json") or "{}")
    except Exception:  # noqa: BLE001
        manifest = {}
    return {
        "ok": not errors(issues),
        "plan": plan,
        "files": files,
        "issues": issues,
        "attempts": attempts,
        "report": plain_report(manifest) if manifest else {},
        "need": need,
        "model": ws_config.resolved(settings).get("model") or "",
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
