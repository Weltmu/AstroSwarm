# -*- coding: utf-8 -*-
"""智能体档案：可选 AI 预设（李清菡等）+ 通道能力矩阵 + 唤醒词生成。

范围：档案数据、通道能力裁剪、唤醒词生成（LLM 一次调用 + 正则兜底）。
李清菡的 agent 进程本体与官方 QQ/iLink 适配器单独接入。
"""
import json
import re
import urllib.error
import urllib.request

DEFAULT_PROFILE_ID = "star_helper"
LIQINGHAN_PROFILE_ID = "liqinghan"

DEFAULT_WAKE_WORDS = ["李清菡", "学姐", "姐姐", "菡姐", "菡菡"]

# 李清菡实际注册的 26 个工具（tools.py _register）
LIQINGHAN_TOOLS = [
    "get_time", "recall_message", "mute_user", "mute_all",
    "read_recent_history", "set_reminder", "add_rule", "list_rules",
    "remove_rule", "checkin", "work", "balance", "leaderboard",
    "get_user_profile", "set_relationship", "remember", "recall",
    "adjust_anger", "product_faq", "describe_image",
    "start_game", "game_guess", "game_end", "game_state",
    "send_face", "generate_image",
]

PROFILES = {
    DEFAULT_PROFILE_ID: {
        "id": DEFAULT_PROFILE_ID,
        "name": "星群助手",
        "description": "默认助手，无额外功能层，行为由内置 AI 插件与 dsh 预设决定。",
        "tools": [],
        "default_wake_words": [],
    },
    LIQINGHAN_PROFILE_ID: {
        "id": LIQINGHAN_PROFILE_ID,
        "name": "李清菡",
        "description": "真人感智能体：群聊插话、语音、图片描述/生成、游戏、群管、记忆等。"
                       "人格仍跟随程序「人格设定」，此处只提供功能层。",
        "tools": LIQINGHAN_TOOLS,
        "default_wake_words": list(DEFAULT_WAKE_WORDS),
    },
}


def list_profiles() -> list:
    """按展示顺序返回内置档案列表（dict 副本）。"""
    return [dict(PROFILES[pid]) for pid in (DEFAULT_PROFILE_ID, LIQINGHAN_PROFILE_ID)
            if pid in PROFILES]


def load_profile(profile_id: str) -> dict | None:
    """按 id 加载档案；未知 id 返回 None。"""
    prof = PROFILES.get(profile_id)
    return dict(prof) if prof else None


# ---- 通道能力矩阵 ----
# source = "<channel>:<scope>"，如 qq:c2c / qq:group / wechat:private。
# 能力值：chat / memory / voice / image / image_gen / proactive /
#         group_interject / group_admin / recall / tools。
# 官方 QQ 无 CQ 表情代码，因此 qq_face 能力不启用（send_face 工具会被裁剪）。
CHANNEL_CAPABILITIES = {
    "qq:c2c": {"chat", "memory", "voice", "image", "image_gen",
               "proactive", "recall", "tools"},
    "qq:group": {"chat", "memory", "voice", "image", "image_gen",
                 "proactive", "group_interject", "group_admin",
                 "recall", "tools"},
    "wechat:private": {"chat", "memory", "tools"},
    "feishu:private": {"chat", "memory", "tools"},
    "telegram:private": {"chat", "memory", "tools"},
}

# 工具 → 所需能力（缺省按 chat，即任何聊天通道都可用）
TOOL_CAPABILITIES = {
    "mute_user": "group_admin",
    "mute_all": "group_admin",
    "set_reminder": "proactive",
    "describe_image": "image",
    "send_face": "qq_face",
    "generate_image": "image_gen",
    "remember": "memory",
    "recall": "memory",
    "recall_message": "recall",
}


def channel_capabilities(source: str) -> set:
    """返回指定来源的能力集合；未知通道一律空（全部禁用）。"""
    return set(CHANNEL_CAPABILITIES.get(source, ()))


