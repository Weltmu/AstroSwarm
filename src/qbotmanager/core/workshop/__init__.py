# -*- coding: utf-8 -*-
"""AI 插件工坊内核：用户说需求 → AI 生成插件 → 检查 → 沙箱试跑 → 一键安装。

桌面端「插件工坊」页和 Linux 无头端控制台共用这一套后台能力：
- 生成模型独立配置、强制强模型（config.py）；
- 两段式生成 + 自动重写 + 沙箱干跑（generator.py）；
- 静态校验：结构/语法/危险调用/权限一致/通道一致/查重（validator.py）；
- 版本历史、一键回滚、一键卸载（installer.py）。
- 分享与投稿：导出 / 导入 zip、上传官网等站长审核（publisher.py）；
- 运行期自修复：真实报错回灌给模型改一版（repair.py）。
生成的插件一律 ``sandbox: true``，只能在沙箱子进程里跑（core/agent/sandbox.py）。
"""
from . import (  # noqa: F401
    config,
    generator,
    installer,
    prompts,
    publisher,
    repair,
    validator,
)

__all__ = ["config", "generator", "installer", "prompts", "validator",
           "publisher", "repair",
           "active_channels", "status", "build", "install", "generated",
           "history", "rollback", "uninstall", "collect_existing",
           "export_zip", "import_zip", "upload", "submissions", "withdraw_submission",
           "runtime_errors", "fix_from_errors"]

_CHANNEL_MAP = {
    "qq": ("qq_official", "qq"),
    "wechat": ("wechat_ilink",),
    "feishu": ("feishu",),
    "telegram": ("telegram",),
}


def active_channels(settings) -> list:
    """当前部署实际开的通道（喂给提示词，避免生成用不上的插件）。"""
    platforms = getattr(settings, "ai_platforms", None) or {}
    official = str(getattr(settings, "qq_channel", "") or "") == "official"
    out = []
    for key, adapters in _CHANNEL_MAP.items():
        if not platforms.get(key, True):
            continue
        if key == "qq":
            out.append("qq_official" if official else "qq")
        else:
            out.append(adapters[0])
    return out


def status(settings) -> dict:
    """工坊状态（给界面显示）：能不能生成 / 用哪家模型 / 提示语。"""
    cfg = config.resolved(settings)
    ready, why = config.is_ready(settings)
    return {
        "ready": ready,
        "why": why,
        "provider": cfg.get("provider") or "",
        "provider_name": cfg.get("provider_name") or "",
        "model": cfg.get("model") or "",
        "api_key_masked": config.mask_key(cfg.get("api_key") or ""),
        "providers": [dict(p) for p in config.WORKSHOP_PROVIDERS],
        "hint": config.AGENT_CAPABLE_HINT,
    }


def collect_existing(settings) -> dict:
    return generator.collect_existing(settings)


def build(settings, need: str, plan=None, channels=None, on_log=None,
          max_repairs: int = generator.MAX_REPAIRS, do_dry_run: bool = True) -> dict:
    """跑完整条流水线，返回 {"ok", "plan", "files", "issues", "report", ...}。"""
    return generator.build(settings, need, plan=plan, channels=channels,
                           on_log=on_log, max_repairs=max_repairs,
                           do_dry_run=do_dry_run)


def install(settings, built: dict) -> dict:
    """把 build 的结果装进 <机器人根>/tool_packs（自动留旧版本）。"""
    plan = built.get("plan") or {}
    manifest = {}
    try:
        import json as _json

        manifest = _json.loads((built.get("files") or {}).get("manifest.json") or "{}")
    except Exception:  # noqa: BLE001
        manifest = {}
    pid = installer.unique_id(settings, str(manifest.get("id") or plan.get("id") or "ai_pack"))
    files = dict(built.get("files") or {})
    if pid != str(manifest.get("id") or ""):
        manifest["id"] = pid
        files["manifest.json"] = __import__("json").dumps(
            manifest, ensure_ascii=False, indent=2)
    meta = {
        "name": manifest.get("name") or plan.get("name") or pid,
        "model": built.get("model") or "",
        "need": str(built.get("need") or "")[:500],
        "plan": plan,
        "attempts": built.get("attempts", 0),
    }
    return installer.install(settings, pid, files, meta)


def generated(settings) -> list:
    return installer.generated(settings)


def history(settings, pid: str) -> list:
    return installer.history(settings, pid)


def rollback(settings, pid: str) -> dict:
    return installer.rollback(settings, pid)


def uninstall(settings, pid: str) -> dict:
    return installer.uninstall(settings, pid)


# ---- 分享 / 投稿（M5）----

def export_zip(settings, pid: str) -> dict:
    """把装好的插件打包成 zip（发给别人 / 自己留底）。"""
    return publisher.export_zip(settings, pid)


def import_zip(settings, zip_path, on_log=None) -> dict:
    """导入一个插件包：先过完整检查（含沙箱试跑），不合格不装。"""
    return publisher.import_zip(settings, zip_path, on_log=on_log)


def upload(settings, pid: str, note: str = "", on_log=None) -> dict:
    """传给官网等站长审核（要有星群账号登录）。"""
    return publisher.upload(settings, pid, note=note, on_log=on_log)


def submissions() -> dict:
    return publisher.submissions()


def withdraw_submission(submission_id: int) -> dict:
    return publisher.withdraw(submission_id)


# ---- 运行期自修复（M3）----

def runtime_errors(settings) -> list:
    """按插件汇总的待修运行报错。"""
    return repair.pending(settings)


def fix_from_errors(settings, pid: str, on_log=None) -> dict:
    """按真实报错让 AI 改一版（返回结果，交给 install() 安装）。"""
    return repair.fix(settings, pid, on_log=on_log)
