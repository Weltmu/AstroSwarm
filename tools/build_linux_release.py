# -*- coding: utf-8 -*-
"""打「Linux 无头端」客户安装包（astroswarm-linux-<版本>.tar.gz）。

为什么要有这个脚本：
    给客户下载的包必须是「可复现的一条命令」打出来的，并且打完自动做一次交付物自检，
    把「包缺文件 / 账号地址写死 / 混进内部文件 / 敏感串」这类缺陷挡在发布之前。

用法（在仓库根目录）：
    python tools/build_linux_release.py
    python tools/build_linux_release.py --version 0.1.3 --console-dist <路径> --out <目录>

产物：
    <out>/astroswarm-linux-<版本>.tar.gz
    <out>/astroswarm-linux-<版本>.tar.gz.sha256

包内结构（install.sh 能直接认）：
    astroswarm/install.sh
    astroswarm/console-dist/{index.html,assets/...}
    astroswarm/app/astroswarm_linux/*.py
    astroswarm/app/qbotmanager/**

排除规则（与 tools/export_public.sh 一致，另外更严：嵌套的也算）：
    * 内部能力包源码：任何 tool_packs/ 之下的 <包 id>/（含 eva/bundled/reply-rhythm 这种嵌套）
    * _private/、__pycache__、*.pyc/pyo、*.bak*、*.old、.git
    * 服务器私钥 / 明文 IP / 服务器路径 —— 打完再做一次全文扫描，命中直接报错不发布
"""
import argparse
import hashlib
import json
import re
import shutil
import sys
import tarfile
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# 内部能力包：**源码不进客户包**（客户从官网插件市场直接下载 zip）
PAID_PACK_IDS = {
    "proactive", "memory", "knowledge", "web-search", "timer",
    "group-manager", "reply-rhythm",
}
# 免费引流包（eva / liqinghan / qweather）可以放
FREE_PACK_IDS = {"eva", "liqinghan", "qweather"}

SKIP_DIR_NAMES = {
    "__pycache__", ".git", ".pytest_cache", ".mypy_cache", "_private",
    ".venv", "venv", "node_modules", "dist", "build", ".idea", ".vscode",
}
SKIP_SUFFIXES = (".pyc", ".pyo", ".pyd", ".spec")
SKIP_FRAGMENTS = (".bak", ".old", ".orig", ".rej")
SKIP_NAME_PREFIXES = ("~$",)

# 交付物里**绝不能出现**的东西（全文本扫描；命中即拒绝发布）
# 只放与本机部署无关的通用模式；具体到某个部署的敏感串（服务器 IP、运营者账号等）
# 放在 tools/.release_guard.txt，一行一条，不进仓库。
FORBIDDEN_TEXT = (
    "-----BEGIN",              # 任何 PEM 私钥/证书
    "ssh-rsa ",
    "OPENSSH PRIVATE KEY",
)
GUARD_FILE = REPO / "tools" / ".release_guard.txt"

# 这些词只报警告（通常只是路径说明），不阻塞
WARN_TEXT = ("/opt/",)


def _forbidden_patterns() -> tuple:
    """通用模式 + 本机敏感串（tools/.release_guard.txt，一行一条，可用 # 注释）。"""
    extra = []
    try:
        for line in GUARD_FILE.read_text(encoding="utf-8").splitlines():
            item = line.strip()
            if item and not item.startswith("#"):
                extra.append(item)
    except OSError:
        pass
    return tuple(FORBIDDEN_TEXT) + tuple(extra)


def _skip_dir(rel_parts) -> bool:
    """rel_parts 是**从被复制根算起**的完整相对路径分段（累加），
    否则 tool_packs 之下嵌套的包（如 eva/bundled/reply-rhythm）会被漏掉。"""
    if any(p in SKIP_DIR_NAMES for p in rel_parts):
        return True
    for i, part in enumerate(rel_parts):
        if part == "tool_packs":
            for later in rel_parts[i + 1:]:
                if later.lower() in PAID_PACK_IDS:
                    return True
    return False


def _skip_file(name: str, rel_parts=()) -> bool:
    low = name.lower()
    if low.endswith(SKIP_SUFFIXES):
        return True
    if any(frag in low for frag in SKIP_FRAGMENTS):
        return True
    if any(name.startswith(p) for p in SKIP_NAME_PREFIXES):
        return True
    return _skip_dir(rel_parts)


