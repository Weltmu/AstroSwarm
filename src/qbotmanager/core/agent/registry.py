"""工具注册表：注册/卸载/加载工具包/执行（含权限、通道与动作回执校验）。

2026-09-27（AI 插件工坊地基）：
- ``schemas(platform)`` 按 manifest.adapters 裁剪：微信里不会再喂 QQ 专属工具；
- ``execute`` 在通道不匹配时直接拒绝（"叫了没反应"变成模型看得见的错误）；
- 执行完按 ``ctx.effect_results`` 校验"工具说成功、动作其实失败"，把真相写回结果；
- ``load_pack`` 记录包元信息（版本/目录/来源/沙箱标记），给工坊的查重与回滚用。
"""
import importlib.util
from pathlib import Path

from .tool import (
    ToolContext,
    ToolPackManifest,
    ToolPermissionError,
    ToolSpec,
    ToolUnavailableError,
    adapters_allow,
    merge_effect_report,
)


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, ToolSpec] = {}
        self._behaviors: dict[str, dict] = {}
        self._behavior_pack_ids: dict[str, str] = {}
        self._packs: dict[str, dict] = {}

    # ---- 注册 / 查询 ----
    def register(self, spec: ToolSpec) -> None:
        self._tools[spec.name] = spec

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)

    def get(self, name: str):
        return self._tools.get(name)

    def names(self) -> set:
        """当前已注册的全部工具名（工坊查重用）。"""
        return set(self._tools)

    def tools_of(self, pack_id: str) -> list:
        return [n for n, s in self._tools.items() if s.pack_id == pack_id]

    def packs(self) -> dict:
        """已加载能力包元信息：id → {version, dir, kind, sandbox, tools...}。"""
        return {k: dict(v) for k, v in self._packs.items()}

    def pack_meta(self, pack_id: str) -> dict | None:
        meta = self._packs.get(pack_id)
        return dict(meta) if meta else None

    def behavior(self, behavior_id: str) -> dict | None:
        """按 id 取已注册行为配置（未安装/被冻结返回 None）。"""
        return self._behaviors.get(behavior_id)

    def behaviors(self) -> dict:
        return dict(self._behaviors)

    def schemas(self, platform: str = "") -> list:
        """按通道裁剪后的工具清单；platform 为空 = 不过滤（向后兼容）。"""
        return [
            spec.schema()
            for spec in self._tools.values()
            if adapters_allow(spec.adapters, platform)
        ]

    def execute(self, name: str, args: dict, ctx: ToolContext) -> str:
        spec = self.check(name, ctx)
        if spec.sandbox:
            raise ToolUnavailableError(
                f"沙箱工具 {name} 必须走 execute_async（独立子进程 + 动作校验）")
        result = str(spec.handler(ctx, args or {}))
        return merge_effect_report(result, ctx.effect_results)

    def check(self, name: str, ctx: ToolContext) -> ToolSpec:
        """执行前检查：工具存在 + 通道匹配 + 权限足够；返回 ToolSpec。"""
        spec = self._tools.get(name)
        if spec is None:
            raise KeyError(f"未注册工具: {name}")
        if not adapters_allow(spec.adapters, ctx.platform):
            raise ToolUnavailableError(
                f"工具 {name} 不支持当前通道 {ctx.source or '未知'}")
        for perm in spec.permissions:
            if not ctx.can(perm):
                raise ToolPermissionError(f"缺少权限: {perm}")
        return spec

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
        self._packs[manifest.id] = {
            "id": manifest.id,
            "name": manifest.name,
            "version": manifest.version,
            "kind": manifest.kind,
            "dir": str(pack_dir),
            "adapters": list(manifest.adapters),
            "permissions": list(manifest.permissions),
            "sandbox": bool(manifest.sandbox),
            "tools": [str(t.get("name") or "") for t in manifest.tools],
        }
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
                    adapters=list(tool.get("adapters") or manifest.adapters or []),
                    sandbox=bool(tool.get("sandbox", manifest.sandbox)),
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
        self._packs.pop(pack_id, None)
        return len(names) + len(behaviors)
