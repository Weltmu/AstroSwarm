"""命令行入口（方便无界面调试，也为打包后的 --cli 提供支持）。"""
import argparse
import os
import sys
import tempfile
from pathlib import Path

from .installer import deploy_all
from .manager import Manager
from .plugins import extract_zip_plugin, install_store_plugin, list_local_plugins
from .settings import Settings


class _SafeWriter:
    """打包版（console=False）没有 stdout/stderr，print 会抛异常并让 --cli 退出码变 1。

    安装程序调用 `AstroSwarm.exe --cli deploy` 时就会踩到：部署其实成功了，
    但进程最后崩一下，安装程序会以为失败。这里把输出落到日志文件兜底。
    """

    def __init__(self, path):
        self._path = Path(path)
        self._fh = None
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._fh = open(self._path, "a", encoding="utf-8", errors="replace")
        except OSError:
            self._fh = None

    def write(self, text):
        if self._fh is not None:
            try:
                self._fh.write(text)
                self._fh.flush()
            except OSError:
                pass
        return len(text or "")

    def flush(self):
        if self._fh is not None:
            try:
                self._fh.flush()
            except OSError:
                pass

    def isatty(self):
        return False


def _ensure_output():
    """无控制台时给 sys.stdout/stderr 装上兜底 writer。"""
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is None:
            log_path = os.environ.get("QBM_CLI_LOG") or str(
                Path(tempfile.gettempdir()) / "astroswarm_cli.log")
            setattr(sys, name, _SafeWriter(log_path))
            continue
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass


def _load_settings(root):
    if root:
        return Settings.load(root)
    found = Settings.find_root()
    if found:
        return Settings.load(found)
    raise SystemExit("未找到已安装的管理器，请先运行图形界面完成首次部署，或指定 --root")


def _run(args):
    s = _load_settings(args.root)
    if args.cmd == "deploy":
        if getattr(args, "auto_start_services", False):
            s.auto_start_services = True
            s.save()
        result = deploy_all(s, log=lambda x: print(x, flush=True))
        for k, v in result.items():
            print(f"{k}: {v}")
    elif args.cmd == "start":
        m = Manager(s, on_log=lambda x: print(x, flush=True))
        m.start_all()
        print("started")
    elif args.cmd == "stop":
        m = Manager(s, on_log=lambda x: print(x, flush=True))
        m.stop_all()
        print("stopped")
    elif args.cmd == "restart-bot":
        m = Manager(s, on_log=lambda x: print(x, flush=True))
        m.restart_bot()
        print("restarted")
    elif args.cmd == "install-plugin":
        install_store_plugin(s, args.name, log=lambda x: print(x, flush=True))
    elif args.cmd == "install-zip":
        p = extract_zip_plugin(s, args.path, log=lambda x: print(x, flush=True))
        print("extracted:", p)
    elif args.cmd == "list-plugins":
        for p in list_local_plugins(s):
            print(p)
    elif args.cmd == "open-env":
        os.startfile(str(s.bot_env_file))
    elif args.cmd == "open-plugins":
        os.startfile(str(s.plugins_dir))
    elif args.cmd == "info":
        print("root:", s.root)
        print("bot:", s.bot_dir)
        print("qq_channel:", s.qq_channel)
        print("nonebot_port:", s.nonebot_port)
        print("account:", s.account_qq)


def main(argv=None):
    _ensure_output()
    p = argparse.ArgumentParser(prog="AstroSwarm", description="多平台机器人管理器")
    p.add_argument("--root", default=None, help="根目录（默认读取全局指针）")
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument("--root", default=None, help="根目录（默认读取全局指针）")
    sub = p.add_subparsers(dest="cmd")
    deploy_parser = sub.add_parser("deploy", help="一键部署", parents=[parent])
    deploy_parser.add_argument(
        "--auto-start-services", action="store_true",
        help="部署后把配置设为「启动程序时自动启动全部服务」")
    sub.add_parser("start", help="启动 QQ 官方通道 + NoneBot", parents=[parent])
    sub.add_parser("stop", help="停止全部", parents=[parent])
    sub.add_parser("restart-bot", help="重启 NoneBot", parents=[parent])
    sub.add_parser("install-plugin", parents=[parent]).add_argument("name")
    sub.add_parser("install-zip", parents=[parent]).add_argument("path")
    sub.add_parser("list-plugins", parents=[parent])
    sub.add_parser("open-env", parents=[parent])
    sub.add_parser("open-plugins", parents=[parent])
    sub.add_parser("info", parents=[parent])
    args = p.parse_args(argv)
    if not args.cmd:
        p.print_help()
        return 1
    _run(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
