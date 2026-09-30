# -*- coding: utf-8 -*-
"""dsh（DeepSeek Harness）QQ 群聊 AI 通道：纯官方凭证路径。

只使用 MIT 许可组件：
  - deepseek-ai/deepseek-harness（dsh）
  - tencent-connect/dsh-qqbot（官方插件）
  - tencent-connect/qqbot-nodejs（官方 SDK）

明确不内置、不调用 @tencent-connect/qqbot-connector（UNLICENSED 专有包，
仅扫码绑定流程用到；本通道始终以 AppID/AppSecret 纯凭证启动）。

布局（全部收在安装根目录内，便于迁移/卸载）：
  <root>/dsh/                 dsh 运行时（node_modules、package.json）
  <root>/dsh/home              DSH_HOME（profiles/sessions/credentials）
  <root>/dsh/home/profiles/qqbot  官方插件 profile
  <root>/dsh/workspace         agent 工作目录（工具沙箱根）
"""
import json
import re
import shutil
import threading
import time
import zipfile
from pathlib import Path

from . import ai_config
from .net import download_with_mirrors
from .process import run_capture, run_stream, start_process

MIN_NODE_MAJOR = 22
# 便携版 Node 版本（npmmirror / nodejs.org 均保留历史版本）
NODE_VERSION = "22.23.2"
NODE_MIRROR_PREFIXES = (
    "https://registry.npmmirror.com/-/binary/node/",
    "https://nodejs.org/dist/",
)
BRIDGE_PORT = 18650
# 桥插件版本：改了 assets/dsh_plugins/qbm_bridge 就 +1，
# 让老安装重装一次桥（marker 里存的就是这个值）。
BRIDGE_VERSION = "3"
# 统一大脑 agent preset：QQ 与微信桥共用同一人设
AGENT_PRESET_ID = "astros"
BINDINGS_FILE = "qbm_bindings.json"
DEFAULT_PERSONALITY = (
    "你是星群（AstroSwarm）的 AI 助手，负责跨平台对话与记忆管理。"
    "回答保持简洁直接，情绪随心情波动，回答长短看情况，只给关键信息，不啰嗦。"
)

# dsh base bundle 默认加载的高危工具：群聊大脑一律禁用。
# 1) 本机执行 / 联网：防止陌生人 @ 机器人就让 LLM 在本机跑 shell、读写文件、上网。
# 2) 子代理 / 工作流 / 后台任务：群聊用不到；而且 0.1.7 的 dsh 在这些工具上会抛
#    "Cannot read properties of undefined (reading 'prepare')"，一旦被模型调用，
#    会话日志里就留下一条没有结果的工具调用，之后每轮都被 DeepSeek 适配器拒收
#    （INVALID_REQUEST: tool calls need immediate results）——见 repair_sessions()。
# 3) 会话内助手类工具（skill / todo / goal）：群聊不需要，留着只会扩大踩坑面。
DISABLED_TOOLS = (
    "tool-bash",
    "tool-pwsh",
    "tool-fs",
    "tool-fs-search",
    "tool-web",
    "tool-subagent",
    "tool-subagent-fork",
    "tool-subagent-control",
    "tool-subagent-list-agents",
    "tool-workflow",
    "tool-ralph",
    "tool-jobs",
    "tool-skill",
    "tool-todo",
    "tool-goal",
)

_node_version_cache = {}  # path -> (expire_ts, version)


# ---------- 路径 ----------
def dsh_dir(settings) -> Path:
    return settings.root / "dsh"


def dsh_home(settings) -> Path:
    return dsh_dir(settings) / "home"


def profile_dir(settings) -> Path:
    return dsh_home(settings) / "profiles" / "qqbot"


def workspace_dir(settings) -> Path:
    return dsh_dir(settings) / "workspace"


def node_dir(settings) -> Path:
    return dsh_dir(settings) / "node"


def dsh_js(settings) -> Path:
    return dsh_dir(settings) / "node_modules" / "@deepseek-ai" / "dsh" / "lib" / "bin.js"


def dsh_log(settings) -> Path:
    return settings.logs_dir / "dsh.log"


def patch_file(settings) -> Path:
    return profile_dir(settings) / "cordis.patch.yml"


def settings_yaml_file(settings) -> Path:
    return dsh_home(settings) / "settings.yaml"


def bridge_source_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "assets" / "dsh_plugins" / "qbm_bridge"


def bridge_marker(settings) -> Path:
    return profile_dir(settings) / ".qbm_bridge_installed"


