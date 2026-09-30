# -*- coding: utf-8 -*-
"""生成 / 校验 Windows 离线载荷清单（offline/manifest.json）。

为什么要有这个脚本：
    installer/AstroSwarm_setup.iss 用 `FileExists(offline/manifest.json)` 判断
    「离线载荷打好了没」——没这个文件，整段载荷不会进安装包，客户装完还得联网下 Python。
    载荷本体（Python embed / Node / wheels / dsh）由各构建脚本产出，这里只做两件事：
      1) 校验四件套齐不齐（缺哪个直接报错，不生成清单）；
      2) 算 sha256 写一份 manifest.json（发版留痕，日后能核对有没有被人换过）。

用法：
    python tools/build_offline_bundle.py            # 校验 + 写清单
    python tools/build_offline_bundle.py --check    # 只校验不写

载荷组成（offline/）：
    python-3.12.10-embed-amd64.zip  Windows 内置 Python
    node-v22.23.2-win-x64.zip       Windows 内置 Node.js
    wheels/*.whl                    NoneBot 依赖（纯离线安装）
    dsh/payload.tar.gz              dsh（腾讯侧插件运行时）离线包
    THIRD_PARTY_NOTICES.txt         第三方许可声明
"""
import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OFFLINE = REPO / "offline"


def sha256(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def _glob_one(pattern: str, label: str, problems: list):
    hits = [h for h in sorted(OFFLINE.glob(pattern)) if h.is_file()]
    if not hits:
        problems.append(f"缺 {label}（{pattern}）")
        return None
    return hits[-1]


def main() -> int:
    ap = argparse.ArgumentParser(description="生成 Windows 离线载荷清单")
    ap.add_argument("--check", action="store_true", help="只校验，不写 manifest.json")
    ap.add_argument("--version", default=None, help="写进清单的客户端版本")
    args = ap.parse_args()

    if not OFFLINE.is_dir():
        print(f"[x] 没有离线载荷目录：{OFFLINE}", file=sys.stderr)
        return 2

    problems = []
    python_zip = _glob_one("python-*-embed-amd64.zip", "内置 Python", problems)
    node_zip = _glob_one("node-*-win-x64.zip", "内置 Node.js", problems)
    dsh_payload = _glob_one("dsh/payload.tar.gz", "dsh 离线包", problems)
    notices = _glob_one("THIRD_PARTY_NOTICES.txt", "第三方许可声明", problems)
    wheels_dir = OFFLINE / "wheels"
    wheels = sorted(wheels_dir.glob("*.whl")) if wheels_dir.is_dir() else []
    if len(wheels) < 20:
        problems.append(f"wheels 太少（{len(wheels)} 个），离线装依赖会失败")

    if problems:
        print("[x] 离线载荷不完整，不生成清单（安装包会退回联网部署）：")
        for item in problems:
            print("    -", item)
        return 1

    version = args.version
    if not version:
        init_src = (REPO / "src" / "qbotmanager" / "__init__.py").read_text(encoding="utf-8")
        for line in init_src.splitlines():
            if line.startswith("APP_VERSION"):
                version = line.split("=", 1)[1].strip().strip('"').strip("'")
                break

    items = {"python": python_zip, "node": node_zip,
             "dsh": dsh_payload, "notices": notices}
    manifest = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "app_version": version,
        "wheels": {
            "count": len(wheels),
            "names_sha256": hashlib.sha256(
                "\n".join(w.name for w in wheels).encode("utf-8")).hexdigest(),
        },
    }
    total = sum(w.stat().st_size for w in wheels)
    for key, path in items.items():
        size = path.stat().st_size
        total += size
        manifest[key] = {"file": path.relative_to(OFFLINE).as_posix(),
                         "size": size, "sha256": sha256(path)}
    manifest["total_bytes"] = total

    print(f"==> 离线载荷 {version}：Python {manifest['python']['size'] // 1048576}MB、"
          f"Node {manifest['node']['size'] // 1048576}MB、wheels {len(wheels)} 个、"
          f"dsh {manifest['dsh']['size'] // 1048576}MB、合计 {total / 1048576:.1f}MB")

    if args.check:
        print("    （--check：只校验，没写清单）")
        return 0

    out = OFFLINE / "manifest.json"
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"==> 清单已写：{out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
