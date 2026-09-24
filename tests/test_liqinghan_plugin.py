# -*- coding: utf-8 -*-
"""李清菡智能体测试：官方 QQ 适配层、微信桥、能力裁剪、程序侧互斥与配置注入。

插件本体运行在 bot venv（有 httpx/nonebot），本测试运行在构建环境，
因此适配层只用标准库（urllib/asyncio），避免引入额外依赖。
"""
import asyncio
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
if not os.environ.get("QBM_POINTER_DIR"):
    os.environ["QBM_POINTER_DIR"] = str(Path(tempfile.mkdtemp(prefix="qbm_test_ptr_")))

ASSETS_PLUGINS = ROOT / "src" / "qbotmanager" / "assets" / "plugins"


def _load_module(name: str, file_name: str):
    """按文件路径加载插件模块（不触发包 __init__，避免 NoneBot 依赖）。"""
    path = ASSETS_PLUGINS / "liqinghan" / file_name
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Seg:
    def __init__(self, type_, data=None):
        self.type = type_
        self.data = data or {}


class _FakeMsg(list):
    pass


class _FakeQQEvent:
    """模拟 nonebot-adapter-qq 消息事件（C2C / 群）。"""

    message_type = "c2c"
    to_me = True

    def __init__(self, openid, group_openid=None, text="", segs=None, nickname="测试用户",
                 to_me=True):
        self.author = SimpleNamespace(
            user_openid=openid, member_openid=openid, username=nickname)
        self.group_openid = group_openid
        self.id = "msg_abc123"
        self._text = text
        self.to_me = to_me
        self._segs = segs or [_Seg("text", {"text": text})]

    def get_user_id(self):
        return self.author.user_openid

    def get_plaintext(self):
        return self._text

    def get_message(self):
        return self._segs


# ---------------------------------------------------------------- 事件转换
def test_to_data_c2c():
    qq = _load_module("lqh_qq", "qq_official.py")
    ev = _FakeQQEvent("o_openid_1", text="你好呀", nickname="小李")
    data = qq.to_data(ev, bot_qq="bot_id")
    assert data["post_type"] == "message"
    assert data["message_type"] == "private"
    assert data["user_id"] == "o_openid_1"
    assert data["message_id"] == "msg_abc123"
    assert data["source"] == "qq:c2c"
    assert data["raw_message"] == "你好呀"
    assert data["sender"]["nickname"] == "小李"
    assert data["message"][0]["type"] == "text"
    assert data["message"][0]["data"]["text"] == "你好呀"


def test_to_data_group_injects_at_when_to_me():
    qq = _load_module("lqh_qq2", "qq_official.py")
    ev = _FakeQQEvent("o_member_2", group_openid="o_group_9", text="学姐在吗", to_me=True)
    data = qq.to_data(ev, bot_qq="bot_id")
    assert data["message_type"] == "group"
    assert data["group_id"] == "o_group_9"
    assert data["source"] == "qq:group"
    ats = [s for s in data["message"] if s["type"] == "at"]
    assert ats and ats[0]["data"]["qq"] == "bot_id"


def test_to_data_group_no_at_when_not_to_me():
    qq = _load_module("lqh_qq3", "qq_official.py")
    ev = _FakeQQEvent("o_member_3", group_openid="o_group_9", text="今天好热", to_me=False)
    data = qq.to_data(ev, bot_qq="bot_id")
    assert not any(s["type"] == "at" for s in data["message"])


def test_to_data_image_keeps_url():
    qq = _load_module("lqh_qq4", "qq_official.py")
    ev = _FakeQQEvent(
        "o_member_4", text="[图片]",
        segs=[_Seg("image", {"url": "https://example.com/a.png"})])
    data = qq.to_data(ev, bot_qq="bot_id")
    imgs = [s for s in data["message"] if s["type"] == "image"]
    assert imgs and imgs[0]["data"]["url"] == "https://example.com/a.png"


