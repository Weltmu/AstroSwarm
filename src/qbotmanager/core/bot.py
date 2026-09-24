# -*- coding: utf-8 -*-
"""NoneBot 机器人项目骨架：生成 / 插件列表读写 / 启停。"""
import json
import logging
import re
import shutil
from pathlib import Path

from ..constants import AI_PLUGIN_DEPS
from . import license as lic_mod
from .process import start_process, stop_process_tree
from .process import run_capture
from .python_runtime import install_with_fallback

logger = logging.getLogger("qbotmanager")

PYPROJECT_TPL = '''[project]
name = "qbot"
version = "1.1.0"
description = "由 AstroSwarm 星群管理的多平台机器人"
requires-python = ">=3.10"
dependencies = []

[tool.nonebot]
plugin_dirs = ["src/plugins"]
adapters = [
{adapters}
]
'''

RUN_PY_TPL = '''import sys
from pathlib import Path

# 确保项目根目录在 sys.path 中：
# 内置 Python 的 _pth 机制不会自动加入脚本目录，缺少此行会导致
# 使用 src.plugins.xxx 绝对导入的插件报 "No module named 'src'"
sys.path.insert(0, str(Path(__file__).resolve().parent))

import nonebot

nonebot.init()

driver = nonebot.get_driver()
{adapter_imports}
{adapter_registers}

nonebot.load_from_toml("pyproject.toml")

if __name__ == "__main__":
    nonebot.run()
'''


def _onebot_active(settings) -> bool:
    """第三方 OneBot 通道是否启用。

    反向 WS 模式不依赖正向端口即可生效（协议端主动连回星群）；
    正向模式要求协议端端口已填写。
    """
    return getattr(settings, "qq_channel", "official") == "onebot" and (
        str(getattr(settings, "qq_onebot_mode", "") or "reverse").lower() == "reverse"
        or int(getattr(settings, "qq_onebot_port", 0) or 0) > 0
    )


def _enabled_qq_adapters(settings) -> list:
    """按设置返回要注册的 QQ 适配器列表 [(显示名, 模块名), ...]。

    QQ 支持两种通道：
    - official：官方机器人（nonebot-adapter-qq）；
    - onebot：第三方 OneBot V11 协议端（nonebot-adapter-onebot，
      AstroSwarm 不内置/不分发协议端，只做标准正向 WS 对接）。
    dsh 通道启用时 QQ 消息由 dsh（DeepSeek Harness）接管，
    NoneBot 不再注册 QQ 适配器，避免同一 AppID 双网关连接冲突。
    李清菡智能体启用时由李清菡接管 QQ（与 dsh 互斥，优先李清菡）。
    """
    if _agent_profile_enabled(settings):
        if (
            getattr(settings, "qq_official_appid", "")
            and getattr(settings, "qq_official_token", "")
            and getattr(settings, "qq_official_secret", "")
        ):
            return [("QQ", "nonebot.adapters.qq")]
        # 档案开着但没填官方凭据：以前这里直接 return []，机器人一个适配器都不加载、
        # 永远收不到消息（用户看到的就是「启动成功但完全没有反应」）。
        # 退回第三方 OneBot 通道，都没有才返回空。
        if _onebot_active(settings):
            return [("QQ", "nonebot.adapters.onebot.v11")]
        return []
    if getattr(settings, "dsh_enabled", False):
        return []
    if _onebot_active(settings):
        return [("QQ", "nonebot.adapters.onebot.v11")]
    if (
        getattr(settings, "qq_channel", "official") != "onebot"
        and
        getattr(settings, "qq_official_appid", "")
        and getattr(settings, "qq_official_token", "")
        and getattr(settings, "qq_official_secret", "")
    ):
        return [("QQ", "nonebot.adapters.qq")]
    return []


def _adapters_toml(settings) -> str:
    """生成 pyproject.toml 的 adapters 块内容。"""
    lines = []
    for name, module in _enabled_qq_adapters(settings):
        lines.append(f'    {{ name = "{name}", module_name = "{module}" }},')
    return "\n".join(lines)