def copy_tree(src: Path, dst: Path, stats: dict, _prefix=()) -> None:
    """复制目录树（按上面的排除规则），并统计跳过了什么。"""
    dst.mkdir(parents=True, exist_ok=True)
    for entry in sorted(src.iterdir()):
        rel_parts = tuple(_prefix) + (entry.name,)
        if entry.is_dir():
            if _skip_dir(rel_parts):
                stats["skipped_dirs"].append(entry.name)
                continue
            copy_tree(entry, dst / entry.name, stats, rel_parts)
        elif entry.is_file():
            if _skip_file(entry.name, rel_parts):
                stats["skipped_files"] += 1
                continue
            shutil.copy2(entry, dst / entry.name)
            stats["copied"] += 1


def _code_lines(text: str) -> str:
    """去掉行注释后剩下的代码，用于「是否真的写死了」这种判断。

    直接搜全文会把注释里「以前写死 http://127.0.0.1:14512」这句话也算命中。
    """
    out = []
    for line in text.splitlines():
        cut = line.split("#", 1)[0]
        out.append(cut)
    return "\n".join(out)


def scan_forbidden(root: Path) -> tuple:
    """交付物自检：全文扫描禁忌字符串 + 内部能力包残留。"""
    hits, warns = [], []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        low = rel.lower()
        # 内部能力包残留（路径里出现 tool_packs/<包 id>/）
        parts = low.split("/")
        for i, part in enumerate(parts):
            if part == "tool_packs" and any(x in PAID_PACK_IDS for x in parts[i + 1:]):
                hits.append(f"{rel}: 内部能力包源码残留")
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:  # noqa: BLE001
            continue
        for needle in _forbidden_patterns():
            if needle in text:
                hits.append(f"{rel}: 命中禁忌字符串 {needle!r}")
        for needle in WARN_TEXT:
            if needle in text:
                warns.append(f"{rel}: 含 {needle}")
    return hits, warns