# ---------------------------------------------------------------- 动作映射
class _FakeBot:
    def __init__(self):
        self.sent = []
        self.active_c2c = []
        self.active_group = []
        self.deleted = []
        self.access_token = "token-123"

    async def send(self, event, message):
        self.sent.append((event, message))
        return SimpleNamespace(id="sent_1")

    async def send_to_c2c(self, *, openid, message, msg_seq=None):
        self.active_c2c.append((openid, message, msg_seq))
        return SimpleNamespace(id=f"c2c_{msg_seq}")

    async def send_to_group(self, *, group_openid, message, msg_seq=None):
        self.active_group.append((group_openid, message, msg_seq))
        return SimpleNamespace(id=f"group_{msg_seq}")

    async def delete_c2c_message(self, *, openid, message_id):
        self.deleted.append(("c2c", openid, message_id))

    async def delete_group_message(self, *, group_openid, message_id):
        self.deleted.append(("group", group_openid, message_id))

    async def get_access_token(self):
        return self.access_token


def test_action_send_private_passive_uses_event():
    qq = _load_module("lqh_qq5", "qq_official.py")
    ch = qq.OfficialChannel()
    ev = _FakeQQEvent("o_openid_1", text="hi")
    bot = _FakeBot()
    ch.set_current(bot, ev, "qq:c2c")

    async def run():
        return await ch.action("send_private_msg", {"user_id": "o_openid_1", "message": "你好"})

    resp = asyncio.run(run())
    assert bot.sent and bot.sent[0][1] == "你好"
    assert resp["message_id"] == "sent_1"
    assert not bot.active_c2c


def test_action_send_private_active_uses_msg_seq():
    qq = _load_module("lqh_qq6", "qq_official.py")
    ch = qq.OfficialChannel()
    bot = _FakeBot()
    ch.attach(bot)

    async def run():
        await ch.action("send_private_msg", {"user_id": "o_openid_x", "message": "第一条"})
        await ch.action("send_private_msg", {"user_id": "o_openid_x", "message": "第二条"})

    asyncio.run(run())
    assert bot.active_c2c == [("o_openid_x", "第一条", 1), ("o_openid_x", "第二条", 2)]


def test_action_send_group_passive_and_active():
    qq = _load_module("lqh_qq7", "qq_official.py")
    ch = qq.OfficialChannel()
    bot = _FakeBot()
    ev = _FakeQQEvent("o_member", group_openid="o_group_9", text="hi")
    ch.set_current(bot, ev, "qq:group")

    async def run():
        await ch.action("send_group_msg", {"group_id": "o_group_9", "message": "群回复"})
        ch._event = None  # 模拟主动消息（无最近事件上下文）
        await ch.action("send_group_msg", {"group_id": "o_group_9", "message": "主动群发"})

    asyncio.run(run())
    assert bot.sent and bot.sent[0][1] == "群回复"
    assert bot.active_group == [("o_group_9", "主动群发", 1)]


def test_action_delete_msg_uses_sent_scope():
    qq = _load_module("lqh_qq8", "qq_official.py")
    ch = qq.OfficialChannel()
    bot = _FakeBot()
    ev = _FakeQQEvent("o_openid_1", text="hi")
    ch.set_current(bot, ev, "qq:c2c")

    async def run():
        await ch.action("send_private_msg", {"user_id": "o_openid_1", "message": "你好"})
        await ch.action("delete_msg", {"message_id": "sent_1"})

    asyncio.run(run())
    assert bot.deleted == [("c2c", "o_openid_1", "sent_1")]


def test_action_unsupported_returns_error_not_raise():
    qq = _load_module("lqh_qq9", "qq_official.py")
    ch = qq.OfficialChannel()

    async def run():
        return {
            "whole": await ch.action("set_group_whole_ban", {"group_id": "g", "enable": True}),
            "member": await ch.action("get_group_member_info", {"group_id": "g", "user_id": "u"}),
            "join": await ch.action("set_group_add_request", {"flag": "f"}),
        }

    out = asyncio.run(run())
    assert "不支持" in str(out["whole"]).lower() or "不支持" in str(out["whole"])
    assert out["member"] is None
    assert "尚未接入" in str(out["join"])


