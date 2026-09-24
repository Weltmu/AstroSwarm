"""一键部署编排：Python 运行时 -> 依赖 -> 机器人骨架。"""
from ..constants import AI_PLUGIN_DEPS, BOT_PACKAGES
from .bot import scaffold_bot, write_env
from .ports import find_free_port
from .python_runtime import ensure_python, install_with_fallback


def prepare_ports(settings):
    """确保端口可用，被占用则自动顺延并同步配置。"""
    settings.nonebot_port = find_free_port(settings.nonebot_port)
    write_env(settings)


def _make_logger(settings, log):
    """把部署日志同时写入 logs/deploy.log，方便排查问题。"""
    try:
        logfile = settings.logs_dir / "deploy.log"
        logfile.parent.mkdir(parents=True, exist_ok=True)
        f = open(logfile, "a", encoding="utf-8", errors="replace")
    except OSError:
        f = None

    def emit(line):
        if log:
            try:
                log(line)
            except Exception:  # noqa: BLE001
                pass
        if f is not None:
            try:
                f.write(line + "\n")
                f.flush()
            except OSError:
                pass

    return emit


def deploy_all(settings, progress=None, log=None, download_progress=None, cancel_event=None) -> dict:
    """执行完整部署，进度按真实阶段映射到 0-100。"""
    log = _make_logger(settings, log)

    def scaled(lo: int, hi: int, label: str):
        def cb(*args):
            try:
                if len(args) == 1:
                    p = float(args[0])
                elif len(args) >= 2 and args[1]:
                    p = float(args[0]) * 100.0 / float(args[1])
                else:
                    p = 0.0
            except (TypeError, ValueError, ZeroDivisionError):
                p = 0.0
            p = max(0.0, min(100.0, p))
            if progress:
                progress(int(lo + p * (hi - lo) / 100.0), 100, label)
        return cb

    settings.ensure_dirs()
    if progress:
        progress(0, 100, "准备部署")

    if not settings.deployed.get("python"):
        ensure_python(settings, progress=scaled(4, 28, "下载 Python 运行时"),
                      log=log, cancel_event=cancel_event)
        settings.deployed["python"] = True
        settings.save()
    if progress:
        progress(30, 100, "Python 就绪")

    if not settings.deployed.get("deps"):
        install_with_fallback(settings, list(BOT_PACKAGES) + list(AI_PLUGIN_DEPS), log=log,
                              progress=scaled(32, 55, "安装 NoneBot 依赖"),
                              cancel_event=cancel_event)
        settings.deployed["deps"] = True
        settings.save()
    if progress:
        progress(57, 100, "依赖就绪")

    scaffold_bot(settings, log=log)
    write_env(settings)
    settings.deployed["bot"] = True
    settings.save()
    if progress:
        progress(60, 100, "生成机器人项目")

    settings.save()
    if progress:
        progress(100, 100, "部署完成")
    if log:
        log("全部部署完成！")
    return {
        "python": str(settings.python_exe),
        "bot": str(settings.bot_dir),
        "nonebot_port": settings.nonebot_port,
    }