def bridge_installed_dir(settings) -> Path:
    """桥插件的稳定安装源目录。

    打包版里 assets 位于 PyInstaller 的 _MEI 临时目录，进程一退就没了；
    直接 file: 指向它会让 profile 的依赖记住一个死路径。
    """
    return dsh_dir(settings) / "plugins" / "qbm_bridge"


def agent_presets_root(settings) -> Path:
    return dsh_home(settings) / ".agent-presets"


def agent_preset_dir(settings) -> Path:
    return agent_presets_root(settings) / AGENT_PRESET_ID


def bindings_file(settings) -> Path:
    """微信→QQ 会话绑定文件（同一人跨平台共享同一会话/记忆）。"""
    return workspace_dir(settings) / BINDINGS_FILE


# ---------- Node 探测 ----------
def node_exe(settings) -> Path:
    """返回可用的 node.exe 路径；找不到返回空 Path。"""
    override = str(getattr(settings, "dsh_node_exe", "") or "").strip()
    if override:
        p = Path(override)
        if p.exists():
            return p
    found = shutil.which("node")
    if found:
        return Path(found)
    return Path("")


def _npm_cli(node: Path) -> Path:
    """从 node 安装目录推导 npm-cli.js（不依赖 .cmd 外壳）。"""
    cand = node.parent / "node_modules" / "npm" / "bin" / "npm-cli.js"
    if cand.exists():
        return cand
    for p in (
        Path(r"C:\Program Files\nodejs\node_modules\npm\bin\npm-cli.js"),
        Path(r"C:\Program Files (x86)\nodejs\node_modules\npm\bin\npm-cli.js"),
    ):
        if p.exists():
            return p
    return Path("")


def node_version(node: Path) -> str:
    if not node or not node.exists():
        return ""
    key = str(node)
    cached = _node_version_cache.get(key)
    if cached and cached[0] > time.time():
        return cached[1]
    ver = ""
    try:
        rc, out = run_capture([str(node), "--version"], timeout=15)
        ver = out.strip() if rc == 0 else ""
    except Exception:  # noqa: BLE001
        ver = ""
    _node_version_cache[key] = (time.time() + 60, ver)
    return ver


def node_ok(node: Path) -> bool:
    ver = node_version(node)
    if not ver.startswith("v"):
        return False
    try:
        return int(ver[1:].split(".")[0]) >= MIN_NODE_MAJOR
    except ValueError:
        return False


def _sanitize_provider_id(name: str) -> str:
    pid = re.sub(r"[^a-z0-9_-]", "", (name or "").lower())
    return pid or "custom"


def provider_key(settings) -> str:
    """当前生效的 dsh provider id（优先手动覆盖，其次按 AI 大脑接口识别）。"""
    override = str(getattr(settings, "dsh_provider", "") or "").strip()
    if override:
        return _sanitize_provider_id(override)
    ai = ai_config.current_config(settings) or {}
    return ai_config.provider_key_for_url(str(ai.get("api_url") or "")) or "deepseek"


def dsh_route(settings) -> tuple:
    """dsh 实际使用的 (provider, model)。

    DeepSeek 必须走 dsh 自带的 deepseek-official 适配器：它从启动环境
    DEEPSEEK_API_KEY 取密钥，也是 dsh-base 里 agent-default-model 的默认路由。
    自己用 llm-pi-ai 声明一个名为 "deepseek" 的 provider 不会被 llm 服务认出来，
    请求会以 `no adapter registered for provider "deepseek"` 收尾，用户看到的
    只有「⚠️ 处理消息时出现异常」。其他服务商（智谱 / Kimi / 通义 / 自定义）
    继续走 llm-pi-ai 自定义路由。
    """
    ai = ai_config.current_config(settings) or {}
    model = str(getattr(settings, "dsh_model", "") or "").strip() or str(ai.get("model") or "").strip()
    provider = provider_key(settings)
    if provider == "deepseek-official" or (
        provider == "deepseek"
        and str(ai.get("api_url") or "").strip().rstrip("/")
        in ("", "https://api.deepseek.com", "https://api.deepseek.com/v1")
    ):
        return "deepseek-official", model or "deepseek-flash"
    if not model:
        for p in ai_config.AI_PROVIDERS:
            if p["key"] == provider and p.get("model"):
                model = p["model"]
                break
    return provider, model


