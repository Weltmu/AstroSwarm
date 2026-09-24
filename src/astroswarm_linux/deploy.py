"""Linux 机器人运行时部署与启停（复用 qbotmanager.core.bot 骨架）。"""
import json
import os
import subprocess
import time
from pathlib import Path

from qbotmanager.core import bot as bot_mod
from qbotmanager.core import tool_packs as tool_packs_mod
from qbotmanager.core.settings import Settings

from . import headless_config, platform_info, proc, runtime

BOT_DEPS = [
    "nonebot2",
    "nonebot-adapter-qq",
    # 第三方 OneBot 协议端（NapCat / LLOneBot / Lagrange）走的是这个适配器；
    # 通道选 onebot 时 run.py 会 import 它，缺了机器人直接起不来。
    "nonebot-adapter-onebot",
    "nonebot-plugin-localstore",
    "fastapi",
    "httpx",
    "websockets",
    "uvicorn",
    "openai",
    "mcp",
    "PyJWT",
    "cryptography",
]
PIP_INDEX = os.environ.get(
    "PIP_INDEX", "https://pypi.tuna.tsinghua.edu.cn/simple"
)


def state_path() -> Path:
    return platform_info.data_home() / "state.json"


def bot_log_path() -> Path:
    return platform_info.log_home() / "nonebot.log"


_QQ_STATE_CACHE = {"at": 0.0, "value": "unknown"}


def _qq_state_from_log() -> str:
    """官方通道/兜底：从机器人日志尾部判断。"""
    try:
        lines = bot_log_path().read_text(
            encoding="utf-8", errors="replace"
        ).splitlines()[-80:]
    except OSError:
        return "unknown"
    # 从最新一行往回找，只看最近一次运行的结果
    for line in reversed(lines):
        if "11298" in line or "白名单" in line or "Unauthorized" in line:
            return "unauthorized"
        if "READY" in line or "connected" in line.lower():
            return "connected"
    if any("Loaded adapters: QQ" in ln for ln in lines):
        return "connecting"
    return "unknown"


def _established_ports() -> list:
    """当前 ESTABLISHED 连接里的「本地端口:对端端口」列表（不依赖第三方库）。"""
    import subprocess

    out = ""
    for cmd in (["ss", "-tn", "state", "established"], ["ss", "-tn"]):
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            out = proc.stdout or ""
        except Exception:  # noqa: BLE001
            out = ""
        if out.strip():
            break
    import re as _re

    addr = _re.compile(r"^[\[\]0-9a-fA-F\.\*:]+:\d+$")
    pairs = []
    for line in out.splitlines():
        toks = line.split()
        if not toks or toks[0].lower().startswith("state"):
            continue                      # 表头
        addrs = [t for t in toks if addr.match(t)]
        if len(addrs) >= 2:
            pairs.append((addrs[0], addrs[1]))   # (本地:端口, 对端:端口)
    return pairs


def _qq_state() -> str:
    """协议端到底连上没有。

    不能只搜日志里的 "connected"：那行写进去就永远在，协议端掉线了控制台还显示「已连接」。
    按真实 TCP 连接判断（反向 WS 看谁连到 bot_port，正向 WS 看我们连出去那条）。
    """
    import time as _time

    now = _time.time()
    if now - _QQ_STATE_CACHE["at"] < 3:      # 控制台会轮询，3 秒内复用结果
        return _QQ_STATE_CACHE["value"]

    state = "unknown"
    try:
        s = build_settings()
        channel = str(getattr(s, "qq_channel", "") or "")
        if channel == "onebot":
            mode = str(getattr(s, "qq_onebot_mode", "") or "reverse").lower()
            pairs = _established_ports()
            if mode == "reverse":
                want = f":{int(getattr(s, 'nonebot_port', 0) or 0)}"
                state = "connected" if any(local.endswith(want) for local, _ in pairs) else "stopped"
            else:
                port = int(getattr(s, "qq_onebot_port", 0) or 0)
                want = f":{port}"
                state = "connected" if any(peer.endswith(want) for _, peer in pairs) else "stopped"
        else:
            state = _qq_state_from_log()
    except Exception:  # noqa: BLE001
        state = _qq_state_from_log()

    _QQ_STATE_CACHE.update({"at": now, "value": state})
    return state


