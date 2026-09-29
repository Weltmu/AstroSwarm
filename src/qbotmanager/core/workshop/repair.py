# -*- coding: utf-8 -*-
"""插件工坊 · 运行期自修复（M3）。

前两步（静态检查 + 沙箱干跑）只能挡住"跑不起来"的插件；真实的群聊场景里还会遇到
参数不对、接口改版、边界数据这类只有跑过才知道的问题。这里的回路是：

    插件在真实使用中报错 → 记一条（哪个插件、哪个工具、完整报错）
    → 用户在工坊点「让 AI 修一版」 → 把报错喂回生成模型
    → 改完仍然走"静态检查 + 沙箱干跑" → 全绿才让用户点安装（自动留旧版本，可回滚）

错误记录写在 `<机器人根>/workshop/runtime_errors.json`，最多留 40 条。
"""
import json
import time
from pathlib import Path

from . import generator, installer, publisher, validator

MAX_ERRORS = 40
MAX_ISSUES_TO_MODEL = 3


class RepairError(RuntimeError):
    """修复失败（大白话说明）。"""


def errors_file(settings) -> Path:
    return installer.workshop_root(settings) / "runtime_errors.json"


def _load(path: Path) -> list:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return []
    return data if isinstance(data, list) else []


def _save(path: Path, items: list) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(items[-MAX_ERRORS:], ensure_ascii=False, indent=2),
                        encoding="utf-8")
    except Exception:  # noqa: BLE001 —— 记不下来也不能影响机器人本体
        pass


def record(settings, pid: str, tool: str, error: str) -> None:
    """记一条运行期报错。"""
    path = errors_file(settings)
    items = _load(path)
    items.append({
        "id": str(pid or ""),
        "tool": str(tool or ""),
        "error": str(error or "")[:2000],
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "ts": time.time(),
        "fixed": False,
    })
    _save(path, items)