def test_action_set_group_ban_builds_official_payload():
    qq = _load_module("lqh_qq10", "qq_official.py")
    ch = qq.OfficialChannel()
    bot = _FakeBot()
    ch.attach(bot)
    calls = []

    def fake_http(method, url, token, body=None):
        calls.append((method, url, token, body))
        if method == "GET":
            return {"members": []}
        return {}

    ch.http_request = fake_http

    async def run():
        return await ch.action(
            "set_group_ban",
            {"group_id": "o_group_9", "user_id": "o_member_2", "duration": 300})

    out = asyncio.run(run())
    assert out["ok"] is True
    assert calls[0][0] == "GET" and "restrict_chat_setting" in calls[0][1]
    post = calls[1]
    assert post[0] == "POST" and post[2] == "token-123"
    member = post[3]["members"][0]
    assert member["op"] == "add"
    assert member["member_openid"] == "o_member_2"
    assert member["mute_expire_at"].endswith("Z")


def test_action_set_group_ban_unmute_uses_del():
    qq = _load_module("lqh_qq11", "qq_official.py")
    ch = qq.OfficialChannel()
    bot = _FakeBot()
    ch.attach(bot)
    calls = []

    def fake_http(method, url, token, body=None):
        calls.append((method, url, token, body))
        if method == "GET":
            return {"members": [{"member_openid": "o_member_2", "mute_expire_at": "2030-01-01T00:00:00Z"}]}
        return {}

    ch.http_request = fake_http

    async def run():
        return await ch.action(
            "set_group_ban",
            {"group_id": "o_group_9", "user_id": "o_member_2", "duration": 0})

    out = asyncio.run(run())
    assert out["ok"] is True
    post = calls[1]
    assert post[3]["members"][0]["op"] == "del"


# ---------------------------------------------------------------- 微信桥
def test_bridge_parses_wechat_payload():
    bridge = _load_module("lqh_bridge", "bridge.py")
    seen = {}

    class _FakeAgent:
        async def on_event(self, data):
            seen["data"] = data

        async def wait_for_reply(self, session, timeout):
            return "微信回复"

    async def run():
        return await bridge.handle_payload(
            _FakeAgent(),
            {"session_key": "wechat:private:o_wechat_1", "text": "你好",
             "sender_name": "微信用户", "is_group": False},
        )

    out = asyncio.run(run())
    assert out["session_id"] == "wechat:private:o_wechat_1"
    assert out["reply"] == "微信回复"
    d = seen["data"]
    assert d["message_type"] == "private"
    assert d["user_id"] == "o_wechat_1"
    assert d["source"] == "wechat:private"
    assert d["raw_message"] == "你好"


# ---------------------------------------------------------------- 能力裁剪
def test_capabilities_wechat_drops_admin_and_proactive():
    caps = _load_module("lqh_caps", "capabilities.py")
    tools = caps.enabled_tools("wechat:private", [
        "mute_user", "mute_all", "set_reminder", "describe_image",
        "send_face", "generate_image", "recall_message", "game_guess"])
    assert tools == ["game_guess"]


def test_capabilities_qq_group_keeps_admin():
    caps = _load_module("lqh_caps2", "capabilities.py")
    tools = caps.enabled_tools("qq:group", [
        "mute_user", "mute_all", "send_face", "recall_message", "game_guess", "remember"])
    assert set(tools) == {"mute_user", "mute_all", "recall_message", "game_guess", "remember"}


# ---------------------------------------------------------------- 程序侧接线
def test_agent_profile_drops_qq_face():
    """官方 QQ 无 CQ 表情代码，qq_face 能力与 send_face 工具应被裁剪。"""
    from qbotmanager.core import agent_profile
    for source in ("qq:c2c", "qq:group"):
        assert "qq_face" not in agent_profile.channel_capabilities(source)
    tools = agent_profile.enabled_tools(
        "qq:group", ["send_face", "mute_user", "recall_message", "game_guess"])
    assert "send_face" not in tools


def test_settings_agent_owner_openid_roundtrip():
    from qbotmanager.core.settings import Settings
    tmp = Path(tempfile.mkdtemp(prefix="qbm_owner_"))
    s = Settings(tmp)
    s.ensure_dirs()
    s.agent_owner_openid = "o_owner_123"
    s.save()
    s2 = Settings.load(tmp)
    assert s2.agent_owner_openid == "o_owner_123"