def _run_py_text(settings) -> str:
    """生成 run.py：按设置注册 QQ 适配器（官方或 OneBot；微信 iLink 由插件目录自动发现）。"""
    adapters = _enabled_qq_adapters(settings)
    imports = "\n".join(
        f"from {mod} import Adapter as Adapter{i}"
        for i, (_, mod) in enumerate(adapters)
    )
    registers = "\n".join(
        f"driver.register_adapter(Adapter{i})" for i in range(len(adapters))
    )
    return RUN_PY_TPL.format(adapter_imports=imports, adapter_registers=registers)

def ensure_ilink_adapter(settings) -> None:
    """把内置的 nonebot_adapter_ilink（微信 ClawBot 适配器）同步到机器人插件目录。

    NoneBot 的 plugin_dirs 会自动发现该目录并注册适配器，无需额外配置。
    """
    try:
        bundled = Path(__file__).resolve().parent.parent / "assets" / "plugins" / "nonebot_adapter_ilink"
        if not bundled.is_dir():
            return
        target = settings.plugins_dir / "nonebot_adapter_ilink"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(bundled, target, dirs_exist_ok=True)
    except OSError as e:
        logger.warning("同步 ilink 适配器失败（微信通道将不可用）: %s", e)


def apply_wechat_gate(settings, full: bool = True) -> bool:
    """按功能闸门同步微信 iLink 适配器。

    full=True：正式授权，恢复微信适配器；
    full=False：试用/未激活，移除微信适配器（QQ 通道不受影响）。
    返回微信通道是否可用。
    """
    target = settings.plugins_dir / "nonebot_adapter_ilink"
    if full:
        try:
            ensure_ilink_adapter(settings)
        except OSError as e:
            logger.warning("同步微信适配器失败: %s", e)
        return True
    try:
        if target.exists():
            shutil.rmtree(target)
    except OSError as e:
        logger.warning("移除微信适配器失败: %s", e)
    return False


