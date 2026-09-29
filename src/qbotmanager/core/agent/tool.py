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

# 运行时平台名 → manifest.adapters 里的通道名（工具包声明兼容哪些通道）
PLATFORM_ADAPTERS = {
    "qq": "qq",
    "qq_official": "qq_official",
    "wechat": "wechat_ilink",
    "feishu": "feishu",
    "telegram": "telegram",
}


def platform_adapter(platform: str) -> str:
    """把运行时平台名（qq_official / wechat …）换成 manifest 里的通道名。"""
    return PLATFORM_ADAPTERS.get(str(platform or "").strip(), "")


def adapters_allow(adapters, platform: str) -> bool:
    """通道过滤：adapters 为空 = 不限通道；有声明就必须命中当前通道。

    拿不到平台信息（platform 为空，例如旧调用方/单元测试）时不拦截，
    保证 2026-09-27 之前的调用行为完全不变。
    """
    items = [str(a).strip() for a in (adapters or []) if str(a).strip()]
    if not items:
        return True
    current = platform_adapter(platform)
    if not current:
        return True
    return current in items


class ToolPermissionError(PermissionError):
    """工具缺少权限时抛出。"""


class ToolUnavailableError(RuntimeError):
    """工具在当前环境/通道不可用（通道不匹配、需要沙箱异步执行等）。"""


# 会真的改变外部世界的动作：这些失败了才算"没做成"（读类动作失败是正常流程）
EFFECT_ACTIONS = {
    "send_message", "mute_user", "mute_all", "recall_message",
    "http_request", "memory_write", "data_write", "reminder_add",
}


def merge_effect_report(result_text: str, effect_results) -> str:
    """动作回执校验：工具说成功、但主程序执行动作失败时，把真相写回结果。

    追加 ``effect_errors`` 并把 ok 改成 false，模型据此如实告知用户，
    而不是照抄工具返回的"成功"。
    """
    bad = []
    for item in effect_results or ():
        if not isinstance(item, dict) or item.get("ok") is not False:
            continue
        if str(item.get("action") or "") not in EFFECT_ACTIONS:
            continue    # 读/探测类动作失败不算"没做成"（插件往往会自己兜底）
        bad.append({
            "action": str(item.get("action") or ""),
            "error": str(item.get("error") or item.get("detail") or "failed"),
        })
    if not bad:
        return result_text
    text = str(result_text)
    try:
        data = json.loads(text)
    except Exception:  # noqa: BLE001
        data = None
    if not isinstance(data, dict):
        return text + "\n[动作回执] " + json.dumps(
            {"effect_errors": bad}, ensure_ascii=False)
    if data.get("ok") is False:
        return text
    data["ok"] = False
    data["effect_errors"] = bad
    return json.dumps(data, ensure_ascii=False, default=str)


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict
    permissions: list
    handler: callable
    lifecycle: str = "none"
    pack_id: str = ""
    adapters: list = field(default_factory=list)
    sandbox: bool = False

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
    """工具执行上下文：配置/存储/发送回执/权限集合 + 当前通道信息。

    2026-09-27 起补充平台/用户字段与"动作回执"：工具里的
    ``ctx.send(action, params)`` 交给主程序执行（发消息、写记忆等），
    结果记进 ``effect_results``，registry 会拿它判断
    "工具说成功、但动作其实没做成"的情况。
    旧调用方只传 cfg/store/send/permissions 时行为与以前完全一致。
    """

    def __init__(self, cfg=None, store=None, send=None, permissions=frozenset(),
                 platform="", scene="", user_id="", group_id="", nickname="",
                 is_superuser=False, extra=None, flush=None, channel=None):
        self.cfg = cfg
        self.store = store
        self._send = send
        self._permissions = set(permissions or ())
        self.platform = str(platform or "")
        self.scene = str(scene or "")
        self.user_id = str(user_id or "")
        self.group_id = str(group_id or "")
        self.nickname = str(nickname or "")
        self.is_superuser = bool(is_superuser)
        self.extra = dict(extra or {})
        self.flush = flush
        self.channel = channel   # 主程序侧的通道发送器（ChannelContext），不下发沙箱
        self.effect_results: list = []

    @property
    def source(self) -> str:
        """<通道>:<场景>，如 qq_official:group / qq:c2c / wechat:private。"""
        if not self.platform:
            return ""
        if self.platform == "qq":
            return "qq:group" if self.scene == "group" else "qq:c2c"
        return f"{self.platform}:{self.scene or 'private'}"

    def can(self, permission: str) -> bool:
        return permission in self._permissions

    def bind_send(self, fn) -> None:
        """换一个动作执行器（主程序每次执行工具前调用；None = 关掉动作）。"""
        self._send = fn

    def send(self, action, params=None):
        """请求主程序执行一个动作；返回 {"ok": bool, ...}，并记录回执。"""
        if self._send is None:
            res = {"ok": False, "error": "action_unavailable",
                   "action": str(action)}
        else:
            try:
                res = self._send(str(action), dict(params or {}))
            except Exception as e:  # noqa: BLE001 —— 动作失败不能让工具崩掉
                res = {"ok": False, "error": "action_error",
                       "action": str(action), "detail": str(e)}
        if not isinstance(res, dict):
            res = {"ok": True, "action": str(action), "value": res}
        else:
            # 回执必须带动作名：执行器漏填时由上下文补上，
            # 否则"动作失败了"会被 merge_effect_report 当成读类动作放过。
            res = dict(res)
            res.setdefault("action", str(action))
        self.effect_results.append(res)
        return res


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
    sandbox: bool = False

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
            sandbox=bool(data.get("sandbox") or False),
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