def _agent_settings(tmp):
    from qbotmanager.core.settings import Settings
    s = Settings(tmp)
    s.ensure_dirs()
    s.agent_profile_enabled = True
    s.agent_profile_id = "liqinghan"
    s.agent_wake_words = ["李清菡", "学姐"]
    s.agent_owner_openid = "o_owner_123"
    s.vision_api_key = "sk-vision"
    s.vision_api_url = "https://api.siliconflow.cn/v1"
    s.vision_model = "Qwen/Qwen3-Omni-30B-A3B-Instruct"
    s.qq_channel = "official"
    s.qq_official_appid = "appid123"
    s.qq_official_token = "tok"
    s.qq_official_secret = "sec"
    return s


def test_bot_env_injects_agent_config():
    from qbotmanager.core import ai_config, bot
    tmp = Path(tempfile.mkdtemp(prefix="qbm_envlq_"))
    s = _agent_settings(tmp)
    ai_config.save_config(
        s, api_key="sk-llm", api_url="https://api.deepseek.com",
        model="deepseek-v4-flash")
    text = bot.build_env_text(s)
    assert "QBM_AGENT_PROFILE_ENABLED=1" in text
    assert "QBM_AGENT_DATA_DIR=" in text
    assert "QBM_AGENT_LOG_FILE=" in text
    assert "QBM_AGENT_OWNER_QQ=o_owner_123" in text
    assert "QBM_AGENT_ADDRESS_WORDS=" in text and "李清菡" in text
    assert "DEEPSEEK_API_URL=https://api.deepseek.com" in text
    assert "DEEPSEEK_API_KEY=sk-llm" in text
    assert "DEEPSEEK_MODEL=deepseek-v4-flash" in text
    assert "SILICONFLOW_API_KEY=sk-vision" in text
    assert "VISION_MODEL=Qwen" in text


def test_qq_bots_intent_subscribes_full_group_messages():
    """QQ_BOTS intent 须含 c2c_group_at_messages（bit 25 = GROUP_AND_C2C_EVENT，
    官方文档中 GROUP_MESSAGE_CREATE 全量群消息与群 @ 同属该意图位）。"""
    from qbotmanager.core import bot
    tmp = Path(tempfile.mkdtemp(prefix="qbm_intent_"))
    s = _agent_settings(tmp)
    text = bot.build_env_text(s)
    line = next(ln for ln in text.splitlines() if ln.startswith("QQ_BOTS="))
    bots = json.loads(line.split("=", 1)[1])
    assert bots[0]["intent"]["c2c_group_at_messages"] is True


def test_bot_env_skips_agent_when_disabled():
    from qbotmanager.core import bot
    tmp = Path(tempfile.mkdtemp(prefix="qbm_envlq2_"))
    s = _agent_settings(tmp)
    s.agent_profile_enabled = False
    assert "QBM_AGENT_PROFILE_ENABLED" not in bot.build_env_text(s)


def test_qq_adapter_enabled_with_agent_and_dsh():
    """李清菡启用时 QQ 由李清菡接管：即使 dsh 开关打开也要注册官方 QQ 适配器。"""
    from qbotmanager.core import bot
    tmp = Path(tempfile.mkdtemp(prefix="qbm_adplq_"))
    s = _agent_settings(tmp)
    s.dsh_enabled = True
    assert bot._enabled_qq_adapters(s) == [("QQ", "nonebot.adapters.qq")]


def test_qq_adapter_not_enabled_for_star_helper():
    """星群助手档案不接管 QQ：dsh 开启时仍由 dsh 接管，不应注册 QQ 适配器。"""
    from qbotmanager.core import bot
    tmp = Path(tempfile.mkdtemp(prefix="qbm_star_"))
    s = _agent_settings(tmp)
    s.agent_profile_id = "star_helper"
    s.dsh_enabled = True
    assert bot._enabled_qq_adapters(s) == []
    s.dsh_enabled = False
    assert bot._enabled_qq_adapters(s) == [("QQ", "nonebot.adapters.qq")]