def record_for_pack(pack_dir, tool: str, error: str) -> bool:
    """从插件目录反推出机器人根并记一条（给 AgentRuntime 用）。

    只记工坊自己生成的插件：没有 workshop/<id>.json 的包（官方包 / 手动装的包）
    记了也没法让 AI 修，白白写文件。
    """
    try:
        pack_dir = Path(pack_dir)
        root = pack_dir.parent.parent
        meta = root / "workshop" / f"{pack_dir.name}.json"
        if not meta.is_file():
            return False
        try:
            info = json.loads(meta.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return False
        if str(info.get("source") or "") != "workshop":
            return False

        class _S:
            pass

        stub = _S()
        stub.root = str(root)
        record(stub, pack_dir.name, tool, error)
        return True
    except Exception:  # noqa: BLE001
        return False


def errors(settings, pid: str = "", only_pending: bool = True) -> list:
    items = _load(errors_file(settings))
    if pid:
        items = [i for i in items if str(i.get("id")) == str(pid)]
    if only_pending:
        items = [i for i in items if not i.get("fixed")]
    return items[-MAX_ERRORS:]


def pending(settings) -> list:
    """按插件汇总的待修报错（界面用）。"""
    grouped = {}
    for item in errors(settings, only_pending=True):
        pid = str(item.get("id") or "")
        row = grouped.setdefault(pid, {"id": pid, "count": 0, "tool": "",
                                       "error": "", "time": ""})
        row["count"] += 1
        row["tool"] = str(item.get("tool") or row["tool"])
        row["error"] = str(item.get("error") or "")[:300]
        row["time"] = str(item.get("time") or "")
    out = []
    for pid, row in grouped.items():
        try:
            manifest = json.loads(
                (installer.packs_root(settings) / pid / "manifest.json").read_text(encoding="utf-8"))
            row["name"] = manifest.get("name") or pid
        except Exception:  # noqa: BLE001
            row["name"] = pid
        out.append(row)
    return sorted(out, key=lambda r: r.get("time") or "", reverse=True)


def mark_fixed(settings, pid: str) -> None:
    path = errors_file(settings)
    items = _load(path)
    touched = False
    for item in items:
        if str(item.get("id")) == str(pid) and not item.get("fixed"):
            item["fixed"] = True
            touched = True
    if touched:
        _save(path, items)


def clear(settings, pid: str = "") -> None:
    """清报错记录（pid 为空 = 全清）。"""
    if not pid:
        _save(errors_file(settings), [])
        return
    _save(errors_file(settings),
          [i for i in _load(errors_file(settings)) if str(i.get("id")) != str(pid)])


def _issues_for_model(items: list) -> list:
    out = []
    for item in items[-MAX_ISSUES_TO_MODEL:]:
        out.append({
            "level": "error",
            "code": "runtime_error",
            "plain": f"工具 {item.get('tool') or '?'} 在真实使用时报了错（{item.get('time') or ''}）。",
            "detail": (str(item.get("error") or ""))[:1200],
        })
    return out


def fix(settings, pid: str, on_log=None) -> dict:
    """按真实报错让 AI 改一版；返回和 workshop.build 同形状的结果（不自动安装）。"""
    log = on_log or (lambda msg: None)
    pid = str(pid or "").strip()
    if not pid:
        raise RepairError("先选一个插件。")
    items = errors(settings, pid, only_pending=True)
    if not items:
        raise RepairError("这个插件最近没有新的报错，不用修。")
    files = publisher.files_of(settings, pid)
    if not files.get("manifest.json"):
        raise RepairError("找不到这个插件的文件（可能已经被卸掉了）。")
    meta = {}
    try:
        meta = json.loads(installer.meta_file(settings, pid).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        meta = {}
    plan = meta.get("plan") if isinstance(meta.get("plan"), dict) else {}
    plan = dict(plan or {})
    plan.setdefault("id", pid)
    plan.setdefault("name", meta.get("name") or pid)
    need = str(meta.get("need") or f"修好插件 {pid} 在真实使用中报的错")
    log(f"正在把 {len(items)} 条真实报错交给 AI 改一版…")
    repaired = generator.repair_files(settings, files, _issues_for_model(items))
    # 模型有时会把 id 改名 —— 修的是同一个插件，id 必须锁死
    try:
        manifest = json.loads(repaired.get("manifest.json") or "{}")
        manifest["id"] = pid
        manifest.setdefault("version", "")
        repaired["manifest.json"] = json.dumps(manifest, ensure_ascii=False, indent=2)
    except Exception:  # noqa: BLE001
        pass
    issues = []
    attempts = 1
    free_tools = publisher.existing_tools_without(settings, pid)
    for step in range(2):
        issues = validator.validate_files(repaired, free_tools)
        if not validator.errors(issues):
            break
        attempts += 1
        log(f"检查又发现 {len(validator.errors(issues))} 个问题，再让 AI 改一遍…")
        repaired = generator.repair_files(settings, repaired,
                                          validator.errors(issues))
        try:
            manifest = json.loads(repaired.get("manifest.json") or "{}")
            manifest["id"] = pid
            repaired["manifest.json"] = json.dumps(manifest, ensure_ascii=False, indent=2)
        except Exception:  # noqa: BLE001
            pass
    if not validator.errors(issues):
        log("正在沙箱里试跑改好的版本…")
        dry = generator.dry_run(repaired, plan)
        issues = list(issues) + list(dry)
    try:
        manifest = json.loads(repaired.get("manifest.json") or "{}")
    except Exception:  # noqa: BLE001
        manifest = {}
    return {
        "ok": not validator.errors(issues),
        "plan": plan,
        "files": repaired,
        "issues": issues,
        "attempts": attempts,
        "report": validator.plain_report(manifest) if manifest else {},
        "need": need,
        "model": generator.ws_config.resolved(settings).get("model") or "",
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        "runtime_errors": [i.get("error") for i in items[-MAX_ISSUES_TO_MODEL:]],
    }
