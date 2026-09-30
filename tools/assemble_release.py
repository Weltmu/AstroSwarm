# -*- coding: utf-8 -*-
"""把 dist/ 的产物组装成可发布的四个交付物（Windows 安装版/便携版 + 校验值）。

用法：
    python tools/assemble_release.py            # 组装（版本号自动取 APP_VERSION）
    python tools/assemble_release.py --no-zip   # 只更新客户目录 + 安装版副本，不重打便携 zip

产物（dist_package/）：
    AstroSwarm_Setup_<版本>.exe                     安装版
    AstroSwarm_v<版本>_Portable_<日期>.zip           便携版（客户目录整包）
    AstroSwarm_客户版/                              便携版解压后的样子
        AstroSwarm.exe / uninstall.exe / 使用说明.docx / offline/（内置载荷，零联网部署）

为什么便携版也要带 offline/：
    安装版是 Inno 把载荷铺到 {app}\\offline；便携版没有安装器，只能自带。
    少了它，便携版首次部署就会退回去联网下载 Python + pip 装依赖。
"""
import argparse
import hashlib
import shutil
import time
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DIST = REPO / "dist"
PKG = REPO / "dist_package"
CLIENT = PKG / "AstroSwarm_客户版"
OFFLINE = REPO / "offline"

# 便携版只带 Windows 载荷：Linux 的 wheels 放在同一个 offline/ 里，别一起塞进去
OFFLINE_ROOTS = ["python-*-embed-amd64.zip", "node-*-win-x64.zip",
                 "THIRD_PARTY_NOTICES.txt", "manifest.json"]
OFFLINE_DIRS = ["wheels", "dsh"]


def sha256(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def app_version() -> str:
    for line in (REPO / "src" / "qbotmanager" / "__init__.py").read_text(
            encoding="utf-8").splitlines():
        if line.startswith("APP_VERSION"):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("[x] 拿不到 APP_VERSION")


def copy_offline(dst_root: Path) -> int:
    """把 Windows 离线载荷复制进便携版目录；返回复制文件数。"""
    dst_root.mkdir(parents=True, exist_ok=True)
    count = 0
    for pattern in OFFLINE_ROOTS:
        for src in sorted(OFFLINE.glob(pattern)):
            if src.is_file():
                shutil.copy2(src, dst_root / src.name)
                count += 1
    for name in OFFLINE_DIRS:
        src_dir = OFFLINE / name
        if not src_dir.is_dir():
            continue
        dst_dir = dst_root / name
        dst_dir.mkdir(parents=True, exist_ok=True)
        for src in sorted(src_dir.rglob("*")):
            if src.is_file():
                target = dst_dir / src.relative_to(src_dir)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, target)
                count += 1
    return count


def make_zip(folder: Path, out: Path) -> None:
    out.unlink(missing_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as zf:
        for path in sorted(folder.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(folder.parent).as_posix())


def main() -> int:
    ap = argparse.ArgumentParser(description="组装发布交付物")
    ap.add_argument("--no-zip", action="store_true", help="不重打便携版 zip")
    args = ap.parse_args()

    version = app_version()
    stamp = time.strftime("%Y%m%d")
    print(f"==> 版本 {version}（{stamp}）")

    for name in ("AstroSwarm.exe", "uninstall.exe"):
        src = DIST / name
        if not src.exists():
            print(f"[x] 缺 {src}，先跑 PyInstaller")
            return 2
        shutil.copy2(src, CLIENT / name)
        print(f"    客户目录更新 {name} {src.stat().st_size} 字节")

    setup_src = DIST / "AstroSwarm_Setup.exe"
    if setup_src.exists():
        setup_dst = PKG / f"AstroSwarm_Setup_{version}.exe"
        shutil.copy2(setup_src, setup_dst)
        print(f"    安装版 {setup_dst.name} {setup_dst.stat().st_size} 字节 "
              f"sha256={sha256(setup_dst)[:16]}...")
    else:
        print("    [!] 没找到 dist/AstroSwarm_Setup.exe（Inno 还没编译）")

    copied = copy_offline(CLIENT / "offline")
    print(f"    内置离线载荷 {copied} 个文件 → 客户目录\\offline")

    zip_dst = PKG / f"AstroSwarm_v{version}_Portable_{stamp}.zip"
    if args.no_zip:
        print("    （--no-zip：没重打便携版）")
    else:
        print("    打便携版 zip（300MB 上下，要一两分钟）...")
        make_zip(CLIENT, zip_dst)
        print(f"    便携版 {zip_dst.name} {zip_dst.stat().st_size} 字节 "
              f"sha256={sha256(zip_dst)[:16]}...")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
