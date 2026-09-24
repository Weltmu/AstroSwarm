"""Headless CLI：status / serve 占位。"""
import argparse
import sys
from pathlib import Path

from . import headless_config, platform_info


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(prog="astroswarm")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("status", help="显示平台信息")
    serve = sub.add_parser("serve", help="启动控制 API（M2）")
    serve.add_argument("--port", type=int, default=7860)
    serve.add_argument("--host", default="127.0.0.1")
    install = sub.add_parser("install", help="初始化配置（可选安装 systemd 自启）")
    install.add_argument("--port", type=int, default=7860)
    install.add_argument("--systemd", action="store_true")
    sub.add_parser("deploy", help="部署 Linux 机器人运行时（venv + 依赖）")
    args = parser.parse_args(argv)
    if args.cmd == "status":
        print(
            f"astroswarm headless · machine_id={platform_info.machine_id()}"
        )
        return 0
    if args.cmd == "serve":
        import uvicorn

        from .api import app

        print(f"AstroSwarm headless API on http://{args.host}:{args.port}")
        uvicorn.run(app, host=args.host, port=args.port, log_level="info")
        return 0
    if args.cmd == "install":
        cfg = headless_config.load()
        cfg["port"] = args.port
        headless_config.save(cfg)
        print(f"配置已写入 {headless_config.config_path()}")
        if args.systemd:
            from .autostart import install as sys_install
            from .autostart import unit_text

            sys_install(
                "astroswarm.service",
                unit_text(Path("/opt/astroswarm"), args.port),
                Path("/etc/systemd/system"),
                enable=True,
            )
            print("systemd 自启已安装：astroswarm.service")
        return 0
    if args.cmd == "deploy":
        from .deploy import ensure_bot

        ensure_bot(log=print)
        print("机器人运行时部署完成")
        return 0
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
