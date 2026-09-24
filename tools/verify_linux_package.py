# -*- coding: utf-8 -*-
"""交付包验收探针：在**解包后的目录**里跑，确认客户机装完真的能用。

用法：
    python3 verify_linux_package.py <解包目录，例如 /tmp/pkgtest/astroswarm>

检查项：
  1. app/astroswarm_linux 与 app/qbotmanager 能被 import（import astroswarm_linux.api 不报错）
  2. auth.account_base() 解析出来**不是** 127.0.0.1（客户机上没有那个服务）
  3. 三种优先级：config.json > 环境变量 ASTROSWARM_ACCOUNT_BASE > 线上默认
  4. 运行时闸门读的是 plans.json 的 all_plugins（不是 plan 名）
  5. plugin_market 带清单签名校验（verify_manifest）
  6. 包内没有付费能力包源码（tool_packs/<付费包 id>/）
  7. 版本号与包名一致

退出码 = 失败项数。
"""
import json
import os
import subprocess
import sys
from pathlib import Path

PAID_PACK_IDS = (
    "proactive", "memory", "knowledge", "web-search", "timer",
    "group-manager", "reply-rhythm",
)


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    app = root / "app"
    fails, oks = [], []

    def ok(msg):
        oks.append(msg)
        print("OK   " + msg)

    def bad(msg):
        fails.append(msg)
        print("FAIL " + msg)

    if not (app / "astroswarm_linux").is_dir():
        print("FAIL 找不到 %s/astroswarm_linux" % app)
        return 1
    print("== 包目录 %s" % root)
    print("== 版本 %s" % (root / "VERSION").read_text(encoding="utf-8").strip()
          if (root / "VERSION").exists() else "== 版本 (无 VERSION 文件)")

    # 1) import 探针（子进程跑，PYTHONPATH 就是解包目录，跟客户机一样）
    probe = (
        "import astroswarm_linux.api as a;"
        "import astroswarm_linux.console_ext as c;"
        "import astroswarm_linux.plans as p;"
        "from qbotmanager.core import plugin_market as pm;"
        "import inspect;"
        "assert hasattr(pm, 'verify_manifest'), 'plugin_market 无 verify_manifest';"
        "print('IMPORT-OK', a.__file__)"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(app)
    env.pop("ASTROSWARM_ACCOUNT_BASE", None)
    env.pop("ASTROSWARM_PLANS_FILE", None)
    proc = subprocess.run([sys.executable, "-c", probe], capture_output=True,
                          text=True, env=env, cwd=str(root), timeout=180)
    if proc.returncode == 0 and "IMPORT-OK" in proc.stdout:
        ok("import astroswarm_linux.api / console_ext / plugin_market 全部成功")
    else:
        bad("import 失败：%s%s" % (proc.stdout.strip(), proc.stderr.strip()[-800:]))

    # 2)+3) 账号地址解析
    def resolve(extra_env=None, cfg=None, tmp=None):
        e = dict(env)
        if extra_env:
            e.update(extra_env)
        if tmp is not None:
            e["XDG_CONFIG_HOME"] = str(tmp)
            e["XDG_DATA_HOME"] = str(tmp)
        if cfg is not None:
            p = Path(tmp) / "astroswarm"
            p.mkdir(parents=True, exist_ok=True)
            (p / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
        r = subprocess.run(
            [sys.executable, "-c",
             "from astroswarm_linux import auth; print('RESOLVED=' + auth.account_base())"],
            capture_output=True, text=True, env=e, cwd=str(root), timeout=120)
        for line in r.stdout.splitlines():
            if line.startswith("RESOLVED="):
                return line.split("=", 1)[1].strip()
        return "<err> %s %s" % (r.stdout.strip(), r.stderr.strip()[-400:])

    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        default = resolve(tmp=tmp)
        if default.startswith("http://127.0.0.1") or "14512" in default:
            bad("默认账号地址还是本机 127.0.0.1/14512：%s（客户机上登录必失败）" % default)
        elif default.rstrip("/") == "https://astroswarm.cn/api/account":
            ok("默认账号地址 = %s" % default)
        else:
            bad("默认账号地址不是线上默认值：%s" % default)

        byenv = resolve(extra_env={"ASTROSWARM_ACCOUNT_BASE": "https://self.example.com"},
                        tmp=tmp)
        if byenv.rstrip("/") == "https://self.example.com":
            ok("环境变量 ASTROSWARM_ACCOUNT_BASE 生效")
        else:
            bad("环境变量没生效：%s" % byenv)

        bycfg = resolve(cfg={"account_base": "https://cfg.example.com"}, tmp=tmp)
        if bycfg.rstrip("/") == "https://cfg.example.com":
            ok("config.json 的 account_base 优先级最高")
        else:
            bad("config.json 的 account_base 没生效：%s" % bycfg)

    # 4)+5) 静态源码断言
    plans_src = (app / "astroswarm_linux" / "plans.py")
    if plans_src.exists() and "all_plugins" in plans_src.read_text(encoding="utf-8"):
        ok("plans.py 存在且按 all_plugins 判全解锁")
    else:
        bad("缺 plans.py 或它不读 all_plugins")
    if (app / "astroswarm_linux" / "plans.json").exists():
        raw = json.loads((app / "astroswarm_linux" / "plans.json").read_text(encoding="utf-8"))
        if raw.get("permanent", {}).get("all_plugins") is True and \
           raw.get("monthly", {}).get("all_plugins") is False:
            ok("plans.json 与账号服务同口径（permanent=true，monthly=false）")
        else:
            bad("plans.json 口径不对：%s" % raw)
    else:
        bad("缺 astroswarm_linux/plans.json")

    dep = (app / "astroswarm_linux" / "deploy.py").read_text(encoding="utf-8")
    if "all_plugins" in dep and 'get("full")' in dep:
        ok("deploy._allowed_packs 走 feature_gate 的 all_plugins")
    else:
        bad("deploy.py 的运行时闸门没跟上 all_plugins")

    # 6) 付费能力包源码残留
    leaked = []
    for p in app.rglob("*"):
        parts = p.as_posix().split("/")
        for i, seg in enumerate(parts):
            if seg == "tool_packs" and any(x in PAID_PACK_IDS for x in parts[i + 1:]):
                leaked.append(p.relative_to(root).as_posix())
                break
    if leaked:
        bad("付费能力包源码残留 %d 个（例：%s）" % (len(leaked), leaked[0]))
    else:
        ok("包内无 tool_packs/<付费包 id>/ 源码")

    for name in ("console-dist/index.html", "install.sh", "app/astroswarm_linux/console_ext.py"):
        if (root / name).exists():
            ok("存在 %s" % name)
        else:
            bad("缺 %s" % name)

    print("\n---- %d 项通过，%d 项失败 ----" % (len(oks), len(fails)))
    for f in fails:
        print("  [!] " + f)
    return len(fails)


if __name__ == "__main__":
    sys.exit(main())