def _ensure_node(settings, log=None, on_progress=None, cancel_event=None) -> Path:
    """确保 Node.js 22+ 可用：优先系统/已配置 Node，否则自动下载便携版。"""
    node = node_exe(settings)
    if node and node_ok(node):
        return node

    def _prog(pct):
        if on_progress:
            try:
                on_progress(int(max(0, min(100, pct))))
            except Exception:  # noqa: BLE001
                pass

    def _log(line):
        if log:
            log(str(line))

    target = node_dir(settings)
    target.mkdir(parents=True, exist_ok=True)
    ver = NODE_VERSION
    _log(f"未检测到可用的 Node.js {MIN_NODE_MAJOR}+，正在下载便携版 Node.js {ver}（约 30MB）...")
    zip_path = settings.downloads_dir / f"node-{ver}-win-x64.zip"
    base = f"v{ver}/node-v{ver}-win-x64.zip"

    def _dl_progress(done, total):
        if total:
            _prog(int(100 * min(1.0, done / total)))

    try:
        download_with_mirrors(
            base, zip_path, progress=_dl_progress,
            prefixes=NODE_MIRROR_PREFIXES, timeout=1800,
            cancel_event=cancel_event,
        )
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(
            "Node.js 自动下载失败，请手动安装 Node.js " + str(MIN_NODE_MAJOR)
            + "+（https://nodejs.org）后在 dsh 设置中指定路径。原因: " + str(e)
        ) from e

    _log("正在解压 Node.js 便携版 ...")
    try:
        with zipfile.ZipFile(zip_path) as z:
            for m in z.infolist():
                if m.is_dir():
                    continue
                parts = Path(m.filename).parts
                if len(parts) <= 1:
                    continue
                rel = Path(*parts[1:])
                if rel.is_absolute() or ".." in rel.parts:
                    continue
                out = target / rel
                out.parent.mkdir(parents=True, exist_ok=True)
                with z.open(m) as src, open(out, "wb") as dst:
                    shutil.copyfileobj(src, dst)
    except Exception as e:  # noqa: BLE001
        raise RuntimeError("Node.js 解压失败: " + str(e)) from e

    exe = target / "node.exe"
    if not node_ok(exe):
        raise RuntimeError("Node.js 便携版校验失败（版本不可用），请手动安装后重试")
    settings.dsh_node_exe = str(exe)
    try:
        settings.save()
    except OSError as e:
        _log("保存 Node.js 路径失败（不影响本次使用）: " + str(e))
    _log("便携版 Node.js 就绪: " + str(exe))
    return exe


# ---------- 安装状态 ----------
def is_installed(settings) -> bool:
    return dsh_js(settings).exists() and profile_dir(settings).exists()


def uninstall(settings, log=None) -> None:
    """卸载 dsh：删除整个 dsh 运行时目录，并清理指向目录内便携 Node 的配置。"""
    def _log(line):
        if log:
            log(str(line))

    d = dsh_dir(settings)
    if d.exists():
        _log("正在卸载 dsh（删除运行时目录）...")
        try:
            shutil.rmtree(d)
        except OSError as e:
            raise RuntimeError("dsh 卸载失败：" + str(e)) from e
    saved = str(getattr(settings, "dsh_node_exe", "") or "").strip()
    if saved:
        try:
            if Path(saved).resolve().is_relative_to(d.resolve()):
                settings.dsh_node_exe = ""
                try:
                    settings.save()
                except OSError as e:
                    _log("清除 Node.js 路径失败: " + str(e))
        except (OSError, ValueError):
            pass
    _log("dsh 已卸载")


