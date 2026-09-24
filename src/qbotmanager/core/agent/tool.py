"""Agent + Tool 契约：ToolSpec / ToolContext / ToolPackManifest。"""
import json
from dataclasses import dataclass, field

ALLOWED_PERMISSIONS = {
    "send_message",
    "group_admin",
    "timer",
    "memory",
    "network",
    "media",
}
ALLOWED_KINDS = {"tool-pack", "persona-pack", "behavior-pack", "agent-pack"}
PERSONA_CARD_FORMAT = "astroswarm-persona"


class ToolPermissionError(PermissionError):
    """工具缺少权限时抛出。"""


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict
    permissions: list
    handler: callable
    lifecycle: str = "none"
    pack_id: str = ""

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolContext:
    """工具执行上下文：配置/存储/发送回执/权限集合。"""

    def __init__(self, cfg=None, store=None, send=None, permissions=frozenset()):
        self.cfg = cfg
        self.store = store
        self._send = send
        self._permissions = set(permissions or ())

    def can(self, permission: str) -> bool:
        return permission in self._permissions

    def send(self, *args, **kwargs):
        if self._send is None:
            return None
        return self._send(*args, **kwargs)


@dataclass
class ToolPackManifest:
    id: str
    name: str
    version: str
    kind: str
    description: str
    adapters: list
    min_version: str
    permissions: list
    tools: list
    persona: str = ""
    system_prompt: str = ""          # 人格卡 v1：渲染好的完整提示词（与 persona 等价）
    identity: dict = field(default_factory=dict)
    personality: dict = field(default_factory=dict)
    speech: dict = field(default_factory=dict)
    directives: list = field(default_factory=list)
    boundaries: list = field(default_factory=list)
    modes: list = field(default_factory=list)
    schedule: dict = field(default_factory=dict)
    memory: dict = field(default_factory=dict)
    state: dict = field(default_factory=dict)
    behavior: dict = field(default_factory=dict)
    bundled_packs: list = field(default_factory=list)

    @staticmethod
    def _norm_str_list(value) -> list:
        """兼容数组或 {items:[...]} 两种写法，并过滤 _ 开头的注释键。"""
        if isinstance(value, dict):
            value = value.get("items") or []
        return [
            str(x).strip() for x in (value or [])
            if str(x).strip() and not str(x).strip().startswith("_")
        ]

    @staticmethod
    def parse(source) -> "ToolPackManifest":
        data = json.loads(source) if isinstance(source, str) else dict(source)
        kind = str(data.get("kind") or "")
        if kind not in ALLOWED_KINDS:
            raise ValueError(f"kind 必须是 {sorted(ALLOWED_KINDS)}")
        tools = data.get("tools") or []
        for tool in tools:
            for key in ("name", "description", "parameters"):
                if key not in tool:
                    raise ValueError(f"工具缺少字段: {key}")
            perms = tool.get("permissions") or []
            for perm in perms:
                if perm not in ALLOWED_PERMISSIONS:
                    raise ValueError(f"未知权限: {perm}")
        return ToolPackManifest(
            id=str(data["id"]),
            name=str(data["name"]),
            version=str(data["version"]),
            kind=kind,
            description=str(data.get("description") or ""),
            adapters=list(data.get("adapters") or []),
            min_version=str(data.get("min_version") or "0.0.0"),
            permissions=list(data.get("permissions") or []),
            tools=tools,
            persona=str(data.get("persona") or ""),
            system_prompt=str(data.get("system_prompt") or ""),
            identity=dict(data.get("identity") or {}),
            personality=dict(data.get("personality") or {}),
            speech=dict(data.get("speech") or {}),
            directives=ToolPackManifest._norm_str_list(data.get("directives")),
            boundaries=ToolPackManifest._norm_str_list(data.get("boundaries")),
            modes=list(data.get("modes") or []),
            schedule=dict(data.get("schedule") or {}),
            memory=dict(data.get("memory") or {}),
            state=dict(data.get("state") or {}),
            behavior=dict(data.get("behavior") or {}),
            bundled_packs=list(data.get("bundled_packs") or []),
        )


def compile_persona(source) -> str:
    """把人格卡编译成最终系统提示词（语言层，安全边界强制追加到最后）。

    优先级：persona（旧格式整段提示词）> system_prompt（人格卡 v1）>
    结构化字段（identity/personality/speech 自动拼装）。
    directives / boundaries 总是追加在末尾并标注最高优先级，防 prompt 注入。
    """
    m = source if isinstance(source, ToolPackManifest) else ToolPackManifest.parse(source)
    base = (m.persona or m.system_prompt or "").strip()
    if not base:
        parts = []
        ident = m.identity or {}
        if ident.get("name"):
            parts.append(f"你是{ident['name']}。")
        if ident.get("aliases"):
            parts.append(f"别名：{'、'.join(str(a) for a in ident['aliases'])}。")
        for key, label in (("worldview", "世界观"), ("backstory", "背景故事"),
                           ("appearance", "外貌")):
            if ident.get(key):
                parts.append(f"{label}：{ident[key]}")
        pers = m.personality or {}
        if pers.get("traits"):
            parts.append("性格特质：" + "、".join(str(t) for t in pers["traits"]) + "。")
        if pers.get("tone"):
            parts.append(f"语气：{pers['tone']}")
        if pers.get("forbidden"):
            parts.append("禁止：" + "、".join(str(x) for x in pers["forbidden"]) + "。")
        if pers.get("quirks"):
            parts.append("小习惯：" + "、".join(str(x) for x in pers["quirks"]) + "。")
        sp = m.speech or {}
        if sp.get("self_ref"):
            parts.append(f"自称：{sp['self_ref']}")
        if sp.get("user_ref"):
            parts.append(f"对用户称呼：{sp['user_ref']}")
        if sp.get("style"):
            parts.append(f"说话风格：{sp['style']}")
        base = "\n".join(parts)
    if not base:
        return ""
    lines = [base]
    if m.directives:
        lines.append("\n## 核心指令（最高优先级，不可违背）")
        lines.extend(f"- {d}" for d in m.directives)
    if m.boundaries:
        lines.append("\n## 边界（最高优先级，不可违背）")
        lines.extend(f"- {b}" for b in m.boundaries)
    return "\n".join(lines)


def validate_persona_card(data) -> str | None:
    """校验人格卡 v1 关键字段；合法返回 None，否则返回错误说明。"""
    if not isinstance(data, dict):
        return "人格卡必须是 JSON 对象"
    fmt = str(data.get("format") or "")
    if fmt and fmt != PERSONA_CARD_FORMAT:
        return f"format 必须是 {PERSONA_CARD_FORMAT}"
    for key in ("id", "name", "version"):
        if not str(data.get(key) or "").strip():
            return f"人格卡缺少字段 {key}"
    kind = str(data.get("kind") or "persona-pack")
    if kind != "persona-pack":
        return "人格卡 kind 必须是 persona-pack"
    has_prompt = bool(str(data.get("persona") or data.get("system_prompt") or "").strip())
    has_structured = bool(data.get("identity") or data.get("personality") or data.get("speech"))
    if not has_prompt and not has_structured:
        return "人格卡缺少 persona/system_prompt 或结构化人设字段"
    return None