def test_ai_platform_env_agent_disables_old_ai():
    """李清菡启用时旧 AI 插件不再处理 QQ/微信，避免双回复。"""
    from qbotmanager.core import bot
    tmp = Path(tempfile.mkdtemp(prefix="qbm_platlq_"))
    s = _agent_settings(tmp)
    s.dsh_enabled = True
    env = bot.ai_platform_env(s)
    assert env["AI_PLATFORM_QQ"] == "0"
    assert env["AI_PLATFORM_WECHAT"] == "0"


def test_manager_skips_dsh_when_agent_profile():
    """李清菡启用时启动全部应跳过 dsh（同一 18650 桥互斥）并提示。"""
    from qbotmanager.core.manager import Manager
    tmp = Path(tempfile.mkdtemp(prefix="qbm_mutex_"))
    s = _agent_settings(tmp)
    s.dsh_enabled = True
    log_lines = []
    m = Manager(s, on_log=lambda line: log_lines.append(line))
    m.qq_channel.start = lambda *a, **k: None
    m.start_bot = lambda *a, **k: None
    m.start_dsh = lambda *a, **k: (_ for _ in ()).throw(AssertionError("不应启动 dsh"))
    out = m.start_all()
    assert out["dsh_ok"] is False
    assert any("跳过 dsh" in line or "互斥" in line for line in log_lines), log_lines


def test_scaffold_includes_liqinghan_plugin():
    """scaffold / start_bot 自愈应把李清菡插件同步到机器人插件目录。"""
    from qbotmanager.core import bot
    tmp = Path(tempfile.mkdtemp(prefix="qbm_synclq_"))
    s = _agent_settings(tmp)
    bot.scaffold_bot(s)
    target = s.plugins_dir / "liqinghan" / "qq_official.py"
    assert target.exists()
    assert (s.plugins_dir / "liqinghan" / "__init__.py").exists()


def test_reminder_uses_persona_name():
    """定时提醒前缀跟随人设：EVA 发（EVA提醒），空人设回退李清菡。"""
    import asyncio
    from types import SimpleNamespace

    scheduler = _load_module("qbm_scheduler", "scheduler.py")

    async def _run_once(cfg, compose=None):
        fired = []

        async def action(name, payload):
            fired.append((name, payload))

        store = SimpleNamespace(
            due_reminders=lambda: [{
                "id": 1, "kind": "group", "target_id": "g1", "text": "喝水",
            }],
            mark_reminder_fired=lambda rid: fired.append(("mark", rid)),
        )
        ob = SimpleNamespace(action=action)
        task = asyncio.create_task(
            scheduler.reminder_loop(cfg, store, ob, compose=compose))
        for _ in range(100):
            if fired:
                break
            await asyncio.sleep(0.01)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception:  # noqa: BLE001
            pass
        return fired

    fired = asyncio.run(_run_once(SimpleNamespace(persona_name="EVA")))
    assert ("send_group_msg",
            {"group_id": "g1", "message": "（EVA提醒）喝水"}) in fired, fired

    fired = asyncio.run(_run_once(SimpleNamespace(persona_name="")))
    assert ("send_group_msg",
            {"group_id": "g1", "message": "（李清菡提醒）喝水"}) in fired, fired

    # 有 compose 回调时：提醒话术由 agent 生成，不套固定模板
    async def compose(_r):
        return "该喝水了，别老坐着"
    fired = asyncio.run(_run_once(
        SimpleNamespace(persona_name="EVA"), compose=compose))
    assert ("send_group_msg",
            {"group_id": "g1", "message": "该喝水了，别老坐着"}) in fired, fired


