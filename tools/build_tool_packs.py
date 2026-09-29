"""打包官方工具包：zip + sha256 + market.json 片段。"""
import hashlib
import json
import shutil
import zipfile
from pathlib import Path

SRC = Path("src/qbotmanager/assets/tool_packs")
OUT = Path("dist/tool_packs")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    entries = []
    for pack in sorted(SRC.iterdir()):
        manifest = json.loads((pack / "manifest.json").read_text(encoding="utf-8"))
        name = f"{manifest['id']}-{manifest['version']}.zip"
        dest = OUT / name
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
            for f in sorted(pack.rglob("*")):
                if f.is_file() and "__pycache__" not in f.parts and not f.name.endswith(".pyc"):
                    z.write(f, f.relative_to(pack))
        sha = hashlib.sha256(dest.read_bytes()).hexdigest()
        category = {
            "tool-pack": "官方能力包",
            "behavior-pack": "官方能力包",
            "persona-pack": "人设",
            "agent-pack": "智能体",
        }.get(manifest["kind"], "功能扩展")
        entries.append(
            {
                "id": manifest["id"],
                "name": manifest["name"],
                "version": manifest["version"],
                "kind": manifest["kind"],
                "category": category,
                "tier": manifest.get("tier") or (
                    "free" if manifest["kind"] in ("persona-pack", "agent-pack") else "member"
                ),
                "description": manifest["description"],
                "url": f"https://astroswarm.cn/tool_packs/{name}",
                "sha256": sha,
                "adapters": manifest["adapters"],
                "permissions": manifest["permissions"],
            }
        )
        print("built", dest, sha[:12])
    (OUT / "market_entries.json").write_text(
        json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