def build_settings() -> Settings:
    cfg = headless_config.load()
    root = platform_info.data_home()
    s = Settings(root)
    s.ensure_dirs()
    s.nonebot_port = int(cfg.get("bot_port") or 12113)
    s.qq_official_appid = cfg.get("qq_app_id") or ""
    s.qq_official_secret = cfg.get("qq_app_secret") or ""
    s.qq_official_token = cfg.get("qq_app_token") or ""
    # QQ 通道：不喂这几个键的话，Settings 会用自己的默认值（服务器那份是 official/None），
    # _onebot_active() 恒为 False，机器人最后连一个适配器都不加载 —— 连不上任何 QQ。
    s.qq_channel = cfg.get("qq_channel") or "onebot"
    s.qq_onebot_mode = cfg.get("qq_onebot_mode") or "reverse"
    s.qq_onebot_host = cfg.get("qq_onebot_host") or "127.0.0.1"
    s.qq_onebot_port = int(cfg.get("qq_onebot_port") or 0)
    s.qq_onebot_path = cfg.get("qq_onebot_path") or "/onebot/v11/ws"
    s.qq_onebot_token = cfg.get("qq_onebot_token") or ""
    s.qq_onebot_listen_host = cfg.get("qq_onebot_listen_host") or "127.0.0.1"
    s.agent_profile_enabled = bool(cfg.get("agent_profile_enabled"))
    s.agent_profile_id = cfg.get("agent_profile_id") or "star_helper"
    # 桌面端字段名是 agent_owner_openid（官方通道存 openid，OneBot 通道就是 QQ 号），
    # bot.write_env 读的也是它；写成 agent_owner_qq 不生效。
    s.agent_owner_openid = str(
        cfg.get("agent_owner_qq") or cfg.get("agent_owner_openid") or ""
    )
    _words = str(cfg.get("agent_address_words") or "").replace("，", ",")
    if _words.strip():
        s.agent_wake_words = [w.strip() for w in _words.split(",") if w.strip()]
    s.ai_enabled = bool(cfg.get("ai_api_key"))
    s.ai_api_key = cfg.get("ai_api_key") or ""
    s.ai_base_url = cfg.get("ai_base_url") or ""
    s.ai_model = cfg.get("ai_model") or ""
    s.ai_provider = cfg.get("ai_provider") or "deepseek"
    # 与桌面端对齐的其余配置：平台开关 / 视觉模型 / 唤醒词
    _plat = cfg.get("ai_platforms")
    if isinstance(_plat, dict):
        s.ai_platforms = {
            k: bool(_plat.get(k, True)) for k in ("qq", "wechat", "feishu", "telegram")
        }
    s.vision_api_url = str(cfg.get("vision_api_url") or "").strip()
    s.vision_api_key = str(cfg.get("vision_api_key") or "").strip()
    s.vision_model = str(cfg.get("vision_model") or "").strip()
    s.agent_wake_auto = bool(cfg.get("agent_wake_auto", True))
    # 本地人设工坊当前启用的人设 id：机器人启动时 persona_workshop.pack_env 靠它决定
    # 加载哪个人设的自带工具（ASTROSWARM_PERSONAS_ALLOWED）；不喂就会是空的。
    s.local_persona_id = str(cfg.get("local_persona_id") or "")
    return s