def test_config_persona_name_follows_mode():
    """persona_name：eva 模式默认 EVA，其余默认李清菡，可环境变量覆盖。"""
    from unittest import mock

    config_mod = _load_module("qbm_liqinghan_config", "config.py")
    with mock.patch.dict(os.environ, {
        "QBM_AGENT_PERSONA_MODE": "eva",
        "QBM_AGENT_PERSONA_NAME": "",
        "PERSONA_NAME": "",
    }, clear=False):
        assert config_mod.Config(None).persona_name == "EVA"
    with mock.patch.dict(os.environ, {
        "QBM_AGENT_PERSONA_MODE": "",
        "QBM_AGENT_PERSONA_NAME": "",
        "PERSONA_NAME": "",
    }, clear=False):
        assert config_mod.Config(None).persona_name == "李清菡"
    with mock.patch.dict(os.environ, {
        "QBM_AGENT_PERSONA_NAME": "星群助手",
    }, clear=False):
        assert config_mod.Config(None).persona_name == "星群助手"


def test_eva_persona_defines_peer_line():
    """EVA 人设分支必须定义模板用到的变量，防止 NameError（主动私聊每 15 分钟崩溃）。"""
    src = (ASSETS_PLUGINS / "liqinghan" / "persona.py").read_text(encoding="utf-8")
    for var in ("peer_line =", "char_lines =", "respect_line ="):
        assert src.count(var) >= 2, f"李清菡/EVA 两个分支都应定义 {var}"
    assert "{peer_line}" in src


def test_agent_wechat_bridge_integration():
    """真实 Agent + 微信 Noop 通道：桥消息 → agent 回复 → wait_for_reply 取回。"""
    sys.path.insert(0, str(ASSETS_PLUGINS))
    try:
        import nonebot  # noqa: F401 —— 插件包 __init__ 依赖 nonebot，构建环境可跳过
        from liqinghan.agent import Agent
        from liqinghan.bridge import handle_payload
        from liqinghan.config import Config
        from liqinghan.qq_official import DispatchChannel
    except ImportError:
        print("skip agent_wechat_bridge_integration (no nonebot in build env)")
        return

    class FakeBrain:
        async def think(self, *args, **kwargs):
            return "你好呀，我在"

    class TestCfg(Config):
        def __init__(self):
            super().__init__(None)
            self.data_dir = tempfile.mkdtemp(prefix="qbm_lqh_data_")
            self.log_file = os.path.join(self.data_dir, "agent.log")
            self.sf_api_key = ""
            self.ds_api_key = "sk-test"
            self.groups = []
            self.owner_qq = ""

    cfg = TestCfg()
    channel = DispatchChannel()
    agent = Agent(cfg, channel)
    agent.brain = FakeBrain()

    async def _no_delay():
        return 0.0
    agent._activity_delay = _no_delay

    async def run():
        return await handle_payload(
            agent,
            {"session_key": "wechat:private:o_wx_1", "text": "在吗",
             "sender_name": "微信用户", "is_group": False},
            channel,
        )

    reply = asyncio.run(run())
    assert "你好呀" in reply["reply"], reply


# ---------------------------------------------------------------- 回复节奏行为包
class _FakeRng:
    """确定性随机源：random() 与 uniform(lo, hi) 可分别指定。"""

    def __init__(self, rand_value=0.5, uniform_value=0.0):
        self.rand_value = rand_value
        self.uniform_value = uniform_value

    def random(self):
        return self.rand_value

    def uniform(self, lo, hi):
        return self.uniform_value


def test_behavior_module_reads_bundled_config():
    bh = _load_module("lqh_behavior", "behavior.py")
    cfg = bh._load()
    assert cfg["activity_delay"]["busy_long_seconds"] == [180, 900]
    assert cfg["activity_delay"]["busy_short_seconds"] == [8, 40]
    assert cfg["activity_delay"]["idle_seconds"] == [60, 180]


def test_behavior_idle_low_probability_no_delay():
    bh = _load_module("lqh_behavior_idle", "behavior.py")
    # idle_probability=0.1，random()=0.5 不命中 → 不延迟
    assert bh.compute_activity_delay(False, rng=_FakeRng(rand_value=0.5)) == 0.0
    # 命中空闲慢回 → 走 idle 区间（uniform 返回固定值）
    assert bh.compute_activity_delay(False, rng=_FakeRng(rand_value=0.05, uniform_value=90.0)) == 90.0