def enabled_tools(source: str, tools: list) -> list:
    """按通道能力裁剪工具列表（保持原顺序）。"""
    caps = channel_capabilities(source)
    return [t for t in tools if TOOL_CAPABILITIES.get(t, "chat") in caps]


def can_proactive(source: str) -> bool:
    return "proactive" in channel_capabilities(source)


def can_group_admin(source: str) -> bool:
    return "group_admin" in channel_capabilities(source)


# ---- 唤醒词 ----
WAKE_PROMPT = (
    "根据以下人设文本，生成 8 到 12 个自然的中文唤醒词/称呼"
    "（角色名、昵称、关系称谓，例如：李清菡、学姐、菡姐）。\n"
    "只输出 JSON 字符串数组，不要解释、不要代码块、不要其他文字。\n\n"
    "人设：\n{persona}"
)

_NAME_PATTERNS = [
    # “你是X / 你叫X / 我叫X / 名字是X / 大家都叫我X / 叫我X”
    r"(?:你是|我是|你叫|我叫|名字是|你的名字(?:是|为)?|大家都叫我|都叫我|叫我)"
    r"\s*[「“\"'『]?\s*([\u4e00-\u9fa5A-Za-z0-9_.-]{1,16})",
    # 引号/书名号里的称呼
    r"[「“\"'『]([\u4e00-\u9fa5A-Za-z0-9_.-]{1,12})[」”\"'』]",
]


def extract_wake_words(persona: str) -> list:
    """从人格文本确定性提取称呼（名字/昵称句式 + 引号内称呼）。"""
    if not persona:
        return []
    found = []
    for pat in _NAME_PATTERNS:
        for m in re.finditer(pat, persona):
            word = m.group(1).strip().strip("，。、；：！？,.!? \t")
            if (1 <= len(word) <= 16 and word not in found
                    and not re.search(r"[\s，。、；：！？,.!?\"'“”‘’【】]", word)):
                found.append(word)
            if len(found) >= 16:
                return found
    return found


def parse_wake_words(raw: str) -> list | None:
    """解析模型返回的 JSON 数组；格式不对返回 None。"""
    if not raw:
        return None
    text = re.sub(r"^```(?:json)?[ \t]*\n?", "", raw.strip())
    text = re.sub(r"\n?```[ \t]*$", "", text)
    m = re.search(r"\[[\s\S]*\]", text)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except ValueError:
        return None
    if not isinstance(data, list):
        return None
    words = []
    for item in data:
        if not isinstance(item, str):
            continue
        word = item.strip()
        if (1 <= len(word) <= 16 and word not in words
                and not re.search(r"[\s，。、；：！？,.!?\"'“”‘’【】]", word)):
            words.append(word)
        if len(words) >= 16:
            break
    return words or None


def generate_wake_words(persona: str, call_llm, default: list | None = None) -> list:
    """按人格生成唤醒词：LLM 一次调用 → 解析失败走正则 → 兜底默认词。"""
    default = list(default) if default else list(DEFAULT_WAKE_WORDS)
    if not persona or not persona.strip():
        return default
    prompt = WAKE_PROMPT.format(persona=persona.strip())
    raw = ""
    try:
        raw = call_llm(prompt)
    except Exception:  # noqa: BLE001 —— 生成失败必须走兜底，不能中断保存流程
        raw = ""
    words = parse_wake_words(raw) if raw else None
    if words:
        return words
    words = extract_wake_words(persona)
    return words or default


def openai_chat(prompt: str, api_url: str, api_key: str, model: str,
                timeout: int = 60) -> str:
    """OpenAI 兼容 chat/completions 单轮调用，返回首条消息文本。"""
    base = (api_url or "").strip().rstrip("/")
    if not base or not api_key or not model:
        raise ValueError("语言模型接口地址 / 密钥 / 模型未配置")
    url = base + "/chat/completions"
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7,
        "max_tokens": 300,
    }).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", "Bearer " + api_key)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    try:
        return str(data["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError) as e:
        raise ValueError("模型返回格式异常: " + str(e)) from e