def ensure_ai_plugin(settings) -> None:
    """把内置 AI 对话插件（assets/plugins/ai）同步到机器人插件目录（不可卸载）。"""
    try:
        bundled = Path(__file__).resolve().parent.parent / "assets" / "plugins" / "ai"
        if not bundled.is_dir():
            return
        target = settings.plugins_dir / "ai"
        target.parent.mkdir(parents=True, exist_ok=True)
        # 不要在客户插件目录里留 .pyc / __pycache__（裸 .pyc 会让 Python 版本一换就炸）
        shutil.copytree(
            bundled, target, dirs_exist_ok=True,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"))
        for pyc in list(target.rglob("__pycache__")):
            shutil.rmtree(pyc, ignore_errors=True)
    except OSError as e:
        logger.warning("同步内置 AI 插件失败: %s", e)


def ensure_agent_runtime(settings, log=None) -> None:
    """把 AgentRuntime 子包同步到机器人目录（bot/qbotmanager）。

    机器人进程是独立 venv，装不进桌面主程序源码；AI 插件里
    `from qbotmanager.core.agent.runtime import get_runtime` 依赖
    这个子包（纯标准库，自包含），随启动自愈同步，工具包才能被加载。
    """
    try:
        import sys as _sys
        if getattr(_sys, "frozen", False) and getattr(_sys, "_MEIPASS", ""):
            # 打包版：qbotmanager 源码在 PYZ 里不在磁盘，改用 appr/ 数据目录的副本
            src_pkg = Path(_sys._MEIPASS) / "appr" / "qbotmanager"
        else:
            src_pkg = Path(__file__).resolve().parent.parent  # src/qbotmanager
        target = settings.bot_dir / "qbotmanager"
        (target / "core" / "agent").mkdir(parents=True, exist_ok=True)
        for rel in ("__init__.py", "core/__init__.py"):
            src = src_pkg / rel
            if src.exists():
                (target / rel).write_text(
                    src.read_text(encoding="utf-8"), encoding="utf-8")
        kb_src = src_pkg / "core" / "knowledge_base.py"
        if kb_src.exists():
            (target / "core" / "knowledge_base.py").write_text(
                kb_src.read_text(encoding="utf-8"), encoding="utf-8")
        agent_src = src_pkg / "core" / "agent"
        agent_dst = target / "core" / "agent"
        if agent_src.is_dir():
            shutil.copytree(agent_src, agent_dst, dirs_exist_ok=True)
        for pyc in list(agent_dst.rglob("__pycache__")):
            shutil.rmtree(pyc, ignore_errors=True)
    except OSError as e:
        logger.warning("同步 AgentRuntime 子包失败（工具包将不可用）: %s", e)
        if log:
            log("同步 AgentRuntime 子包失败: " + str(e))


def ensure_bridge_client(settings) -> None:
    """把微信桥客户端插件（qbm-bridge-client）同步到机器人插件目录（不可卸载）。"""
    try:
        bundled = Path(__file__).resolve().parent.parent / "assets" / "plugins" / "qbm_bridge_client"
        if not bundled.is_dir():
            return
        target = settings.plugins_dir / "qbm_bridge_client"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(bundled, target, dirs_exist_ok=True)
    except OSError as e:
        logger.warning("同步微信桥客户端失败: %s", e)


def ensure_liqinghan_plugin(settings) -> None:
    """把李清菡智能体插件（assets/plugins/liqinghan）同步到机器人插件目录。"""
    try:
        bundled = Path(__file__).resolve().parent.parent / "assets" / "plugins" / "liqinghan"
        if not bundled.is_dir():
            return
        target = settings.plugins_dir / "liqinghan"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(bundled, target, dirs_exist_ok=True)
    except OSError as e:
        logger.warning("同步李清菡智能体插件失败: %s", e)


def ensure_ai_deps(settings, log=None) -> None:
    """确保内置 AI 插件依赖（openai / mcp）已安装；缺失时自动补装（老部署自愈）。"""
    py = settings.python_exe
    if not py.exists():
        return
    try:
        rc, _ = run_capture([str(py), "-m", "pip", "show", "openai", "mcp", "PyJWT", "cryptography"], timeout=60)
    except Exception:  # noqa: BLE001
        rc = 1
    if rc == 0:
        return
    if log:
        log("内置 AI 插件依赖缺失，正在自动安装（openai / mcp）...")
    try:
        install_with_fallback(settings, list(AI_PLUGIN_DEPS), log=log)
        if log:
            log("AI 插件依赖安装完成")
    except Exception as e:  # noqa: BLE001
        logger.warning("AI 插件依赖安装失败: %s", e)
        if log:
            log("AI 插件依赖安装失败: " + str(e))


def ensure_official_qq_deps(settings, log=None) -> None:
    """确保官方 QQ 适配器（nonebot-adapter-qq）已安装；缺失时自动补装。"""
    py = settings.python_exe
    if not py.exists():
        return
    try:
        rc, _ = run_capture([str(py), "-m", "pip", "show", "nonebot-adapter-qq"], timeout=60)
    except Exception:  # noqa: BLE001
        rc = 1
    if rc == 0:
        return
    if log:
        log("官方 QQ 适配器缺失，正在自动安装（nonebot-adapter-qq）...")
    try:
        install_with_fallback(settings, ["nonebot-adapter-qq"], log=log)
        if log:
            log("官方 QQ 适配器安装完成")
    except Exception as e:  # noqa: BLE001
        logger.warning("官方 QQ 适配器安装失败: %s", e)
        if log:
            log("官方 QQ 适配器安装失败: " + str(e))


def ensure_onebot_deps(settings, log=None) -> None:
    """确保 OneBot V11 适配器（nonebot-adapter-onebot）已安装；缺失时自动补装。"""
    py = settings.python_exe
    if not py.exists():
        return
    try:
        rc, _ = run_capture([str(py), "-m", "pip", "show", "nonebot-adapter-onebot"], timeout=60)
    except Exception:  # noqa: BLE001
        rc = 1
    if rc == 0:
        return
    if log:
        log("OneBot 适配器缺失，正在自动安装（nonebot-adapter-onebot）...")
    try:
        install_with_fallback(settings, ["nonebot-adapter-onebot"], log=log)
        if log:
            log("OneBot 适配器安装完成")
    except Exception as e:  # noqa: BLE001
        logger.warning("OneBot 适配器安装失败: %s", e)
        if log:
            log("OneBot 适配器安装失败: " + str(e))


def build_env_text(settings) -> str:
    su = json.dumps(settings.superusers, ensure_ascii=False)
    reverse_onebot = _onebot_active(settings) and str(
        getattr(settings, "qq_onebot_mode", "") or "reverse"
    ).lower() == "reverse"
    listen_host = "127.0.0.1"
    if reverse_onebot:
        listen_host = str(
            getattr(settings, "qq_onebot_listen_host", "") or "127.0.0.1"
        ).strip() or "127.0.0.1"
    lines = [
        "ENVIRONMENT=prod\n"
        f"HOST={listen_host}\n"
        f"PORT={settings.nonebot_port}\n"
        "DRIVER=~fastapi+~httpx+~websockets\n"
        f"SUPERUSERS={su}\n"
        "COMMAND_START=[\"\"]\n"
        "LOG_LEVEL=INFO\n"
        "LOCALSTORE_USE_CWD=true\n"
    ]
    if (
        getattr(settings, "qq_channel", "official") != "onebot"
        and getattr(settings, "qq_official_appid", "")
        and getattr(settings, "qq_official_token", "")
        and getattr(settings, "qq_official_secret", "")
    ):
        lines.append(
            "QQ_IS_SANDBOX="
            + ("true" if getattr(settings, "qq_official_sandbox", False) else "false")
            + "\n"
        )
        bots = [{
            "id": settings.qq_official_appid,
            "token": settings.qq_official_token,
            "secret": settings.qq_official_secret,
            "intent": {"c2c_group_at_messages": True},
        }]
        lines.append(
            "QQ_BOTS=" + json.dumps(bots, ensure_ascii=False, separators=(",", ":")) + "\n"
        )
    if _onebot_active(settings):
        token = str(getattr(settings, "qq_onebot_token", "") or "").strip()
        if reverse_onebot:
            # 反向 WS：协议端主动连回星群，NoneBot 只监听，无需写 ONEBOT_WS_URLS
            if token:
                lines.append(f"ONEBOT_ACCESS_TOKEN={token}\n")
        else:
            host = str(getattr(settings, "qq_onebot_host", "") or "127.0.0.1").strip()
            port = int(getattr(settings, "qq_onebot_port", 0) or 0)
            path = str(getattr(settings, "qq_onebot_path", "") or "/onebot/v11/ws").strip()
            if not path.startswith("/"):
                path = "/" + path
            url = f"ws://{host}:{port}{path}"
            lines.append(
                "ONEBOT_WS_URLS=" + json.dumps([url], ensure_ascii=False, separators=(",", ":")) + "\n"
            )
            if token:
                lines.append(f"ONEBOT_ACCESS_TOKEN={token}\n")
    if _agent_profile_enabled(settings):
        from . import ai_config
        llm = ai_config.current_config(settings)
        lines.append("QBM_AGENT_PROFILE_ENABLED=1\n")
        lines.append(f"QBM_AGENT_DATA_DIR={str(settings.root / 'data' / 'liqinghan').replace(chr(92), '/')}\n")
        lines.append(f"QBM_AGENT_LOG_FILE={str(settings.logs_dir / 'liqinghan.log').replace(chr(92), '/')}\n")
        owner = str(getattr(settings, "agent_owner_openid", "") or "").strip()
        lines.append(f"QBM_AGENT_OWNER_QQ={owner}\n")
        words = list(getattr(settings, "agent_wake_words", []) or [])
        if words:
            lines.append("QBM_AGENT_ADDRESS_WORDS=" + ",".join(words) + "\n")
        if str(llm.get("api_url") or ""):
            lines.append(f"DEEPSEEK_API_URL={str(llm['api_url']).rstrip('/')}\n")
        if str(llm.get("api_key") or ""):
            lines.append(f"DEEPSEEK_API_KEY={llm['api_key']}\n")
        if str(llm.get("model") or ""):
            lines.append(f"DEEPSEEK_MODEL={llm['model']}\n")
        if str(getattr(settings, "vision_api_key", "") or ""):
            lines.append(f"SILICONFLOW_API_KEY={settings.vision_api_key}\n")
        if str(getattr(settings, "vision_api_url", "") or ""):
            lines.append(f"VISION_API_URL={str(settings.vision_api_url).rstrip('/')}\n")
        if str(getattr(settings, "vision_model", "") or ""):
            lines.append(f"VISION_MODEL={settings.vision_model}\n")
    return "".join(lines)


def _agent_profile_enabled(settings) -> bool:
    """李清菡档案启用（其他档案不注入李清菡插件配置）。"""
    return bool(getattr(settings, "agent_profile_enabled", False)) and (
        getattr(settings, "agent_profile_id", "") == "liqinghan")


def sync_qq_adapters(settings, log=None) -> None:
    """按当前设置重写 pyproject.toml 的 adapters 列表与 run.py（保留插件列表）。"""
    if not (settings.bot_dir / "pyproject.toml").exists():
        scaffold_bot(settings)
        return
    pf = settings.bot_dir / "pyproject.toml"
    text = pf.read_text(encoding="utf-8")
    new_block = "adapters = [\n" + _adapters_toml(settings) + "\n]\n"
    marker = "[tool.nonebot]"
    idx = text.find(marker)
    if idx == -1:
        text += "\n[tool.nonebot]\n" + new_block
    else:
        rest = text[idx + len(marker):]
        am = re.search(r"adapters\s*=\s*\[(.*?)\]", rest, re.S)
        if am:
            text = text[:idx + len(marker) + am.start()] + new_block + text[idx + len(marker) + am.end():]
        else:
            insert_at = idx + len(marker) + 1
            text = text[:insert_at] + "\n" + new_block + text[insert_at:]
    pf.write_text(text, encoding="utf-8")
    (settings.bot_dir / "run.py").write_text(_run_py_text(settings), encoding="utf-8")
    if log:
        log("已同步 QQ 适配器配置")


def scaffold_bot(settings, log=None) -> None:
    """生成机器人项目骨架（pyproject.toml / run.py / .env / src/plugins）。"""
    if log:
        log("生成机器人项目骨架 ...")
    settings.bot_dir.mkdir(parents=True, exist_ok=True)
    settings.plugins_dir.mkdir(parents=True, exist_ok=True)
    (settings.bot_dir / "pyproject.toml").write_text(
        PYPROJECT_TPL.format(adapters=_adapters_toml(settings)), encoding="utf-8"
    )
    (settings.bot_dir / "run.py").write_text(_run_py_text(settings), encoding="utf-8")
    (settings.bot_dir / ".env").write_text(build_env_text(settings), encoding="utf-8")
    (settings.plugins_dir / ".gitkeep").write_text("", encoding="utf-8")
    ensure_agent_runtime(settings, log=log)
    ensure_ilink_adapter(settings)
    ensure_ai_plugin(settings)
    ensure_bridge_client(settings)
    ensure_liqinghan_plugin(settings)


def write_env(settings) -> None:
    settings.bot_dir.mkdir(parents=True, exist_ok=True)
    (settings.bot_dir / ".env").write_text(build_env_text(settings), encoding="utf-8")


def read_plugins(settings) -> list:
    """读取 pyproject.toml 中 [tool.nonebot] 下的 plugins 列表。"""
    pf = settings.bot_dir / "pyproject.toml"
    if not pf.exists():
        return []
    text = pf.read_text(encoding="utf-8")
    m = re.search(r"\[tool\.nonebot\](.*?)(\n\[[^\]]+\]|\Z)", text, re.S)
    if not m:
        return []
    sec = m.group(1)
    pm = re.search(r"plugins\s*=\s*\[(.*?)\]", sec, re.S)
    if not pm:
        return []
    try:
        return json.loads("[" + pm.group(1) + "]")
    except ValueError:
        return []


def write_plugins(settings, plugins: list) -> None:
    """把 pip 安装的商店插件名写入 pyproject.toml 的 plugins 列表。"""
    pf = settings.bot_dir / "pyproject.toml"
    if not pf.exists():
        scaffold_bot(settings)
    text = pf.read_text(encoding="utf-8")
    new_line = "plugins = [" + ", ".join(json.dumps(p, ensure_ascii=False) for p in plugins) + "]\n"
    marker = "[tool.nonebot]"
    idx = text.find(marker)
    if idx == -1:
        text += "\n[tool.nonebot]\n" + new_line
    else:
        rest = text[idx + len(marker):]
        pm = re.search(r"plugins\s*=\s*\[(.*?)\]", rest, re.S)
        if pm:
            text = text[:idx + len(marker) + pm.start()] + new_line + text[idx + len(marker) + pm.end():]
        else:
            # 插入到 [tool.nonebot] 节内第一行
            insert_at = idx + len(marker) + 1
            text = text[:insert_at] + "\n" + new_line + text[insert_at:]
    pf.write_text(text, encoding="utf-8")


AI_PLATFORM_KEYS = ("qq", "wechat", "feishu", "telegram")


def ai_platform_env(settings) -> dict:
    """AI 平台开关 → 机器人侧环境变量（AI_PLATFORM_QQ=1/0 ...）。

    平台开关只影响 AI 大脑是否处理该平台的消息，不影响平台适配器本身运行。
    默认全开；旧 settings.json 没有该字段时同样按全开处理。
    """
    platforms = getattr(settings, "ai_platforms", None)
    if not isinstance(platforms, dict):
        platforms = {}
    if getattr(settings, "dsh_enabled", False):
        # 统一大脑开启后：微信由 dsh 桥接管，旧 AI 插件不再处理微信，避免双回复
        platforms = dict(platforms)
        platforms["wechat"] = False
    if _agent_profile_enabled(settings):
        # 李清菡接管 QQ 与微信（微信走 18650 桥），旧 AI 插件全部停用避免双回复
        platforms = dict(platforms)
        platforms["qq"] = False
        platforms["wechat"] = False
    env = {}
    for key in AI_PLATFORM_KEYS:
        env[f"AI_PLATFORM_{key.upper()}"] = "1" if platforms.get(key, True) else "0"
    return env


def build_bot_env(settings) -> dict:
    """构建 NoneBot 进程环境变量（含功能闸门：试用仅 QQ，正式授权解锁微信）。"""
    env = {"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    if not getattr(settings, "ai_enabled", True):
        env["AI_DISABLED"] = "1"
        return env
    env.update(ai_platform_env(settings))
    gate = lic_mod.feature_gate()
    # 微信通道看 member（付费会员档），不是 full（= 解锁全部付费能力包）
    if not gate.get("member", True):
        env["AI_PLATFORM_WECHAT"] = "0"
    return env


def start_bot(settings, on_line=None):
    """启动 NoneBot。返回 Popen。"""
    py = settings.python_exe
    if not py.exists():
        raise RuntimeError("Python 运行时不存在，请先完成部署")
    run_py = settings.bot_dir / "run.py"
    if not run_py.exists():
        raise RuntimeError("机器人项目不完整（缺少 bot/run.py），请重新完成部署")
    # 功能闸门：试用/未激活只允许 QQ 机器人，微信适配器按会员权益同步
    gate = lic_mod.feature_gate()
    apply_wechat_gate(settings, full=bool(gate.get("member", True)))
    ensure_ai_plugin(settings)
    ensure_bridge_client(settings)
    ensure_liqinghan_plugin(settings)
    ensure_agent_runtime(settings, log=on_line)
    # 自愈：按当前设置重新生成适配器列表（QQ 官方 / 微信 iLink），避免填了凭证但没生效
    sync_qq_adapters(settings, log=on_line)
    if _onebot_active(settings):
        ensure_onebot_deps(settings, log=on_line)
    elif getattr(settings, "qq_official_appid", ""):
        ensure_official_qq_deps(settings, log=on_line)
    if getattr(settings, "ai_enabled", True):
        ensure_ai_deps(settings, log=on_line)
    # 自愈：刷新 .env（保证 LOCALSTORE_USE_CWD 等新配置写入旧部署）
    write_env(settings)
    env = build_bot_env(settings)
    # 注入已安装能力包：目录 + 按权益允许加载的包列表（会员到期=冻结不加载）
    try:
        from . import tool_packs as tool_packs_mod
        env.update(tool_packs_mod.pack_env(settings))
    except Exception:  # noqa: BLE001
        pass
    # 注入和风天气工具包配置（项目ID/凭据ID/私钥路径 → QWEATHER_* 环境变量）
    try:
        env.update(tool_packs_mod.qweather_env(settings))
    except Exception:  # noqa: BLE001
        pass
    # 注入本地人设工坊：用户自制人设包（人格 + 工具）
    try:
        from . import persona_workshop as persona_workshop_mod
        env.update(persona_workshop_mod.pack_env(settings))
    except Exception:  # noqa: BLE001
        pass
    # 注入本地知识库目录（AI 内置 knowledge_search 工具检索用）
    try:
        env["ASTROSWARM_KNOWLEDGE_DIR"] = str(
            Path(settings.root) / "knowledge")
    except Exception:  # noqa: BLE001
        pass
    return start_process(
        [str(py), "run.py"], cwd=settings.bot_dir, on_line=on_line,
        env=env,
        log_file=settings.logs_dir / "nonebot.log",
    )


def stop_bot(proc):
    stop_process_tree(proc)