def test_behavior_busy_long_and_short():
    bh = _load_module("lqh_behavior_busy", "behavior.py")
    # 命中长延迟（0.35 概率）→ 返回 uniform 值
    assert bh.compute_activity_delay(True, rng=_FakeRng(rand_value=0.1, uniform_value=600.0)) == 600.0
    # 未命中长延迟 → 走短延迟区间
    assert bh.compute_activity_delay(True, rng=_FakeRng(rand_value=0.9, uniform_value=20.0)) == 20.0


def test_behavior_env_override(tmp_path):
    cfg_path = tmp_path / "custom_behavior.json"
    cfg_path.write_text(
        json.dumps({"activity_delay": {"busy_long_probability": 1.0,
                                       "busy_long_seconds": [5, 5],
                                       "busy_short_seconds": [1, 1],
                                       "idle_probability": 0.0,
                                       "idle_seconds": [1, 1]}}),
        encoding="utf-8",
    )
    old = os.environ.get("ASTROSWARM_REPLY_RHYTHM")
    os.environ["ASTROSWARM_REPLY_RHYTHM"] = str(cfg_path)
    try:
        bh = _load_module("lqh_behavior_env", "behavior.py")
        assert bh.compute_activity_delay(True, rng=_FakeRng(rand_value=0.5, uniform_value=5.0)) == 5.0
    finally:
        if old is None:
            os.environ.pop("ASTROSWARM_REPLY_RHYTHM", None)
        else:
            os.environ["ASTROSWARM_REPLY_RHYTHM"] = old


if __name__ == "__main__":
    test_to_data_c2c()
    print("OK to_data_c2c")
    test_to_data_group_injects_at_when_to_me()
    print("OK to_data_group_at")
    test_to_data_group_no_at_when_not_to_me()
    print("OK to_data_group_no_at")
    test_to_data_image_keeps_url()
    print("OK to_data_image")
    test_action_send_private_passive_uses_event()
    print("OK action_send_private_passive")
    test_action_send_private_active_uses_msg_seq()
    print("OK action_send_private_active")
    test_action_send_group_passive_and_active()
    print("OK action_send_group")
    test_action_delete_msg_uses_sent_scope()
    print("OK action_delete_msg")
    test_action_unsupported_returns_error_not_raise()
    print("OK action_unsupported")
    test_action_set_group_ban_builds_official_payload()
    print("OK action_set_group_ban")
    test_action_set_group_ban_unmute_uses_del()
    print("OK action_set_group_ban_unmute")
    test_bridge_parses_wechat_payload()
    print("OK bridge_payload")
    test_capabilities_wechat_drops_admin_and_proactive()
    print("OK capabilities_wechat")
    test_capabilities_qq_group_keeps_admin()
    print("OK capabilities_qq_group")
    test_agent_profile_drops_qq_face()
    print("OK agent_profile_drops_qq_face")
    test_settings_agent_owner_openid_roundtrip()
    print("OK settings_owner_openid")
    test_bot_env_injects_agent_config()
    print("OK bot_env_injects_agent_config")
    test_qq_bots_intent_subscribes_full_group_messages()
    print("OK qq_bots_intent_full_group")
    test_bot_env_skips_agent_when_disabled()
    print("OK bot_env_skips_agent")
    test_qq_adapter_enabled_with_agent_and_dsh()
    print("OK qq_adapter_with_agent_and_dsh")
    test_qq_adapter_not_enabled_for_star_helper()
    print("OK qq_adapter_not_enabled_for_star_helper")
    test_ai_platform_env_agent_disables_old_ai()
    print("OK ai_platform_env_agent")
    test_manager_skips_dsh_when_agent_profile()
    print("OK manager_skips_dsh")
    test_scaffold_includes_liqinghan_plugin()
    print("OK scaffold_liqinghan")
    test_reminder_uses_persona_name()
    print("OK reminder_persona_name")
    test_config_persona_name_follows_mode()
    print("OK config_persona_name")
    test_eva_persona_defines_peer_line()
    print("OK eva_persona_peer_line")
    test_agent_wechat_bridge_integration()
    print("OK agent_wechat_bridge_integration")
