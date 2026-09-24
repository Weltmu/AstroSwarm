# -*- coding: utf-8 -*-
"""生成「可以公开的」源码树。

⚠ 关键：**不要把现有仓库直接 push 到公开地址** —— 私有文件与敏感串仍然存在于
   历史提交里，删文件/改文件只是新增了一个提交，历史照样能翻出来。
   正确做法：用本脚本导出干净的工作树，再在一个**全新的空仓库**里做首次提交。

用法：
    python tools/export_public.py [输出目录]      # 默认 build/public-src

导出规则（只取被 git 跟踪的文件）：
    * 服务器运维 / 授权服务 / 语料工具 / 本机脚本
    * 全部能力包（含此前的付费包：proactive / memory / knowledge / web-search /
      timer / group-manager / reply-rhythm）自 2026-09 起随主仓库开源，不再排除
    * _private/、__pycache__、*.pyc、*.bak*、*.old
导出后自动复扫一遍敏感串，命中即非 0 退出。
"""
import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

PRIVATE_RE = re.compile(
    r"^(?:"
    r"server_sync/|license_server/|_private/|docs/superpowers/|"
    r"server_app_pull\.py|serve_pull\.py|"
    r"tools/astroswarm_nginx\.conf|"
    # 语料 / 对话归档工具（内部数据流水线）
    r"tools/export_training_corpus\.py|tools/prepare_training_set\.py|"
    r"tools/analyze_corpus\.py|tools/audit_conversations\.py|tools/clean_member_hint\.py|"
    # 授权服务与服务器运维脚本
    r"tools/backup_license\.sh|tools/pubkey\.sh|tools/verify_license_server\.sh|"
    r"tools/restore_license_db\.py|tools/patch_server_license\.py|tools/license_patch\.py|"
    r"tools/verify_recovered\.py|"
    r"tools/server_brand_rename\.sh|tools/spawn_deploy\.py|tools/video_patch\.py|"
    r"tools/strip_meta\.py|tools/rebuild_zips\.py|tools/assemble_dist\.py|"
    r"tools/build_linux_package\.py|tools/build_nuitka_linux\.sh"
    r")"
)

# 2026-09 起插件全部免费开源（用户决定），原先排除付费能力包源码的规则已停用。
# 这里保留一个永不匹配的正则：将来若又要排除，把原来的表达式贴回来即可。
PAID_PACK_RE = re.compile(r"(?!)")

JUNK = {".write_test.txt", "tools/.release_guard.txt"}

# 导出后复扫：通用敏感模式（本机专属的串放在 tools/.release_guard.txt，不進仓库）
SCAN_PATTERNS = [
    ("PEM 私钥/证书", r"-----BEGIN[A-Z ]*(?:PRIVATE KEY|CERTIFICATE)"),
    ("SSH 私钥/公钥串", r"ssh-(?:rsa|ed25519)\s+AAAA"),
    ("OpenAI 风格密钥", r"\bsk-[A-Za-z0-9_\-]{20,}"),
    ("GitHub token", r"\bgh[pousr]_[A-Za-z0-9]{20,}"),
    ("云厂商 AK", r"\b(?:AKID|LTAI)[A-Za-z0-9]{12,}"),
    ("Windows 个人目录", r"[Cc]:[\\/]Users[\\/][A-Za-z0-9_.\-]+[\\/]"),
]
SKIP_SUFFIX = {".png", ".jpg", ".jpeg", ".ico", ".ttf", ".woff", ".woff2", ".zip", ".gz", ".db", ".exe"}


def tracked_files():
    raw = subprocess.run(
        ["git", "-c", "core.quotePath=false", "ls-files", "-z"],
        cwd=REPO, capture_output=True, check=True,
    ).stdout
    for item in raw.split(b"\0"):
        if item:
            yield item.decode("utf-8")


def guard_patterns():
    """本机专属敏感串（tools/.release_guard.txt，一行一条，不进仓库）。"""
    extra = []
    guard = REPO / "tools" / ".release_guard.txt"
    if guard.exists():
        for line in guard.read_text(encoding="utf-8").splitlines():
            item = line.strip()
            if item and not item.startswith("#"):
                extra.append(item)
    return extra


CONSOLE_KEEP_TOP = ("index.html", "vite.config.js", "package.json")
CONSOLE_SKIP_NAME = ("node_modules", "__pycache__", ".vite")


def copy_console(src: Path, out: Path) -> int:
    """把网页控制台前端源码（Linux 无头版的网页界面）拷进公开树。

    控制台的规范源码在官网仓库（QBotManager_website/console），这里只做同步，
    不改变它的归属；没找到就跳过并提示，不阻塞导出。
    """
    if not src.is_dir():
        print(f"[!] 没找到控制台源码目录 {src}，跳过（用 --console-src 指定）")
        return 0
    dst = out / "console"
    count = 0
    for name in CONSOLE_KEEP_TOP:
        item = src / name
        if item.is_file():
            (dst / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, dst / name)
            count += 1
    for path in sorted(src.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(src)
        if any(part in CONSOLE_SKIP_NAME for part in rel.parts):
            continue
        if ".bak" in path.name or path.name.endswith((".orig", ".rej", ".old")):
            continue
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        count += 1
    print(f"==> 控制台前端源码：{count} 个文件（来自 {src}）")
    return count


def main() -> int:
    ap = argparse.ArgumentParser(description="导出可以公开的源码树")
    ap.add_argument("out", nargs="?", default=str(REPO / "build" / "public-src"))
    ap.add_argument("--console-src", default=str(REPO.parent / "QBotManager_website" / "console"),
                    help="网页控制台前端源码目录（默认取仓库同级的 QBotManager_website/console）")
    args = ap.parse_args()
    out = Path(args.out).resolve()
    if out.exists():
        shutil.rmtree(out)
    kept, skipped = 0, []
    for rel in tracked_files():
        if rel in JUNK or PRIVATE_RE.match(rel) or PAID_PACK_RE.search(rel):
            skipped.append(rel)
            continue
        src = REPO / rel
        if not src.is_file():
            print(f"[!] git 索引里有、工作区却没有：{rel}")
            continue
        dst = out / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        kept += 1

    print(f"==> 导出到 {out}")
    print(f"    收录 {kept} 个文件，排除 {len(skipped)} 个")
    for item in sorted(skipped)[:40]:
        print("     -", item)
    if len(skipped) > 40:
        print(f"     …… 另有 {len(skipped) - 40} 个")

    copy_console(Path(args.console_src), out)

    print("==> 复扫敏感串")
    hits = []
    patterns = SCAN_PATTERNS + [("本机专属串", re.escape(s)) for s in guard_patterns()]
    for path in sorted(out.rglob("*")):
        if not path.is_file() or path.suffix.lower() in SKIP_SUFFIX:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        rel = path.relative_to(out).as_posix()
        for label, pat in patterns:
            for m in re.finditer(pat, text):
                line_no = text.count("\n", 0, m.start()) + 1
                hits.append(f"{rel}:{line_no}: {label}: {m.group(0)[:80]}")
    if hits:
        print("!! 发现可疑内容，先处理再发布：")
        for item in hits[:40]:
            print("   ", item)
        return 1
    print("    干净")
    print("\n下一步（在导出目录里执行）：")
    print("    git init -b main && git add -A && git commit -m 'AstroSwarm 星群：客户端与运行框架源码'")
    print("    git remote add origin <公开仓库地址> && git push -u origin main")
    return 0


if __name__ == "__main__":
    sys.exit(main())
