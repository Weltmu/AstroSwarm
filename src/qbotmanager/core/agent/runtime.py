"""AgentRuntime：统一工具注册表 + 内置工具 + 工具包加载。"""
import os
import time
from pathlib import Path

from .registry import ToolRegistry
from .tool import ToolContext, ToolSpec

_runtime = None


class AgentRuntime:
    def __init__(self):
        self.registry = ToolRegistry()
        self._register_builtin()

    def _register_builtin(self):
        self.registry.register(
            ToolSpec(
                name="get_current_time",
                description="获取当前日期和时间",
                parameters={"type": "object", "properties": {}, "required": []},
                permissions=[],
                handler=lambda ctx, args: time.strftime("%Y-%m-%d %H:%M:%S %A"),
            )
        )

        def _knowledge_search(ctx, args):
            import json as _json

            from .. import knowledge_base

            query = str(args.get("query") or "").strip()
            root = os.environ.get("ASTROSWARM_KNOWLEDGE_DIR", "")
            results = knowledge_base.search_dir(root, query, top_k=3) if root else []
            return _json.dumps({"ok": True, "results": results},
                               ensure_ascii=False)

        self.registry.register(
            ToolSpec(
                name="knowledge_search",
                description="从本地知识库检索文档片段（用户上传的 txt/md），返回带出处的结果；"
                            "用于回答用户自己文档里的问题",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "检索问题"},
                    },
                    "required": ["query"],
                },
                permissions=[],
                handler=_knowledge_search,
            )
        )

    def load_packs(self, packs_dir, allowed=None) -> int:
        packs_dir = Path(packs_dir)
        if not packs_dir.exists():
            return 0
        total = 0
        for pack in sorted(packs_dir.iterdir()):
            if (pack / "manifest.json").exists():
                if allowed is not None:
                    try:
                        import json

                        mid = json.loads(
                            (pack / "manifest.json").read_text(encoding="utf-8")
                        ).get("id")
                    except Exception:  # noqa: BLE001
                        continue
                    if mid not in allowed:
                        continue  # 冻结：不加载，但保留文件
                try:
                    total += self.registry.load_pack(pack)
                except Exception:  # noqa: BLE001
                    continue
        return total

    def schemas(self, platform: str = "") -> list:
        """按通道裁剪的工具清单（platform 为空 = 全部，旧行为）。"""
        return self.registry.schemas(platform)

    def packs(self) -> dict:
        return self.registry.packs()

    def pack_meta(self, pack_id: str):
        return self.registry.pack_meta(pack_id)

    def tool_names(self) -> set:
        return self.registry.names()

    def behavior(self, behavior_id: str) -> dict | None:
        return self.registry.behavior(behavior_id)

    def behaviors(self) -> dict:
        return self.registry.behaviors()

    def execute(self, name: str, args: dict, ctx: ToolContext) -> str:
        return self.registry.execute(name, args, ctx)

    async def execute_async(self, name: str, args: dict, ctx: ToolContext,
                            host=None, timeout=None) -> str:
        """异步执行入口：沙箱工具走独立子进程，其余与 execute 完全一致。

        host 是主程序提供的动作执行器 ``async def host(action, params, ctx)``，
        沙箱里的插件只能通过它做事（发消息/记忆/联网等），主程序逐条校验。
        """
        spec = self.registry.check(name, ctx)
        if not spec.sandbox:
            return self.execute(name, args, ctx)
        from . import sandbox

        meta = self.registry.pack_meta(spec.pack_id) or {}
        pack_dir = meta.get("dir") or ""
        if not pack_dir:
            raise sandbox.SandboxError(
                f"沙箱工具 {name} 找不到所属插件目录（包 {spec.pack_id}）")
        try:
            return await sandbox.run_tool(
                Path(pack_dir), spec.name, args or {}, ctx, host, timeout=timeout)
        except Exception as exc:  # noqa: BLE001
            # 工坊生成的插件在真实使用中挂了：记一条，工坊页能让 AI 按这条报错改一版。
            # 记不下来也不能影响机器人本体，所以整段吞掉异常。
            try:
                from ..workshop import repair as _repair

                _repair.record_for_pack(Path(pack_dir), spec.name, str(exc))
            except Exception:  # noqa: BLE001
                pass
            raise


def get_runtime() -> AgentRuntime:
    global _runtime
    if _runtime is None:
        _runtime = AgentRuntime()
        packs = os.environ.get("ASTROSWARM_TOOL_PACKS", "")
        allowed_raw = os.environ.get("ASTROSWARM_TOOL_PACKS_ALLOWED")
        allowed = (
            None
            if allowed_raw is None
            else {x for x in allowed_raw.split(",") if x}
        )
        if packs:
            _runtime.load_packs(packs, allowed=allowed)
        personas = os.environ.get("ASTROSWARM_PERSONAS", "")
        persona_allowed_raw = os.environ.get("ASTROSWARM_PERSONAS_ALLOWED")
        persona_allowed = (
            None
            if persona_allowed_raw is None
            else {x for x in persona_allowed_raw.split(",") if x}
        )
        if personas:
            _runtime.load_packs(personas, allowed=persona_allowed)
    return _runtime
