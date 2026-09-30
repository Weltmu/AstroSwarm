# -*- coding: utf-8 -*-
"""生成离线载荷的第三方许可清单（offline/THIRD_PARTY_NOTICES.txt）。

用法：python tools/gen_third_party_notices.py <node_modules 目录> <输出文件>
"""
import json
import sys
from pathlib import Path

FIXED = [
    ("Python (embeddable runtime)", "3.12.10", "PSF-2.0", "https://www.python.org/"),
    ("Node.js (portable runtime)", "22.23.2", "MIT", "https://nodejs.org/"),
]


def _license_of(pkg: dict) -> str:
    lic = pkg.get("license")
    if isinstance(lic, dict):
        return str(lic.get("type") or "")
    if isinstance(lic, str):
        return lic
    lics = pkg.get("licenses")
    if isinstance(lics, list):
        return " OR ".join(str(x.get("type") if isinstance(x, dict) else x) for x in lics)
    return ""


def main() -> int:
    nm = Path(sys.argv[1])
    out = Path(sys.argv[2])
    entries = []
    seen = set()
    for pj in nm.rglob("package.json"):
        rel = pj.relative_to(nm)
        if "node_modules" in rel.parts[:-1]:
            # 只收集包根目录的 package.json（跳过包内子路径 shim）
            continue
        try:
            data = json.loads(pj.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        name = data.get("name")
        if not name or name in seen:
            continue
        seen.add(name)
        lic = _license_of(data)
        text = ""
        base = pj.parent
        for cand in ("LICENSE", "LICENSE.md", "LICENSE.txt", "license", "LICENCE", "COPYING"):
            f = base / cand
            if f.is_file():
                try:
                    text = f.read_text(encoding="utf-8", errors="replace")[:20000]
                except OSError:
                    text = ""
                break
        entries.append((name, str(data.get("version") or ""), lic or "(see package)", text))

    lines = [
        "AstroSwarm 星群 · 第三方组件许可清单",
        "=" * 60,
        "",
        "本程序随安装包分发以下第三方组件。全部为宽松许可（MIT / Apache-2.0 / BSD / ISC / PSF 等）。",
        "下列许可文本摘自各组件的发行包；如与上游发布不一致，以上游为准。",
        "",
        "明确未内置：@tencent-connect/qqbot-connector（UNLICENSED 专有包）、"
        "@deepseek-ai/libreoffice-kit*（MPL-2.0）、@img/sharp*（含 LGPL-3.0-or-later）。",
        "",
        "---- 组件总表 ----",
    ]
    for name, ver, lic, _t in FIXED:
        lines.append(f"{name}\t{ver}\t{lic}")
    for name, ver, lic, _t in sorted(entries):
        lines.append(f"{name}\t{ver}\t{lic}")
    lines.append("")
    lines.append("---- 许可原文 ----")
    for name, ver, lic, text in sorted(entries):
        if not text:
            continue
        lines.append("")
        lines.append("=" * 60)
        lines.append(f"{name} {ver} — {lic}")
        lines.append("=" * 60)
        lines.append(text)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"components={len(entries)} size={out.stat().st_size/1024:.0f}KB -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