def check_deliverable(root: Path, version: str) -> list:
    """交付物内容自检：逐条断言。"""
    app = root / "app" / "astroswarm_linux"
    problems = []

    required = [
        "api.py", "auth.py", "console_ext.py", "deploy.py", "headless_config.py",
        "logs.py", "plans.py", "plans.json", "tools.py",
    ]
    for name in required:
        if not (app / name).exists():
            problems.append(f"缺文件 astroswarm_linux/{name}")

    core = root / "app" / "qbotmanager" / "core"
    pm = core / "plugin_market.py"
    if not pm.exists():
        problems.append("缺 qbotmanager/core/plugin_market.py")
    else:
        src = pm.read_text(encoding="utf-8")
        if "verify_manifest" not in src:
            problems.append("plugin_market.py 不是带清单签名校验（verify_manifest）的新版")

    auth_src = (app / "auth.py").read_text(encoding="utf-8") if (app / "auth.py").exists() else ""
    auth_code = _code_lines(auth_src)
    if "127.0.0.1:14512" in auth_code:
        problems.append("auth.py 仍硬编码 http://127.0.0.1:14512（客户机上登录必失败）")
    if "https://astroswarm.cn/api/account" not in auth_code:
        problems.append("auth.py 没有线上默认账号地址 https://astroswarm.cn/api/account")
    if "ASTROSWARM_ACCOUNT_BASE" not in auth_code:
        problems.append("auth.py 没有环境变量回退 ASTROSWARM_ACCOUNT_BASE")

    dep = (app / "deploy.py").read_text(encoding="utf-8") if (app / "deploy.py").exists() else ""
    if "all_plugins" not in dep:
        problems.append("deploy.py 的运行时闸门没有读 plans.json 的 all_plugins")

    tls = (app / "tools.py").read_text(encoding="utf-8") if (app / "tools.py").exists() else ""
    # 只看真正的返回语句，别被注释/文档里「以前是 plan != "none"」这句话误伤
    if re.search(r"return\s+plan\s*!=\s*[\"']none[\"']", _code_lines(tls)):
        problems.append("tools.py 还按 plan 名判全解锁（应读 all_plugins）")
    if "all_plugins" not in tls and 'get("full")' not in tls:
        problems.append("tools.py 没有读 all_plugins / feature_gate")

    init_src = (app / "__init__.py").read_text(encoding="utf-8") if (app / "__init__.py").exists() else ""
    if version not in init_src:
        problems.append(f"astroswarm_linux/__init__.py 里的 __version__ 不是 {version}")

    if not (root / "install.sh").exists():
        problems.append("缺 install.sh")
    else:
        ish = (root / "install.sh").read_text(encoding="utf-8", errors="ignore")
        for needle in ("--account-base", "ASTROSWARM_ACCOUNT_BASE", "astroswarm.cn"):
            if needle not in ish:
                problems.append(f"install.sh 没写清账号服务入口（缺 {needle}）")
    if not (root / "console-dist" / "index.html").exists():
        problems.append("缺 console-dist（控制台前端产物）")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description="打 Linux 无头端客户包")
    ap.add_argument("--version", default=None, help="版本号（默认取 astroswarm_linux/__init__.py）")
    ap.add_argument("--console-dist", default=None, help="控制台前端产物目录")
    ap.add_argument("--out", default=str(REPO / "dist_package"), help="输出目录")
    ap.add_argument("--keep-staging", action="store_true", help="保留临时目录便于排查")
    args = ap.parse_args()

    version = args.version
    if not version:
        init_src = (REPO / "src" / "astroswarm_linux" / "__init__.py").read_text(encoding="utf-8")
        for line in init_src.splitlines():
            if line.startswith("__version__"):
                version = line.split("=", 1)[1].strip().strip('"').strip("'")
                break
    if not version:
        print("[x] 拿不到版本号", file=sys.stderr)
        return 2

    console_candidates = [
        Path(args.console_dist) if args.console_dist else None,
        Path("D:/ai/QBotManager_website/console-dist"),
        REPO / "console-dist",
    ]
    console_dist = next(
        (p for p in console_candidates if p and (p / "index.html").exists()), None)
    if console_dist is None:
        print("[x] 找不到 console-dist（控制台前端产物）：用 --console-dist 指定", file=sys.stderr)
        return 2

    staging = Path(tempfile.mkdtemp(prefix="astroswarm_pkg_"))
    root = staging / "astroswarm"
    stats = {"copied": 0, "skipped_files": 0, "skipped_dirs": []}

    print(f"==> 版本 {version}")
    print(f"==> 前端产物 {console_dist}")
    copy_tree(REPO / "src" / "astroswarm_linux", root / "app" / "astroswarm_linux", stats)
    copy_tree(REPO / "src" / "qbotmanager", root / "app" / "qbotmanager", stats)
    copy_tree(console_dist, root / "console-dist", stats)
    shutil.copy2(REPO / "tools" / "install.sh", root / "install.sh")
    (root / "VERSION").write_text(version + "\n", encoding="utf-8")

    print(f"    复制 {stats['copied']} 个文件，跳过 {stats['skipped_files']} 个；"
          f"剪掉的目录：{', '.join(sorted(set(stats['skipped_dirs'])))}")

    problems = check_deliverable(root, version)
    hits, warns = scan_forbidden(root)

    # 一份机器可读的清单，方便日后核对"到底打了什么进去"
    manifest = {
        "version": version,
        "files": sorted(
            p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()),
        "excluded_paid_packs": sorted(PAID_PACK_IDS),
        "console_dist": str(console_dist),
    }
    (root / "MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    if problems or hits:
        print("\n[x] 交付物自检失败，**不发布**：")
        for p in problems:
            print("    -", p)
        for h in hits:
            print("    -", h)
        if not args.keep_staging:
            shutil.rmtree(staging, ignore_errors=True)
        return 1
    for w in warns[:10]:
        print("    [!] " + w)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    archive = out_dir / f"astroswarm-linux-{version}.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(root, arcname="astroswarm")

    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (out_dir / (archive.name + ".sha256")).write_text(
        f"{digest}  {archive.name}\n", encoding="utf-8")

    print(f"\n==> 产物 {archive}")
    print(f"    大小 {archive.stat().st_size} 字节")
    print(f"    sha256 {digest}")
    print(f"    文件数 {len(manifest['files'])}")
    if not args.keep_staging:
        shutil.rmtree(staging, ignore_errors=True)
    else:
        print(f"    暂存目录 {root} （--keep-staging）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