def install(settings, log=None, on_progress=None, cancel_event=None, force=False) -> None:
    """一键安装 dsh + 官方插件到安装根目录（纯凭证 profile，不装扫码组件）。

    已安装且未要求强制重装时，直接刷新配置并返回，
    避免用户点“安装/修复”时每次都重跑 npm install（表现为重新下载）。
    """
    def _prog(pct):
        if on_progress:
            try:
                on_progress(int(max(0, min(100, pct))))
            except Exception:  # noqa: BLE001
                pass

    def _log(line):
        if log:
            log(str(line))

    if not force and is_installed(settings):
        _prog(90)
        _log("dsh 已安装，跳过下载（正在刷新配置）...")
        write_config(settings, log=_log)
        ensure_bridge(settings, log=_log)
        _prog(100)
        return

    _prog(0)

    node = _ensure_node(
        settings, log=_log,
        on_progress=lambda p: _prog(4 + int(6 * max(0, min(100, p)) / 100)),
        cancel_event=cancel_event,
    )
    _prog(10)
    npm = _npm_cli(node)
    if not npm:
        raise RuntimeError("未找到 npm（Node.js 安装不完整），请重新安装 Node.js")
    _log(f"检测到 Node.js {node_version(node)}，开始安装 dsh ...")
    d = dsh_dir(settings)
    d.mkdir(parents=True, exist_ok=True)
    (workspace_dir(settings)).mkdir(parents=True, exist_ok=True)
    pkg = d / "package.json"
    if not pkg.exists():
        pkg.write_text(
            json.dumps({
                "name": "qbotmanager-dsh",
                "private": True,
                "version": "1.0.0",
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # npm install 很耗时（首次约 10-15 分钟），用 run_stream 实时回传。
    # 官方源失败时回退国内镜像；均失败时给出明确错误。
    install_start = time.time()
    for registry in (None, "https://registry.npmmirror.com"):
        if cancel_event is not None and cancel_event.is_set():
            raise RuntimeError("安装已取消")
        cmd = [str(node), str(npm), "install", "--no-audit", "--no-fund",
               "@deepseek-ai/dsh", "@tencent-connect/dsh-qqbot"]
        if registry:
            cmd += ["--registry", registry]
        _log("正在下载 dsh（首次安装约 10-15 分钟）..." + ("（国内镜像）" if registry else ""))

        # 没有可靠的分包进度：独立线程每 5 秒按耗时平滑推进到 72%，
        # 日志只回传文本，不再触发不定式进度条。
        stop_timer = threading.Event()

        def _tick():
            while not stop_timer.wait(5.0):
                elapsed_min = (time.time() - install_start) / 60.0
                _prog(10 + min(66, int(elapsed_min * 6)))

        ticker = threading.Thread(target=_tick, daemon=True, name="dsh-install-tick")
        ticker.start()
        try:
            rc, tail = run_stream(
                cmd, cwd=str(d), timeout=1800, env=None,
                on_line=_log, cancel_event=cancel_event,
            )
        except Exception as e:  # noqa: BLE001
            _log(f"安装失败：{e}")
            stop_timer.set()
            continue
        finally:
            stop_timer.set()
            ticker.join(timeout=2)
        if rc == 0:
            break
        if rc == -2:
            raise RuntimeError("安装已取消")
        _log("本次安装失败，尝试备用源 ...")
    else:
        raise RuntimeError("dsh 安装失败：npm install 未能成功，请检查网络后重试")

    # 创建 qqbot profile 并安装官方插件
    _log("正在创建 qqbot profile ...")
    _prog(78)
    js = dsh_js(settings)
    env = {"DSH_HOME": str(dsh_home(settings))}
    resolved = {"n": 0}

    def _profile_line(line):
        _log(line)
        # pnpm 输出 "Progress: resolved N"，每行推进一格（上限 90）
        if "resolved" in line:
            resolved["n"] += 1
            _prog(min(92, 78 + resolved["n"]))

    rc, out = run_stream(
        [str(node), str(js), "plugin", "--profile", "qqbot",
         "add", "@tencent-connect/dsh-qqbot"],
        cwd=str(d), timeout=600, env=env,
        on_line=_profile_line,
    )
    if rc != 0:
        raise RuntimeError("dsh 插件安装失败：" + (out or "")[-800:])
    _log("dsh 插件安装完成")
    _prog(94)
    write_config(settings, log=_log)
    ensure_bridge(settings, log=_log)
    _log("dsh 安装完成")
    _prog(100)


# ---------- 配置 ----------
def build_patch_text(settings) -> str:
    """生成 profile 的 cordis.patch.yml：纯凭证 + 模型路由 + 安全禁用。"""
    appid = str(getattr(settings, "qq_official_appid", "") or "").strip()
    secret = str(getattr(settings, "qq_official_secret", "") or "").strip()
    provider, model = dsh_route(settings)
    personality = ai_config.read_personality(settings).strip()
    require_mention = bool(getattr(settings, "dsh_require_mention", True))

    def yaml_str(v: str) -> str:
        return json.dumps(str(v or ""), ensure_ascii=False)

    lines = [
        "# 由 AstroSwarm 星群自动生成（纯官方凭证路径，不启用扫码绑定）",
        "- id: im-qqbot",
        "  config:",
        f"    appId: {yaml_str(appid)}",
        f"    appSecret: {yaml_str(secret)}",
        f"    provider: {yaml_str(provider)}",
        f"    model: {yaml_str(model)}",
        f"    requireMention: {'true' if require_mention else 'false'}",
        f"    cwd: {yaml_str(str(workspace_dir(settings)))}",
        "    textChunkLimit: 4500",
        "    sessionIdleTimeout: 1800000",
        "    debug: false",
        f"    preset: {AGENT_PRESET_ID}",
    ]
    if personality:
        lines.append(f"    groupPrompt: {yaml_str(personality)}")
        lines.append(f"    directPrompt: {yaml_str(personality)}")
    # 微信/外部平台桥：与 QQ 同一个 dsh agents 服务（同一大脑、同一记忆）
    lines.append("- id: qbm-bridge")
    lines.append("  config:")
    lines.append("    host: 127.0.0.1")
    lines.append(f"    port: {BRIDGE_PORT}")
    lines.append(f"    provider: {yaml_str(provider)}")
    lines.append(f"    model: {yaml_str(model)}")
    lines.append(f"    cwd: {yaml_str(str(workspace_dir(settings)))}")
    lines.append(f"    preset: {AGENT_PRESET_ID}")
    if personality:
        lines.append(f"    groupPrompt: {yaml_str(personality)}")
        lines.append(f"    directPrompt: {yaml_str(personality)}")
    lines.append(f"    bindingsFile: {yaml_str(str(bindings_file(settings)))}")
    # v1.2.9：**不再注册 dsh 的 agent preset**（注册表和 preset 行都不写）。
    # 原因：0.1.7 的 dsh 安装树里 dsh-scope 有多份物理拷贝，而 scopeOf() 读的是
    # 模块级 Symbol("dsh.scope")。注册表由 @deepseek-ai/dsh/node_modules 下那份
    # 解析，agent 却由 dsh-base/node_modules 下的 agent-loop 创建，两份 Symbol
    # 不相等 → presets.mount() 必抛
    # "Agent preset binding requires a scoped context"，会话根本建不起来，
    # 用户只会收到「⚠️ 处理消息时出现异常，请稍后重试。」
    # 人设改由两个通道各自的 groupPrompt / directPrompt 承担（im-qqbot 与
    # qbm-bridge 都实现了 system-prompt/assemble 注入），工具仍走宿主；
    # 等上游修掉 scope 拷贝问题再考虑恢复 preset。
    for tool in DISABLED_TOOLS:
        lines.append(f"- id: {tool}")
        lines.append("  disabled: true")
    return "\n".join(lines) + "\n"


def write_preset(settings, log=None) -> bool:
    """写入统一大脑 agent preset（px 人设，QQ 与微信桥共用）。"""
    try:
        d = agent_preset_dir(settings)
        d.mkdir(parents=True, exist_ok=True)
        personality = (ai_config.read_personality(settings) or "").strip()
        if not personality:
            personality = DEFAULT_PERSONALITY
        (d / "preset.yml").write_text(
            "name: 星群助手\n"
            "description: px 人设 + 统一大脑记忆规则（AstroSwarm 内置）\n"
            "order: 10\n",
            encoding="utf-8",
        )
        (d / "agent.cordis.yml").write_text(
            "# AstroSwarm 统一大脑 preset（自动生成，请勿手改）\n"
            "- id: persona\n"
            "  name: '@deepseek-ai/dsh-persona'\n"
            "  config:\n"
            f"    prefix: {json.dumps(personality, ensure_ascii=False)}\n",
            encoding="utf-8",
        )
        return True
    except OSError as e:
        if log:
            log("写入 dsh 人设 preset 失败: " + str(e))
        return False


def ensure_bridge(settings, log=None) -> bool:
    """把 qbm-bridge 插件加进 qqbot profile（幂等：marker 存在即跳过）。"""
    def _log(line):
        if log:
            log(str(line))

    if not is_installed(settings):
        return False
    marker = bridge_marker(settings)
    if marker.exists():
        try:
            if marker.read_text(encoding="utf-8").strip() == BRIDGE_VERSION:
                return True
        except OSError:
            pass
    src = bridge_source_dir()
    if not src.is_dir():
        return False
    stable = bridge_installed_dir(settings)
    try:
        shutil.copytree(src, stable, dirs_exist_ok=True)
    except OSError as e:
        _log("拷贝桥插件到稳定目录失败：" + str(e))
        return False
    node = node_exe(settings)
    js = dsh_js(settings)
    if not node or not js.exists():
        return False
    d = dsh_dir(settings)
    env = {"DSH_HOME": str(dsh_home(settings))}
    _log("正在把微信桥插件接入 dsh ...")
    try:
        rc, out = run_capture(
            [str(node), str(js), "plugin", "--profile", "qqbot", "add", f"file:{stable}"],
            cwd=str(d), timeout=300, env=env,
        )
    except Exception as e:  # noqa: BLE001
        _log(f"桥插件接入异常: {e}")
        return False
    if rc != 0:
        _log("桥插件接入失败：" + (out or "")[-500:])
        return False
    try:
        marker.write_text(BRIDGE_VERSION, encoding="utf-8")
    except OSError:
        pass
    _log("微信桥插件已接入 dsh（下次启动 dsh 时生效，不用重启其它服务）")
    return True


def build_settings_text(settings) -> str:
    """生成 DSH_HOME/settings.yaml：把 AI 大脑的服务商注册为 dsh 自定义 provider。

    dsh 的 llm 服务只认注册过的 provider：DeepSeek 用自带的 deepseek-official，
    第三方（通义 / Kimi / 智谱 / OpenAI / 自定义）按 OpenAI 兼容协议走 llm-pi-ai。
    """
    ai = ai_config.current_config(settings) or {}
    provider, model = dsh_route(settings)
    base_url = str(ai.get("api_url") or "").strip()
    if not base_url:
        for p in ai_config.AI_PROVIDERS:
            if p["key"] == provider and p.get("url"):
                base_url = p["url"]
                break

    def y(v: str) -> str:
        return json.dumps(str(v or ""), ensure_ascii=False)

    lines = [
        "agent-default-model:",
        f"  provider: {y(provider)}",
        f"  model: {y(model)}",
    ]
    # DeepSeek 走 dsh 自带的 deepseek-official 适配器，不能再自己声明同名 provider；
    # 只有第三方接口才需要 llm-pi-ai 自定义路由。
    if provider != "deepseek-official":
        lines += [
            "llm-pi-ai:",
            "  providers:",
            f"    {provider}:",
            "      apiKeyEnv: QBM_DSH_API_KEY",
            "      api: openai-completions",
            f"      baseURL: {y(base_url)}",
            "      models:",
            f"        - id: {y(model)}",
        ]
    return "\n".join(lines) + "\n"


def write_config(settings, log=None) -> bool:
    """把当前凭证/模型/人设写入 profile 配置与 settings.yaml；未安装时返回 False。"""
    if not profile_dir(settings).exists():
        return False
    try:
        write_preset(settings, log=log)
        pf = patch_file(settings)
        pf.parent.mkdir(parents=True, exist_ok=True)
        pf.write_text(build_patch_text(settings), encoding="utf-8")
        sf = settings_yaml_file(settings)
        sf.parent.mkdir(parents=True, exist_ok=True)
        sf.write_text(build_settings_text(settings), encoding="utf-8")
        return True
    except OSError as e:
        if log:
            log("写入 dsh 配置失败: " + str(e))
        return False


# ---------- 会话自愈 ----------
# DeepSeek Messages 协议要求「助手发起的工具调用」必须紧跟着对应的「工具结果」。
# dsh 执行工具时如果基础设施抛错（0.1.7 的 scope / 调度器缺陷等），日志里会留下
# 一条只有 tool call、没有 tool result 的记录；这条记录之后的每一轮请求都会被
# 适配器拒收：
#   INVALID_REQUEST: DeepSeek Messages tool calls need immediate results
# 机器人于是永久卡死（用户看到「⚠️ 本轮异常结束」+ 上面这句），重启才能好。
# 这里在启动 dsh 之前把这种坏会话回滚到「最后一个完整轮次」：保留之前正常的对话，
# 把出错的轮次和它之后那些失败的尝试一起丢掉，并删掉投影缓存让它重新生成。
def sessions_dir(settings) -> Path:
    return dsh_home(settings) / "sessions"


def session_logs(settings) -> list:
    """所有 dsh 会话日志（<home>/sessions/<工作目录>/<会话 id>/<版本>.jsonl.zstd）。"""
    base = sessions_dir(settings)
    if not base.exists():
        return []
    return sorted(p for p in base.glob("*/*/*.jsonl.zstd") if p.is_file())


def _read_session_text(path: Path):
    """读 dsh 会话文本（多帧 zstd）；读不出来返回 None（损坏文件交给 dsh 自己恢复）。"""
    try:
        import zstandard
    except ImportError:
        return None
    try:
        with open(path, "rb") as f:
            raw = zstandard.ZstdDecompressor().stream_reader(f).read()
        return raw.decode("utf-8")
    except Exception:  # noqa: BLE001
        return None


def _parse_session(text: str):
    """拆成 (header, header_line, event_lines, events)；结构不认识就返回 None。"""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) < 2:
        return None
    try:
        header = json.loads(lines[0])
    except ValueError:
        return None
    if not isinstance(header, dict) or header.get("type") != "session":
        return None
    events = []
    for i, ln in enumerate(lines[1:]):
        try:
            ev = json.loads(ln)
        except ValueError:
            return None
        if not isinstance(ev, dict) or ev.get("seq") != i:
            return None      # 布局变了就别乱动（seq 必须从 0 连续）
        events.append(ev)
    return header, lines[0], lines[1:], events


def _wire_blocks(raw) -> list:
    """把会话里的内容块换成 DeepSeek 线上的块名（tool-call → tool_use）。"""
    out = []
    for b in raw if isinstance(raw, list) else []:
        if not isinstance(b, dict):
            continue
        kind = b.get("type")
        if kind == "tool-call":
            out.append({"type": "tool_use", "id": b.get("id")})
        elif kind == "tool-result":
            out.append({"type": "tool_result", "id": b.get("toolCallId")})
        else:
            out.append({"type": kind})
    return out


def _history_problem(events) -> tuple | None:
    """按 DeepSeek 适配器同样的规则检查历史；坏则返回 (事件下标, 原因)。"""
    merged = []          # [[wire_role, blocks], ...]：连续同角色会合并
    for i, ev in enumerate(events):
        kind = ev.get("type")
        data = ev.get("data") if isinstance(ev.get("data"), dict) else {}
        if kind == "user/message":
            blocks = _wire_blocks(data.get("content"))
            if not blocks:
                continue
            role = "user"
        elif kind == "assistant/message":
            msg = data.get("message") if isinstance(data.get("message"), dict) else {}
            blocks = _wire_blocks(msg.get("content"))
            if not blocks:
                continue
            for b in blocks:
                if b["type"] == "tool_use":
                    b["at"] = i
            role = "assistant"
        elif kind == "tool/result":
            msg = data.get("message") if isinstance(data.get("message"), dict) else {}
            src = msg.get("source") if isinstance(msg.get("source"), dict) else {}
            call = src.get("callId")
            if not call:
                continue
            blocks = [{"type": "tool_result", "id": call}]
            role = "user"
        else:
            continue
        if merged and merged[-1][0] == role:
            merged[-1][1].extend(blocks)
        else:
            merged.append([role, blocks])
    pending = {}         # callId -> 发起它的事件下标
    for role, blocks in merged:
        if role == "assistant":
            pending = {}
            for b in blocks:
                if b["type"] != "tool_use" or not b.get("id"):
                    continue
                pending[b["id"]] = b.get("at", 0)
        else:
            for b in blocks:
                if b["type"] == "tool_result":
                    pending.pop(b.get("id"), None)
            if pending:
                return min(pending.values()), "工具调用没有紧跟工具结果"
    if pending:
        return min(pending.values()), "历史以未结束的工具调用结尾"
    return None


def _turn_start_before(events, index: int) -> int:
    """往前找到包含该事件的那一轮的 turn/start 下标（找不到返回 -1）。"""
    i = min(index, len(events) - 1)
    while i >= 0:
        if events[i].get("type") == "turn/start":
            return i
        i -= 1
    return -1


def _write_session_frames(path: Path, header_line: str, lines) -> None:
    """按 dsh 的物理格式写回：第一帧只有 header 一行，第二帧是全部事件。"""
    import zstandard
    cctx = zstandard.ZstdCompressor(write_checksum=True)
    blob = cctx.compress((header_line + "\n").encode("utf-8"))
    body = "".join(ln + "\n" for ln in lines)
    if body:
        blob += cctx.compress(body.encode("utf-8"))
    tmp = path.with_name(path.name + ".repair-tmp")
    with open(tmp, "wb") as f:
        f.write(blob)
    tmp.replace(path)


def _drop_projection_cache(home: Path, session_id: str) -> None:
    """删掉会话投影缓存，强制 dsh 用回滚后的历史重建。"""
    if not session_id:
        return
    cache = home / "storages" / "session_projcache" / "sessions" / (session_id + ".json")
    try:
        cache.unlink()
    except OSError:
        pass


def repair_session_log(path: Path, home: Path, log=None) -> bool:
    """修一个坏会话；返回 True 表示文件被改写（含整段丢弃）。"""
    parsed = _parse_session(_read_session_text(path) or "")
    if not parsed:
        return False
    header, header_line, event_lines, events = parsed
    keep = len(events)
    why = ""
    while True:
        problem = _history_problem(events[:keep])
        if problem is None:
            break
        why = problem[1]
        cut = _turn_start_before(events, problem[0])
        if cut <= 0:
            keep = 0
            break
        keep = cut
    if keep == len(events):
        return False
    sid = str(header.get("id") or path.parent.name)
    backup = path.with_name(path.name + ".repair-bak")
    try:
        if not backup.exists():
            shutil.copy2(path, backup)
    except OSError:
        pass
    try:
        if keep == 0:
            path.unlink()        # 整段历史都不可用：留好备份，下次 dsh 建新会话
        else:
            _write_session_frames(path, header_line, event_lines[:keep])
    except OSError as e:
        if log:
            log("修复 dsh 会话失败: " + str(e))
        return False
    _drop_projection_cache(home, sid)
    if log:
        log("修复 dsh 会话 %s：%s，已回到最近一次正常对话（原文件备份为 %s）"
            % (sid, why or "历史断链", backup.name))
    return True


def repair_sessions(settings, log=None) -> int:
    """启动前自检：修掉被工具调用中断的 dsh 会话，返回修好的会话数。"""
    home = dsh_home(settings)
    fixed = 0
    for path in session_logs(settings):
        try:
            if repair_session_log(path, home, log=log):
                fixed += 1
        except Exception:  # noqa: BLE001 —— 自愈失败绝不能挡住启动
            continue
    return fixed

# ---------- 启停 ----------
def start(settings, log=None, cancel_event=None):
    """启动 dsh qqbot profile；返回 Popen。"""
    if not is_installed(settings):
        raise RuntimeError("dsh 未安装，请先在 QQ 页点击「安装/修复 dsh」")
    appid = str(getattr(settings, "qq_official_appid", "") or "").strip()
    secret = str(getattr(settings, "qq_official_secret", "") or "").strip()
    if not appid or not secret:
        raise RuntimeError("请先在上方填写 QQ 官方机器人 AppID / AppSecret")
    ai = ai_config.current_config(settings) or {}
    api_key = str(getattr(settings, "dsh_api_key", "") or "").strip() or str(ai.get("api_key") or "")
    if not api_key:
        raise RuntimeError("未配置模型 API Key：请在 AI 大脑中配置服务商，或在 dsh 设置中填写")
    if not write_config(settings, log=log):
        raise RuntimeError("写入 dsh 配置失败")
    repair_sessions(settings, log=log)   # 工具调用断链的坏会话先自愈（细节写日志）
    ensure_bridge(settings, log=log)
    node = node_exe(settings)
    if not node:
        raise RuntimeError("未检测到 Node.js")
    js = dsh_js(settings)
    env = {
        "DSH_HOME": str(dsh_home(settings)),
        "QQBOT_APPID": appid,
        "QQBOT_SECRET": secret,
        "DEEPSEEK_API_KEY": api_key,
        "QBM_DSH_API_KEY": api_key,
    }
    if log:
        log("启动 dsh（DeepSeek Harness QQ 通道）...")
    return start_process(
        [str(node), str(js), "--profile", "qqbot"],
        cwd=str(dsh_dir(settings)),
        on_line=log,
        env=env,
        log_file=dsh_log(settings),
    )


def status(settings, running: bool) -> dict:
    """dsh 通道状态（不依赖外部进程查询）。"""
    st = {
        "installed": is_installed(settings),
        "running": running,
        "connected": False,
        "reason": "未安装",
        "appid": str(getattr(settings, "qq_official_appid", "") or ""),
        "node": node_version(node_exe(settings)),
    }
    if not st["installed"]:
        # 小白看不懂「未安装」之后要干嘛：直接告诉他点哪个按钮，一步装 + 启动
        st["reason"] = "未安装 · 点「安装并启动 dsh」会自动装好并启动"
        return st
    if not running:
        st["reason"] = "已安装 · 未运行（点「启动 dsh」）"
        return st
    text = ""
    try:
        p = dsh_log(settings)
        if p.exists():
            with open(p, "r", encoding="utf-8", errors="replace") as f:
                f.seek(max(0, p.stat().st_size - 65536))
                text = f.read()
    except OSError:
        text = ""
    idx_ready = text.rfind("Bot ready!")
    idx_bad = max(
        text.rfind("Reconnecting"),
        text.rfind("连接失败"),
        text.rfind("接口访问源IP不在白名单"),
    )
    if idx_ready > idx_bad:
        st["connected"] = True
        st["reason"] = "已连接（QQ 网关 READY）"
    elif idx_bad > idx_ready:
        st["connected"] = False
        st["reason"] = (
            "IP 白名单未配置（开放平台 → 开发设置）"
            if "接口访问源IP不在白名单" in text[max(0, idx_bad - 200):idx_bad + 200]
            else "连接中/重试中（检查开放平台 IP 白名单）"
        )
    else:
        st["reason"] = "启动中"
    return st
