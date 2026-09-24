"""工具注册表：注册/卸载/加载工具包/执行（含权限校验）。"""
import importlib.util
from pathlib import Path

from .tool import ToolContext, ToolPackManifest, ToolPermissionError, ToolSpec


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, ToolSpec] = {}
        self._behaviors: dict[str, dict] = {}
        self._behavior_pack_ids: dict[str, str] = {}

    def register(self, spec: ToolSpec) -> None:
        self._tools[spec.name] = spec

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)

    def get(self, name: str):
        return self._tools.get(name)

    def behavior(self, behavior_id: str) -> dict | None:
        """按 id 取已注册行为配置（未安装/被冻结返回 None）。"""
        return self._behaviors.get(behavior_id)

    def behaviors(self) -> dict:
        return dict(self._behaviors)

    def schemas(self) -> list:
        return [spec.schema() for spec in self._tools.values()]

    def execute(self, name: str, args: dict, ctx: ToolContext) -> str:
        spec = self._tools.get(name)
        if spec is None:
            raise KeyError(f"未注册工具: {name}")
        for perm in spec.permissions:
            if not ctx.can(perm):
                raise ToolPermissionError(f"缺少权限: {perm}")
        return str(spec.handler(ctx, args or {}))

    def load_pack(self, pack_dir) -> int:
        pack_dir = Path(pack_dir)
        if not (pack_dir / "manifest.json").exists():
            # 兼容 zip 带顶层目录的情况：找第一层子目录
            for sub in pack_dir.iterdir():
                if sub.is_dir() and (sub / "manifest.json").exists():
                    pack_dir = sub
                    break
            else:
                raise ValueError(f"缺少 manifest.json: {pack_dir}")
        manifest = ToolPackManifest.parse(
            (pack_dir / "manifest.json").read_text(encoding="utf-8")
        )
        count = 0
        if manifest.kind == "behavior-pack" and manifest.behavior:
            self._behaviors[manifest.id] = manifest.behavior
            self._behavior_pack_ids[manifest.id] = manifest.id
            count += 1
        if manifest.kind in ("persona-pack", "agent-pack") and manifest.bundled_packs:
            # 人设包/智能体包可捆绑行为包：装包 = 行为一起生效
            for bundled_id in manifest.bundled_packs:
                bundled_dir = pack_dir / "bundled" / bundled_id
                if (bundled_dir / "manifest.json").exists():
                    try:
                        count += self.load_pack(bundled_dir)
                        # 捆绑行为归所属包所有：卸载/冻结时一并移除
                        self._behavior_pack_ids[bundled_id] = manifest.id
                    except Exception:  # noqa: BLE001 —— 单个捆绑包失败不拖垮人设包
                        continue
        for tool in manifest.tools:
            name = tool["name"]
            mod_path = pack_dir / "tools" / f"{name}.py"
            spec = importlib.util.spec_from_file_location(
                f"{manifest.id}_{name}", mod_path
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            self.register(
                ToolSpec(
                    name=name,
                    description=tool["description"],
                    parameters=tool["parameters"],
                    permissions=tool.get("permissions") or [],
                    handler=getattr(module, "handle"),
                    lifecycle=tool.get("lifecycle", "none"),
                    pack_id=manifest.id,
                )
            )
            count += 1
        return count

    def unload_pack(self, pack_id: str) -> int:
        names = [n for n, s in self._tools.items() if s.pack_id == pack_id]
        for name in names:
            self.unregister(name)
        behaviors = [
            bid for bid, owner in self._behavior_pack_ids.items() if owner == pack_id
        ]
        for bid in behaviors:
            self._behaviors.pop(bid, None)
            self._behavior_pack_ids.pop(bid, None)
        return len(names) + len(behaviors)