def ensure_bot(log=print) -> Settings:
    """生成 bot 骨架 + 创建 venv + 安装依赖。幂等：已装则跳过。"""
    s = build_settings()
    bot_mod.scaffold_bot(s, log=log)
    venv_py = runtime.ensure_venv(runtime.find_python3(), s.bot_dir / ".venv", log)
    s.python_exe = venv_py
    marker = s.bot_dir / ".venv" / ".qbm_deps_v3"
    if not marker.exists():
        log("安装机器人依赖（nonebot2 / adapter-qq / localstore / openai / mcp）...")
        subprocess.run(
            [str(venv_py), "-m", "pip", "install", "-q", "--upgrade", "pip"],
            check=False,
            env={**os.environ, "PIP_INDEX_URL": PIP_INDEX},
            timeout=600,
        )
        subprocess.run(
            [str(venv_py), "-m", "pip", "install", "-q", *BOT_DEPS],
            check=True,
            env={**os.environ, "PIP_INDEX_URL": PIP_INDEX},
            timeout=900,
        )
        marker.write_text("ok", encoding="utf-8")
        log("依赖安装完成")
    bot_mod.write_env(s)
    try:
        from qbotmanager.core import ai_config

        ai_config.save_config(
            s,
            s.ai_api_key or "",
            s.ai_base_url or "",
            s.ai_model or "",
        )
    except Exception as exc:  # noqa: BLE001
        log(f"AI 配置写入跳过：{exc}")
    try:
        # 微信通道按真实权益决定，写死 False 会在每次部署时把 ilink 适配器删掉。
        # 用 member 而不是 full：full 是「解锁全部付费能力包」（只有 permanent），
        # 微信通道属于「付费会员」能力，月费档也该有。
        _full = False
        try:
            from . import auth as _auth

            _gate = _auth.feature_gate()
            _full = bool(_gate.get("member", _gate.get("full")))
        except Exception:  # noqa: BLE001
            _full = False
        bot_mod.apply_wechat_gate(s, full=_full)
        log("微信通道（iLink）：%s" % ("已启用手" if _full else "未解锁，仅 QQ"))
    except Exception as exc:  # noqa: BLE001
        log(f"微信闸门同步跳过：{exc}")
    return s


def _env(settings: Settings) -> dict:
    env = {"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    try:
        env.update(bot_mod.build_bot_env(settings))
    except Exception:  # noqa: BLE001
        pass
    # build_bot_env() 内部用桌面端的 lic.feature_gate() 判权益，无头端读不到桌面 license，
    # 会把 AI_PLATFORM_* 一律压成 "0"，表现是消息进来了却「平台分发返回 None，跳过」。
    # 无头端的权益在 auth.feature_gate()，所以这里用自己的结论覆盖平台开关。
    try:
        env.update(bot_mod.ai_platform_env(settings))
    except Exception:  # noqa: BLE001
        pass
    env["ASTROSWARM_TOOL_PACKS"] = str(platform_info.data_home() / "tool_packs")
    _packs = _allowed_packs()
    env["ASTROSWARM_TOOL_PACKS_ALLOWED"] = ",".join(_packs)
    # 主动聊天是付费能力包：它的实现（ai 插件里的 proactive 模块）必须在确认授权后才导入，
    # 否则「付费门」只在工具清单上，代码照样随免费插件一起加载 = 白送。
    if "proactive" in _packs:
        env["ASTROSWARM_PACK_PROACTIVE"] = "1"
    # 已安装回复节奏行为包 → 李清菡插件用其配置覆盖内置默认节奏
    rhythm = platform_info.data_home() / "tool_packs" / "reply-rhythm" / "behavior.json"
    if rhythm.exists():
        env["ASTROSWARM_REPLY_RHYTHM"] = str(rhythm)
    return env


def _allowed_packs() -> list:
    """本机已安装、可以加载的工具包（装了就加载）。

    2026-09 起能力包全部免费（随主仓库开源）：不再看 plan / owned_plugins /
    账号签名，也不再有「会员到期冻结」。仍然逐个读 manifest.json 取 id，
    是为了跳过没有 id 的坏包（历史目录残留、手工拷一半的包）。
    """
    root = platform_info.data_home() / "tool_packs"
    allowed = []
    if root.exists():
        for pack in root.iterdir():
            manifest = pack / "manifest.json"
            if not manifest.exists():
                continue
            try:
                mid = json.loads(manifest.read_text(encoding="utf-8")).get("id")
            except Exception:  # noqa: BLE001
                continue
            if mid:
                allowed.append(mid)
    return allowed


def _listen_pid(port: int) -> int:
    """谁在监听这个端口（拿不到返回 0）。用于「状态文件坏了也知道机器人其实在跑」。"""
    if not port:
        return 0
    import re as _re
    import subprocess

    for cmd in (["ss", "-lntpH", f"sport = :{int(port)}"], ["ss", "-lntp"]):
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=5).stdout or ""
        except Exception:  # noqa: BLE001
            out = ""
        if not out.strip():
            continue
        if f":{int(port)}" not in out:
            continue
        m = _re.search(r"pid=(\d+)", out)
        if m:
            return int(m.group(1))
    return 0


def _pid_alive(pid: int) -> bool:
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except OSError:
        return False


def _bot_pid() -> int:
    """当前真正在跑的机器人 pid。

    先信状态文件，其次看 bot_port 的监听者：状态文件丢了或写过又崩时，机器人明明在跑
    （微信还连着）控制台却显示「未运行」，用户会反复点「启动」。
    """
    st = _state()
    pid = int(st.get("pid") or 0)
    if _pid_alive(pid):
        return pid
    cfg = headless_config.load()
    port = int(cfg.get("bot_port") or 12113)
    live = _listen_pid(port)
    if live:
        state_path().write_text(
            json.dumps({"pid": live, "started_at": int(st.get("started_at") or time.time())}),
            encoding="utf-8",
        )
    return live


def start(log=print) -> dict:
    """启动机器人。已有实例在跑就直接返回，绝不拉起第二个（两个实例会抢同一个端口）。"""
    running = _bot_pid()
    if running:
        log(f"bot 已在运行 pid={running}，跳过启动")
        return {"ok": True, "already_running": True, "pid": running}
    s = ensure_bot(log=log)
    log_path = bot_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("", encoding="utf-8")  # 每次启动清空，状态判断只看本次运行
    popen = proc.spawn(
        [str(s.python_exe), "run.py"],
        cwd=s.bot_dir,
        env=_env(s),
        log_path=log_path,
    )
    state_path().write_text(
        json.dumps({"pid": popen.pid, "started_at": int(time.time())}),
        encoding="utf-8",
    )
    log(f"bot 已启动 pid={popen.pid}")
    return {"ok": True, "pid": popen.pid}


def stop(log=print) -> dict:
    """停止机器人：等进程真的退出再返回，超时就 SIGKILL。"""
    import signal

    pid = _bot_pid()
    if not pid:
        if state_path().exists():
            state_path().unlink()
        log("bot 没在运行")
        return {"ok": True, "already_stopped": True}
    try:
        os.kill(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass
    deadline = time.time() + 8
    while time.time() < deadline and _pid_alive(pid):
        time.sleep(0.3)
    if _pid_alive(pid):
        log(f"bot pid={pid} 未响应 SIGTERM，强制结束")
        try:
            os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        time.sleep(0.5)
    if state_path().exists():
        state_path().unlink()
    log("bot 已停止")
    return {"ok": True, "pid": pid}


def _state() -> dict:
    try:
        return json.loads(state_path().read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def status() -> dict:
    st = _state()
    pid = _bot_pid()          # 状态文件坏了也能从端口反查到真实 pid
    alive = bool(pid)
    s = build_settings()
    installed = (s.bot_dir / "run.py").exists() and (
        s.bot_dir / ".venv" / "bin" / "python"
    ).exists()
    return {
        "state": "running" if alive else ("installed" if installed else "not_installed"),
        "pid": pid or None,
        "started_at": st.get("started_at"),
        "bot_dir": str(s.bot_dir),
        "log": str(bot_log_path()),
        "qq": _qq_state(),
    }
