# -*- coding: utf-8 -*-
"""核心逻辑测试：message_store 解析、设置回环、安装根找回、机器码格式。"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
if not os.environ.get("QBM_POINTER_DIR"):
    os.environ["QBM_POINTER_DIR"] = str(Path(tempfile.mkdtemp(prefix="qbm_test_ptr_")))

from qbotmanager.core import message_store  # noqa: E402
from qbotmanager.core import settings as settings_mod  # noqa: E402
from qbotmanager.core.settings import Settings  # noqa: E402


def _trust_plan(lic_mod):
    """短接权益签名校验：这些用例只测档位/到期逻辑，签名本身另有专项测试

    （见 test_entitlement_signature_is_required）。
    """
    lic_mod.verify_entitlement = lambda *a, **k: True


def test_message_store():
    tmp = Path(tempfile.mkdtemp(prefix="qbm_t_"))
    s = Settings(tmp)
    data_dir = s.bot_dir / "data" / "ai"
    data_dir.mkdir(parents=True)
    (data_dir / "aichat_context.json").write_text(json.dumps({
        "group_67890": [{"role": "user", "content": "a"}],
        "12345": [{"role": "user", "content": "b"}],
        "wechat:private:o9cq@im.wechat": [{"role": "user", "content": "c"}],
    }), encoding="utf-8")
    convs = message_store.load_conversations(s)
    assert len(convs) == 3, convs
    assert message_store.load_message_count(s) == 3


def test_message_store_dsh():
    """首页/消息中心应能读取 dsh 的 QQ 会话（zstd 落盘）。"""
    import zstandard
    tmp = Path(tempfile.mkdtemp(prefix="qbm_t_"))
    s = Settings(tmp)
    sess = tmp / "dsh" / "home" / "sessions" / "ws" / "sess1234"
    sess.mkdir(parents=True)
    lines = [
        {"type": "user/message", "time": 1000,
         "data": {"content": [{"type": "text", "text": "你是谁"}], "role": "user"}},
        {"type": "assistant/message", "time": 2000,
         "data": {"content": [{"type": "text", "text": "我是 px"}], "role": "assistant"}},
    ]
    raw = "\n".join(json.dumps(x, ensure_ascii=False) for x in lines).encode("utf-8")
    (sess / "session.jsonl.zstd").write_bytes(zstandard.ZstdCompressor().compress(raw))
    convs = message_store.load_conversations(s, 8)
    qq = [c for c in convs if c["platform"] == "qq"]
    assert qq, convs
    assert qq[0]["last"] == "我是 px"
    assert message_store.load_message_count(s) >= 2


def test_settings_roundtrip():
    tmp = Path(tempfile.mkdtemp(prefix="qbm_t_"))
    s = Settings(tmp)
    s.ensure_dirs()
    assert s.beginner_mode is True, "小白模式默认应为开启"
    s.theme = "swiss"
    s.accent = "cyber"
    s.glass_effect = "liquid"
    s.ui_opacity = 45
    s.ui_color = "#F3F4F6"
    s.bg_image_enabled = True
    s.bg_image_path = "C:/t.png"
    s.auto_start_services = True
    s.auto_launch_on_boot = True
    s.beginner_mode = False
    s.save()
    s2 = Settings.load(tmp)
    assert s2.theme == "swiss" and s2.accent == "cyber"
    assert s2.glass_effect == "liquid" and s2.ui_opacity == 45
    assert s2.ui_color == "#F3F4F6" and s2.bg_image_enabled
    assert s2.auto_start_services is True
    assert s2.auto_launch_on_boot is True
    assert s2.beginner_mode is False


def test_settings_load_bad_port_keeps_creds():
    """单个字段损坏（端口非数字）不应丢掉其它配置（如 QQ 凭证）。"""
    tmp = Path(tempfile.mkdtemp(prefix="qbm_t_"))
    s = Settings(tmp)
    s.ensure_dirs()
    s.qq_official_appid = "102795166"
    s.qq_official_secret = "secret-value"
    s.save()
    data = json.loads((tmp / "settings.json").read_text(encoding="utf-8"))
    data["nonebot_port"] = "not-a-number"
    (tmp / "settings.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    s2 = Settings.load(tmp)
    assert s2.nonebot_port == 12111, s2.nonebot_port
    assert s2.qq_official_appid == "102795166", "损坏字段导致后续配置丢失"
    assert s2.qq_official_secret == "secret-value"


def test_settings_ignores_old_bg_fields():
    """旧版设置文件里的 bg_quality / bg_auto_degrade 应被忽略，不影响其它配置。"""
    tmp = Path(tempfile.mkdtemp(prefix="qbm_bgold_"))
    s = Settings(tmp)
    s.ensure_dirs()
    s.qq_official_appid = "102795166"
    s.save()
    data = json.loads((tmp / "settings.json").read_text(encoding="utf-8"))
    data["bg_quality"] = "4K60"
    data["bg_auto_degrade"] = False
    (tmp / "settings.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    s2 = Settings.load(tmp)
    assert s2.qq_official_appid == "102795166"
    assert not hasattr(s2, "bg_quality")
    assert not hasattr(s2, "bg_auto_degrade")


def test_start_all_rollback():
    """启动中途失败时应回滚已启动的组件（先 dsh 反序回 bot/qq）。"""
    from qbotmanager.core.manager import Manager
    tmp = Path(tempfile.mkdtemp(prefix="qbm_m_"))
    s = Settings(tmp)
    s.ensure_dirs()
    s.dsh_enabled = True
    m = Manager(s, on_log=lambda line: None)
    stopped = []
    started = []
    m.qq_channel.start = lambda *a, **k: None
    m.qq_channel.stop = lambda *a, **k: stopped.append("qq")
    m.start_bot = lambda *a, **k: started.append("bot")
    m.stop_bot = lambda: stopped.append("bot")

    def _dsh_fail(*a, **k):
        raise RuntimeError("dsh boom")
    m.start_dsh = _dsh_fail
    m.stop_dsh = lambda: stopped.append("dsh")

    try:
        m.start_all()
        raise AssertionError("expected RuntimeError")
    except RuntimeError as e:
        assert "已回滚" in str(e), str(e)
    assert started == ["bot"], started
    assert stopped == ["bot", "qq"], stopped


def test_find_root_fallback():
    ptr = Path(tempfile.mkdtemp(prefix="qbm_ptr_"))
    settings_mod.POINTER_DIR = ptr
    settings_mod.POINTER_FILE = ptr / "settings.json"
    settings_mod.RECENT_FILE = ptr / "recent_roots.json"
    root = Path.home() / f".qbm_test_root_{os.getpid()}"
    root.mkdir(parents=True, exist_ok=True)
    try:
        s = Settings(root)
        s.ensure_dirs()
        s.save()
        settings_mod.POINTER_FILE.unlink()
        found = settings_mod.Settings.find_root()
        assert found == s.root, f"find_root fallback failed: {found}"

        # 最近列表里即使残留临时目录（测试假根），也必须跳过，不能把程序带回 %TEMP%
        fake = Path(tempfile.mkdtemp(prefix="qbm_t_"))
        fake_settings = Settings(fake)
        fake_settings.ensure_dirs()
        fake_settings.save()
        settings_mod.RECENT_FILE.write_text(
            json.dumps([str(fake), str(root)], ensure_ascii=False), encoding="utf-8")
        found2 = settings_mod.Settings.find_root()
        assert found2 == s.root, f"temp root should be skipped: {found2}"
    finally:
        import shutil
        shutil.rmtree(root, ignore_errors=True)


def test_machine_code():
    from qbotmanager.core.license import machine_code
    mc = machine_code()
    assert len(mc) == 39 and mc.count("-") == 7
    assert all(c in "0123456789ABCDEF-" for c in mc)


def test_trial_key_parsing():
    import base64
    import time

    from qbotmanager.core import license as lic

    _trust_plan(lic)

    sig = b"z" * 64
    exp = int(time.time()) + 30 * 86400
    b32 = base64.b32encode(sig).decode()
    groups = "-".join(b32[i:i + 4] for i in range(0, len(b32), 4))
    key = f"TR1-{groups}-{exp}"
    assert lic._trial_parts(key) == (sig, exp)
    assert lic._trial_parts("TR1-XXXX") is None
    assert lic._trial_parts("PERM-AAAA-AAAA") is None


def test_verify_key_details_rejects_garbage():
    from qbotmanager.core import license as lic

    _trust_plan(lic)

    d = lic.verify_key_details(
        "ABCD-1234-ABCD-1234-ABCD-1234-ABCD-1234", "BAD-KEY")
    assert d["ok"] is False


def test_status_without_license_isolated():
    from qbotmanager.core import license as lic

    _trust_plan(lic)

    orig = lic.license_file
    tmp = Path(tempfile.mkdtemp(prefix="qbm_lic_"))
    lic.license_file = lambda: tmp / "license.json"
    try:
        st = lic.status()
        assert st["activated"] is False
        assert "未激活" in st["reason"]
    finally:
        lic.license_file = orig


def test_account_file_isolated():
    from qbotmanager.core import account

    orig = account.account_file
    tmp = Path(tempfile.mkdtemp(prefix="qbm_acct_"))
    account.account_file = lambda: tmp / "account.json"
    try:
        account.save_account({"email": "a@b.c", "token": "tok"})
        assert account.load_account()["email"] == "a@b.c"
        account.clear_account()
        assert account.load_account() is None
    finally:
        account.account_file = orig


def test_effective_now_uses_time_offset():
    from qbotmanager.core import license as lic

    _trust_plan(lic)

    lic_data = {"time_offset": 86400}
    assert abs(lic._effective_now(lic_data) - (time.time() + 86400)) < 2


def test_check_startup_requires_online_when_window_expired():
    from qbotmanager.core import license as lic

    _trust_plan(lic)

    calls = []
    orig = (lic.status, lic.load_license, lic.online_activate, lic.save_license)
    lic.status = lambda: {
        "activated": True, "machine_id": "M", "key": "K",
        "remaining_days": 5, "grace_remaining": 0,
    }
    lic.load_license = lambda: {
        "last_check": time.time(), "last_online": time.time() - 30 * 86400,
    }
    lic.online_activate = lambda mid, key: calls.append(1) or {
        "ok": False, "network": True, "reason": "offline"
    }
    lic.save_license = lambda d: None
    try:
        st = lic.check_startup()
        assert st["activated"] is False, st
        assert "联网验证超期" in st["reason"]
        assert calls, "复查窗口过期后必须发起联网验证"
    finally:
        (lic.status, lic.load_license, lic.online_activate, lic.save_license) = orig


def test_check_startup_grants_grace_when_offline():
    """复查窗口过期但只超了几天、又连不上服务器：进宽限期，仍然可用。"""
    from qbotmanager.core import license as lic

    _trust_plan(lic)

    calls = []
    orig = (lic.status, lic.load_license, lic.online_activate, lic.save_license)
    lic.status = lambda: {
        "activated": True, "machine_id": "M", "key": "K",
        "remaining_days": 5, "grace_remaining": 0,
    }
    lic.load_license = lambda: {"last_online": time.time() - 8 * 86400}   # 试用窗口 7 天，刚过 1 天
    lic.online_activate = lambda mid, key: calls.append(1) or {
        "ok": False, "network": True, "reason": "offline"
    }
    lic.save_license = lambda d: None
    try:
        st = lic.check_startup()
        assert st["activated"] is True, st
        assert st.get("grace_warn") is True, st
        assert "宽限" in st["reason"], st
        assert calls, "宽限期内也必须尝试联网复查"
    finally:
        (lic.status, lic.load_license, lic.online_activate, lic.save_license) = orig


def test_server_candidates_prefers_https():
    """候选地址：环境变量 > 上次成功 > 内置 HTTPS。

    公开代码里不再放明文 IP 回退（开源前已移除），所以默认候选必须全是 https。
    """
    from qbotmanager.core import license as lic

    _trust_plan(lic)

    orig = (lic.load_license, lic.SERVER_URL, lic.SERVER_URL_FALLBACKS)
    lic.load_license = lambda: None
    try:
        urls = lic._server_candidates()
        assert urls[0].startswith("https://"), urls
        assert all(u.startswith("https://") for u in urls), urls
        lic.load_license = lambda: {"server": "http://127.0.0.1:9999/"}
        assert lic._server_candidates()[0] == "http://127.0.0.1:9999", lic._server_candidates()
        os.environ["QBM_LICENSE_SERVER"] = "https://example.com/lic/"
        try:
            assert lic._server_candidates()[0] == "https://example.com/lic", lic._server_candidates()
        finally:
            os.environ.pop("QBM_LICENSE_SERVER", None)
    finally:
        (lic.load_license, lic.SERVER_URL, lic.SERVER_URL_FALLBACKS) = orig


def test_check_startup_passes_within_window():
    from qbotmanager.core import license as lic

    _trust_plan(lic)

    calls = []
    orig = (lic.status, lic.load_license, lic.online_activate, lic.save_license)
    lic.status = lambda: {
        "activated": True, "machine_id": "M", "key": "K",
        "remaining_days": 5, "grace_remaining": 0,
    }
    lic.load_license = lambda: {"last_online": time.time()}
    lic.online_activate = lambda mid, key: calls.append(1) or {"ok": True}
    lic.save_license = lambda d: None
    try:
        st = lic.check_startup()
        assert st["activated"] is True
        assert not calls, "复查窗口内不应联网"
    finally:
        (lic.status, lic.load_license, lic.online_activate, lic.save_license) = orig


def test_check_startup_rejects_clock_rollback():
    from qbotmanager.core import license as lic

    _trust_plan(lic)

    orig = (lic.status, lic.load_license, lic.online_activate, lic.save_license)
    lic.status = lambda: {
        "activated": True, "machine_id": "M", "key": "K",
        "remaining_days": None, "grace_remaining": 10,
    }
    lic.load_license = lambda: {"last_check": time.time() + 7200, "last_online": 0}
    lic.online_activate = lambda mid, key: {"ok": False, "network": True, "reason": "offline"}
    lic.save_license = lambda d: None
    try:
        st = lic.check_startup()
        assert st["activated"] is False
        assert "系统时间异常" in st["reason"]
    finally:
        (lic.status, lic.load_license, lic.online_activate, lic.save_license) = orig


def test_auto_trial_network_error():
    import urllib.error

    from qbotmanager.core import license as lic

    _trust_plan(lic)

    orig = lic.urllib.request.urlopen

    def _boom(*_a, **_k):
        raise urllib.error.URLError("down")

    lic.urllib.request.urlopen = _boom
    try:
        res = lic.auto_trial()
        assert res["ok"] is False
        assert res.get("network") is True
    finally:
        lic.urllib.request.urlopen = orig


def test_update_check_parse():
    from qbotmanager.core.update_check import _parse, newer_available
    assert _parse("0.1.0") == (0, 1, 0)
    assert newer_available("0.1.0", "0.1.1") is True
    assert newer_available("0.1.1", "0.1.0") is False


def test_migrate_roots():
    from qbotmanager.core import migrate
    tmp = Path(tempfile.mkdtemp(prefix="qbm_mig_"))
    s = Settings(tmp)
    s.ensure_dirs()
    s.deployed = {"python": True, "deps": True, "bot": True}
    s.save()
    assert migrate.is_install_root(tmp)
    assert migrate.is_deployed_root(tmp)
    ptr = Path(tempfile.mkdtemp(prefix="qbm_ptr2_"))
    migrate.POINTER_DIR = ptr
    migrate.POINTER_FILE = ptr / "settings.json"
    assert migrate.adopt_root(tmp)
    assert (ptr / "settings.json").exists()


def test_ai_config_bridge():
    from qbotmanager.core import ai_config
    tmp = Path(tempfile.mkdtemp(prefix="qbm_ai_"))
    s = Settings(tmp)
    s.ensure_dirs()
    assert ai_config.save_config(
        s, api_key="sk-test-123", api_url="https://api.deepseek.com", model="deepseek-v4-flash")
    p = ai_config.manager_file(s)
    assert p.exists() and "config" in p.parts and "ai" in p.parts
    cfg = ai_config.current_config(s)
    assert cfg["api_key"] == "sk-test-123" and cfg["model"] == "deepseek-v4-flash"
    assert ai_config.provider_key_for_url("https://api.deepseek.com") == "deepseek"
    assert ai_config.provider_key_for_url("https://api.deepseek.com/") == "deepseek"
    # 同名校验覆盖不新增
    ai_config.save_config(s, api_key="sk-new", api_url="https://api.deepseek.com", model="deepseek-v4-pro")
    confs = ai_config.read_manager(s)["ai_configs"]
    assert len(confs) == 1 and confs[0]["api_key"] == "sk-new"
    # brain_summary 走新路径
    from qbotmanager.core import message_store
    assert message_store.brain_summary(s)["model"] == "deepseek-v4-pro"
    # ai_enabled 持久化
    s.ai_enabled = False
    s.nonebot_enabled = False
    s.ai_platforms = {"qq": False, "wechat": True, "feishu": False, "telegram": True}
    s.save()
    assert Settings.load(tmp).ai_enabled is False
    assert Settings.load(tmp).nonebot_enabled is False
    assert Settings.load(tmp).ai_platforms == s.ai_platforms
    assert Settings(tmp).ai_enabled is True
    assert Settings(tmp).nonebot_enabled is True
    assert Settings(tmp).ai_platforms == {"qq": True, "wechat": True,
                                          "feishu": True, "telegram": True}
    # 人设与主动聊天（程序内设置桥）
    assert "星群" in ai_config.read_personality(s)
    assert ai_config.save_personality(s, "你是测试人格，回答简洁")
    assert ai_config.read_personality(s) == "你是测试人格，回答简洁"
    assert ai_config.save_proactive(
        s, enabled=True, targets=["10001", "20002"], groups=["30003"],
        interval_min=5, interval_max=10, cooldown=3,
        quiet_start=22, quiet_end=7)
    pro = ai_config.read_proactive(s)
    assert pro["enabled"] is True
    assert pro["targets"] == ["10001", "20002"]
    assert pro["groups"] == ["30003"]
    assert pro["interval_min"] == 5 and pro["interval_max"] == 10
    assert pro["cooldown"] == 3
    assert pro["quiet_start"] == 22 and pro["quiet_end"] == 7
    # 记忆与 MCP
    assert ai_config.read_memory_enabled(s) is True
    assert ai_config.save_memory_enabled(s, False)
    assert ai_config.read_memory_enabled(s) is False
    servers = {"demo": {"type": "sse", "enabled": True, "url": "http://127.0.0.1:8000/sse"}}
    assert ai_config.save_mcp(s, enabled=True, servers=servers)
    mcp = ai_config.read_mcp(s)
    assert mcp["enabled"] is True and mcp["servers"]["demo"]["url"].endswith("/sse")
    # 人设写入固定新路径（bot/config/ai）：旧路径存在时先迁移再写新路径
    old = s.bot_dir / "data" / "config" / "ai" / ai_config.MANAGER_NAME
    old.parent.mkdir(parents=True, exist_ok=True)
    old.write_text(json.dumps({"personality": "旧版人设"}), encoding="utf-8")
    assert ai_config.save_personality(s, "新版本人设")
    new = s.bot_dir / "config" / "ai" / ai_config.MANAGER_NAME
    assert json.loads(new.read_text(encoding="utf-8"))["personality"] == "新版本人设"


def test_ai_provider_presets():
    from qbotmanager.core import ai_config
    assert ai_config.AI_PROVIDERS[0]["key"] == "custom"
    for p in ai_config.AI_PROVIDERS[1:]:
        assert p["url"].startswith("https://"), p
        assert p["model"], p
    keys = {p["key"] for p in ai_config.AI_PROVIDERS}
    assert {"deepseek", "dashscope", "zhipu", "moonshot", "openai"} <= keys


def test_ai_platform_env():
    from qbotmanager.core import bot
    tmp = Path(tempfile.mkdtemp(prefix="qbm_env_"))
    s = Settings(tmp)
    s.ai_platforms = {"qq": False, "wechat": True, "feishu": False, "telegram": True}
    env = bot.ai_platform_env(s)
    assert env == {
        "AI_PLATFORM_QQ": "0",
        "AI_PLATFORM_WECHAT": "1",
        "AI_PLATFORM_FEISHU": "0",
        "AI_PLATFORM_TELEGRAM": "1",
    }
    # 旧配置缺字段时默认全开
    s2 = Settings(tmp)
    del s2.ai_platforms
    assert bot.ai_platform_env(s2) == {
        "AI_PLATFORM_QQ": "1",
        "AI_PLATFORM_WECHAT": "1",
        "AI_PLATFORM_FEISHU": "1",
        "AI_PLATFORM_TELEGRAM": "1",
    }


def test_qq_official_login_state():
    from qbotmanager.core.manager import Manager
    tmp = Path(tempfile.mkdtemp(prefix="qbm_nap_"))
    s = Settings(tmp)
    s.qq_channel = "official"
    s.qq_official_appid = "appid123"
    s.qq_official_token = "tok"
    s.qq_official_secret = "sec"
    m = Manager(s)
    st = m.qq_login_state()
    assert st["logged_in"] is False
    assert st["account"] == "appid123"
    assert st["reason"] in ("已配置", "等待 NoneBot 连接")
    assert m.qq_channel.accounts() == ["appid123"]
    assert m.qq_channel.qr_image_path() is None


def test_qq_onebot_channel():
    from qbotmanager.core import bot
    from qbotmanager.core.manager import Manager
    from qbotmanager.core.qq_channel import create_qq_channel
    tmp = Path(tempfile.mkdtemp(prefix="qbm_onebot_"))
    s = Settings(tmp)
    s.qq_channel = "onebot"
    s.qq_onebot_host = "127.0.0.1"
    s.qq_onebot_port = 3001
    s.qq_onebot_path = "/onebot/v11/ws"
    s.qq_onebot_token = "secret-token"
    s.qq_onebot_mode = "forward"
    s.qq_onebot_listen_host = "127.0.0.1"
    # 设置回环
    s.save()
    s2 = Settings.load(tmp)
    assert s2.qq_channel == "onebot"
    assert s2.qq_onebot_port == 3001
    assert s2.qq_onebot_token == "secret-token"
    assert s2.qq_onebot_mode == "forward"
    assert s2.qq_onebot_listen_host == "127.0.0.1"
    # 通道创建
    ch = create_qq_channel(s2)
    assert ch.key == "onebot"
    assert ch.accounts() == ["127.0.0.1:3001"]
    assert ch.qr_image_path() is None
    # 适配器与环境变量
    assert bot._enabled_qq_adapters(s2) == [("QQ", "nonebot.adapters.onebot.v11")]
    env_text = bot.build_env_text(s2)
    assert "ONEBOT_WS_URLS" in env_text
    assert "ws://127.0.0.1:3001/onebot/v11/ws" in env_text
    assert "ONEBOT_ACCESS_TOKEN=secret-token" in env_text
    assert "ONEBOT_WS_TOKEN=" not in env_text
    # Manager 登录状态
    m = Manager(s2)
    st = m.qq_login_state()
    assert st["account"] == "127.0.0.1:3001"

    # 反向 WS（推荐，默认）：地址可直接粘贴到协议端
    s2.qq_onebot_mode = "reverse"
    s2.qq_onebot_listen_host = "0.0.0.0"
    s2.nonebot_port = 12111
    env_text = bot.build_env_text(s2)
    assert "ONEBOT_WS_URLS" not in env_text
    assert "ONEBOT_ACCESS_TOKEN=secret-token" in env_text
    assert "HOST=0.0.0.0" in env_text
    ch2 = create_qq_channel(s2)
    assert ch2.reverse_ws_url() == "ws://127.0.0.1:12111/onebot/v11/ws"
    assert ch2.accounts() == ["ws://127.0.0.1:12111/onebot/v11/ws"]
    st2 = Manager(s2).qq_login_state()
    assert st2["account"] == "ws://127.0.0.1:12111/onebot/v11/ws"
    assert "反向" in st2["reason"]


def test_dsh_config_bridge():
    from qbotmanager.core import ai_config, bot, dsh as dsh_mod
    tmp = Path(tempfile.mkdtemp(prefix="qbm_dsh_"))
    s = Settings(tmp)
    s.ensure_dirs()
    s.qq_official_appid = "appid123"
    s.qq_official_token = "tok"
    s.qq_official_secret = "secret123"
    s.dsh_enabled = True
    s.dsh_require_mention = True
    assert ai_config.save_config(
        s, api_key="sk-test", api_url="https://api.deepseek.com",
        model="deepseek-v4-flash")
    assert ai_config.save_personality(s, "你是测试人格")
    # 未安装时 write_config 返回 False
    assert dsh_mod.write_config(s) is False
    # 模拟已安装 profile 目录
    dsh_mod.profile_dir(s).mkdir(parents=True, exist_ok=True)
    assert dsh_mod.write_config(s) is True
    text = dsh_mod.patch_file(s).read_text(encoding="utf-8")
    assert 'appId: "appid123"' in text
    assert 'appSecret: "secret123"' in text
    assert "deepseek-v4-flash" in text
    assert "groupPrompt:" in text and "你是测试人格" in text
    assert "tool-bash" in text and "disabled: true" in text
    # settings.yaml：DeepSeek 默认 provider 与 OpenAI 兼容地址
    sy = dsh_mod.settings_yaml_file(s).read_text(encoding="utf-8")
    assert "provider: \"deepseek\"" in sy
    assert "https://api.deepseek.com/v1" in sy
    assert "apiKeyEnv: QBM_DSH_API_KEY" in sy
    assert "deepseek-v4-flash" in sy
    # dsh 启用时 NoneBot 不再注册 QQ 适配器（避免同 AppID 双网关）
    assert bot._enabled_qq_adapters(s) == []
    s.dsh_enabled = False
    assert bot._enabled_qq_adapters(s) != []
    # 非 DeepSeek 服务商：provider/baseURL/models 随 AI 大脑切换
    ai_config.save_config(
        s, api_key="sk-dash", api_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model="qwen3.7-flash")
    s.dsh_enabled = True
    assert dsh_mod.write_config(s) is True
    text2 = dsh_mod.patch_file(s).read_text(encoding="utf-8")
    assert 'provider: "dashscope"' in text2
    assert "qwen3.7-flash" in text2
    sy2 = dsh_mod.settings_yaml_file(s).read_text(encoding="utf-8")
    assert "dashscope" in sy2
    assert "dashscope.aliyuncs.com" in sy2
    assert "qwen3.7-flash" in sy2
    # provider id 清洗
    s.dsh_provider = "My Provider!"
    assert dsh_mod.provider_key(s) == "myprovider"
    s.dsh_provider = ""
    # settings 回环
    s.dsh_enabled = True
    s.dsh_api_key = "sk-xxx"
    s.dsh_model = "deepseek-v4-pro"
    s.dsh_provider = "deepseek-official"
    s.save()
    s2 = Settings.load(tmp)
    assert s2.dsh_enabled is True
    assert s2.dsh_api_key == "sk-xxx"
    assert s2.dsh_model == "deepseek-v4-pro"
    assert s2.dsh_provider == "deepseek-official"


def test_unified_brain_config():
    """统一大脑：dsh 配置含桥插件块；开启 dsh 后旧 AI 插件停用微信处理。"""
    from qbotmanager.core import bot as bot_mod
    from qbotmanager.core import dsh as dsh_mod
    tmp = Path(tempfile.mkdtemp(prefix="qbm_ub_"))
    s = Settings(tmp)
    s.ensure_dirs()
    text = dsh_mod.build_patch_text(s)
    assert "qbm-bridge" in text
    assert "18650" in text
    assert "preset: astros" in text
    assert "agent-presets" in text
    assert "bindingsFile" in text
    env = bot_mod.ai_platform_env(s)
    assert env["AI_PLATFORM_WECHAT"] == "1"
    s.dsh_enabled = True
    env = bot_mod.ai_platform_env(s)
    assert env["AI_PLATFORM_WECHAT"] == "0"


def test_write_preset():
    """统一大脑 preset：QQ 与微信桥共用统一人设，人设变更后重新生成。"""
    from qbotmanager.core import ai_config, dsh as dsh_mod
    tmp = Path(tempfile.mkdtemp(prefix="qbm_preset_"))
    s = Settings(tmp)
    s.ensure_dirs()
    d = dsh_mod.agent_preset_dir(s)
    assert dsh_mod.write_preset(s) is True
    assert (d / "preset.yml").exists()
    comp = (d / "agent.cordis.yml").read_text(encoding="utf-8")
    assert "@deepseek-ai/dsh-persona" in comp
    assert "星群" in comp
    # 人设变化后 preset 同步更新
    ai_config.save_personality(s, "你是星群助手，回答极简")
    assert dsh_mod.write_preset(s) is True
    comp2 = (d / "agent.cordis.yml").read_text(encoding="utf-8")
    assert "你是星群助手" in comp2
    assert "你叫px" not in comp2


def test_ensure_bridge_skips_when_marked():
    """桥已接入（marker 存在）时 ensure_bridge 不应再调 dsh CLI。"""
    from qbotmanager.core import dsh as dsh_mod
    tmp = Path(tempfile.mkdtemp(prefix="qbm_br_"))
    s = Settings(tmp)
    s.ensure_dirs()
    profile = tmp / "dsh" / "home" / "profiles" / "qqbot"
    profile.mkdir(parents=True)
    (profile / ".qbm_bridge_installed").write_text("ok", encoding="utf-8")
    calls = []
    orig_installed = dsh_mod.is_installed
    orig_run = dsh_mod.run_capture
    try:
        dsh_mod.is_installed = lambda settings: True
        dsh_mod.run_capture = lambda *a, **k: calls.append(a) or (0, "")
        assert dsh_mod.ensure_bridge(s) is True
    finally:
        dsh_mod.is_installed = orig_installed
        dsh_mod.run_capture = orig_run
    assert calls == []


def test_dsh_install_skips_when_installed():
    """已安装时点“安装/修复”不应重跑 npm install，只刷新配置。"""
    from qbotmanager.core import dsh as dsh_mod
    tmp = Path(tempfile.mkdtemp(prefix="qbm_dsh_"))
    s = Settings(tmp)
    s.ensure_dirs()
    orig_installed = dsh_mod.is_installed
    orig_write = dsh_mod.write_config
    calls = []
    try:
        dsh_mod.is_installed = lambda settings: True
        dsh_mod.write_config = lambda settings, log=None: calls.append("write") or True
        dsh_mod.install(s, log=lambda line: calls.append(str(line)))
    finally:
        dsh_mod.is_installed = orig_installed
        dsh_mod.write_config = orig_write
    assert "write" in calls, calls
    assert not any("正在下载 dsh" in c or "npm install" in c for c in calls), calls


def test_dsh_uninstall():
    """重装前卸载：删除整个 dsh 目录并清除指向目录内 Node 的配置。"""
    from qbotmanager.core import dsh as dsh_mod
    tmp = Path(tempfile.mkdtemp(prefix="qbm_dshu_"))
    s = Settings(tmp)
    s.ensure_dirs()
    d = dsh_mod.dsh_dir(s)
    (d / "home").mkdir(parents=True)
    (d / "node_modules" / "@deepseek-ai" / "dsh" / "lib").mkdir(parents=True)
    (d / "node_modules" / "@deepseek-ai" / "dsh" / "lib" / "bin.js").write_text("", encoding="utf-8")
    s.dsh_node_exe = str(d / "node" / "node.exe")
    dsh_mod.uninstall(s)
    assert not d.exists()
    assert s.dsh_node_exe == ""


class _FakeProc:
    def __init__(self, pid):
        self.pid = pid

    def poll(self):
        return None


def test_start_dsh_cleans_bridge_port():
    """启动 dsh 前应强制清理 18650 残留监听，避免 EADDRINUSE 崩溃。"""
    from qbotmanager.core import dsh as dsh_mod
    from qbotmanager.core import manager as manager_mod
    from qbotmanager.core.manager import Manager
    tmp = Path(tempfile.mkdtemp(prefix="qbm_dshp_"))
    s = Settings(tmp)
    s.ensure_dirs()
    m = Manager(s, on_log=lambda line: None)
    killed = []
    orig_start = dsh_mod.start
    orig_pids = m._port_pids
    orig_cmd = manager_mod._proc_cmdline
    orig_alive = manager_mod._pid_alive
    orig_kill = manager_mod._kill_pid_tree
    try:
        dsh_mod.start = lambda settings, log=None, cancel_event=None: _FakeProc(4242)
        m._port_pids = lambda port: [999] if port == dsh_mod.BRIDGE_PORT else []
        manager_mod._proc_cmdline = lambda pid, timeout=15: "C:\\Temp\\node.exe --profile m1"
        manager_mod._pid_alive = lambda pid: pid > 0
        manager_mod._kill_pid_tree = lambda pid, timeout=15: killed.append(pid)
        m.start_dsh()
    finally:
        dsh_mod.start = orig_start
        m._port_pids = orig_pids
        manager_mod._proc_cmdline = orig_cmd
        manager_mod._pid_alive = orig_alive
        manager_mod._kill_pid_tree = orig_kill
    assert killed == [999], killed


def test_dsh_running_requires_identity():
    """崩溃留下的幽灵 PID 不能把 dsh 误判为正在运行。"""
    from qbotmanager.core import manager as manager_mod
    from qbotmanager.core.manager import Manager
    tmp = Path(tempfile.mkdtemp(prefix="qbm_ghost_"))
    s = Settings(tmp)
    s.ensure_dirs()
    m = Manager(s, on_log=lambda line: None)
    m._save_runtime(dsh_pid=1234)
    orig_cmd = manager_mod._proc_cmdline
    orig_alive = manager_mod._pid_alive
    try:
        manager_mod._pid_alive = lambda pid: pid == 1234
        manager_mod._proc_cmdline = lambda pid, timeout=15: "C:\\other\\app.exe"
        assert m.dsh_running() is False
        m._dsh_verify = None  # 清缓存再换命令行验证
        manager_mod._proc_cmdline = lambda pid, timeout=15: (
            '"C:\\Program Files\\nodejs\\node.exe" D:\\ai\\dsh\\lib\\bin.js --profile qqbot')
        assert m.dsh_running() is True
    finally:
        manager_mod._proc_cmdline = orig_cmd
        manager_mod._pid_alive = orig_alive


def test_dsh_running_caches_identity():
    """GUI 每 2 秒刷新都会问 dsh 是否运行，同 PID 只能查一次命令行。"""
    from qbotmanager.core import manager as manager_mod
    from qbotmanager.core.manager import Manager
    tmp = Path(tempfile.mkdtemp(prefix="qbm_dshc_"))
    s = Settings(tmp)
    s.ensure_dirs()
    m = Manager(s, on_log=lambda line: None)
    m._save_runtime(dsh_pid=1234)
    calls = []
    orig_cmd = manager_mod._proc_cmdline
    orig_alive = manager_mod._pid_alive
    try:
        manager_mod._pid_alive = lambda pid: pid == 1234
        manager_mod._proc_cmdline = lambda pid, timeout=15: calls.append(pid) or (
            '"C:\\Program Files\\nodejs\\node.exe" D:\\ai\\dsh\\lib\\bin.js --profile qqbot')
        assert m.dsh_running() is True
        assert m.dsh_running() is True
        assert m.dsh_running() is True
        assert calls == [1234], calls
        # 验证失败的幽灵 PID：5 秒内复用失败结果，不再反复拉子进程
        m._dsh_verify = None
        manager_mod._proc_cmdline = lambda pid, timeout=15: calls.append(pid) or "C:\\other\\app.exe"
        assert m.dsh_running() is False
        assert m.dsh_running() is False
        assert calls == [1234, 1234], calls
    finally:
        manager_mod._proc_cmdline = orig_cmd
        manager_mod._pid_alive = orig_alive


def test_ensure_port_closed_force():
    """force=True 时专用端口上的无关进程也应被清理；非 force 仍按身份匹配。"""
    from qbotmanager.core import manager as manager_mod
    from qbotmanager.core.manager import Manager
    tmp = Path(tempfile.mkdtemp(prefix="qbm_port_"))
    s = Settings(tmp)
    s.ensure_dirs()
    m = Manager(s, on_log=lambda line: None)
    killed = []
    orig_pids = m._port_pids
    orig_cmd = manager_mod._proc_cmdline
    orig_alive = manager_mod._pid_alive
    orig_kill = manager_mod._kill_pid_tree
    try:
        m._port_pids = lambda port: [111] if port == 18650 else []
        manager_mod._proc_cmdline = lambda pid, timeout=15: "C:\\other\\app.exe"
        manager_mod._pid_alive = lambda pid: True
        manager_mod._kill_pid_tree = lambda pid, timeout=15: killed.append(pid)
        m._ensure_port_closed(18650, "AstroSwarm", force=True)
        assert killed == [111], killed
        m._port_pids = lambda port: [222] if port == 18650 else []
        m._ensure_port_closed(18650, "AstroSwarm", force=False)
        assert killed == [111], "非 force 时不应清理命令行不匹配的进程"
    finally:
        m._port_pids = orig_pids
        manager_mod._proc_cmdline = orig_cmd
        manager_mod._pid_alive = orig_alive
        manager_mod._kill_pid_tree = orig_kill


def test_stop_all_cleans_bridge_port():
    """停止全部应同时兜底清理 NoneBot 端口与 dsh 桥端口。"""
    from qbotmanager.core import dsh as dsh_mod
    from qbotmanager.core.manager import Manager
    tmp = Path(tempfile.mkdtemp(prefix="qbm_stop_"))
    s = Settings(tmp)
    s.ensure_dirs()
    m = Manager(s, on_log=lambda line: None)
    m.stop_dsh = lambda: None
    m.stop_bot = lambda: None
    m.qq_channel.stop = lambda: None
    seen = []
    orig = m._ensure_port_closed
    try:
        m._ensure_port_closed = lambda port, hint, force=False: seen.append((port, hint, force))
        m.stop_all()
    finally:
        m._ensure_port_closed = orig
    assert any(p == s.nonebot_port and not force for p, _h, force in seen), seen
    assert any(p == dsh_mod.BRIDGE_PORT and force for p, _h, force in seen), seen


def test_feature_gate_not_activated():
    from qbotmanager.core import license as lic

    _trust_plan(lic)

    orig = (lic.status, lic.load_license)
    try:
        lic.status = lambda: {"activated": False, "reason": "未激活"}
        lic.load_license = lambda: None
        gate = lic.feature_gate()
        assert gate["full"] is False
        assert "QQ" in gate["reason"] and "未开通" in gate["reason"]
    finally:
        (lic.status, lic.load_license) = orig


def test_feature_gate_trial_only_qq():
    from qbotmanager.core import license as lic

    _trust_plan(lic)

    orig = (lic.status, lic.load_license)
    try:
        lic.status = lambda: {
            "activated": True,
            "expires_at": time.time() + 86400,
            "remaining_days": 1,
            "trial": True,
        }
        lic.load_license = lambda: {"plan": "trial"}
        gate = lic.feature_gate()
        assert gate["full"] is False
        assert "QQ" in gate["reason"]
    finally:
        (lic.status, lic.load_license) = orig


def test_feature_gate_permanent_unlocks_all():
    from qbotmanager.core import license as lic

    _trust_plan(lic)

    orig = (lic.status, lic.load_license)
    try:
        lic.status = lambda: {"activated": True, "expires_at": None}
        lic.load_license = lambda: {"plan": "permanent"}
        gate = lic.feature_gate()
        assert gate["full"] is True and gate["all_plugins"] is True
        assert gate["member"] is True
    finally:
        (lic.status, lic.load_license) = orig


def test_feature_gate_monthly_is_member_not_all_plugins():
    """月费档 = 付费会员（解锁微信），但**不是**「解锁全部付费包」。

    只有 plans.json 里 all_plugins=true 的档位（目前只有 permanent）才是 full。
    旧行为（月费也 full=True）会让月费用户装遍付费包，与服务端下载口口径不一致。
    """
    from qbotmanager.core import license as lic

    _trust_plan(lic)

    orig = (lic.status, lic.load_license)
    try:
        lic.status = lambda: {
            "activated": True,
            "expires_at": time.time() + 86400 * 10,
        }
        lic.load_license = lambda: {
            "plan": "monthly",
            "plan_expires_at": time.time() + 86400 * 10,
        }
        gate = lic.feature_gate()
        assert gate["full"] is False and gate["all_plugins"] is False, gate
        assert gate["member"] is True, gate
        assert gate["reason"] == ""
    finally:
        (lic.status, lic.load_license) = orig


def test_feature_gate_expired_plan_locks():
    from qbotmanager.core import license as lic

    _trust_plan(lic)

    orig = (lic.status, lic.load_license)
    try:
        lic.status = lambda: {
            "activated": True,
            "expires_at": time.time() + 86400 * 10,
        }
        lic.load_license = lambda: {
            "plan": "monthly",
            "plan_expires_at": time.time() - 1,
        }
        assert lic.feature_gate()["full"] is False
    finally:
        (lic.status, lic.load_license) = orig


def test_save_plan_persists():
    from qbotmanager.core import license as lic

    _trust_plan(lic)

    tmp = Path(tempfile.mkdtemp(prefix="qbm_licplan_"))
    orig = lic.license_file
    try:
        lic.license_file = lambda: tmp / "license.json"
        lic.save_license({"machine_id": "TEST", "key": "TR1-X"})
        lic.save_plan("monthly", time.time() + 86400)
        data = lic.load_license() or {}
        assert data.get("plan") == "monthly"
        assert float(data.get("plan_expires_at") or 0) > 0
    finally:
        lic.license_file = orig


def test_entitlements_roundtrip():
    """插件商店权益：plan/到期/已购插件本地持久化；会员不等于「解锁全部付费包」。"""
    from qbotmanager.core import license as lic

    _trust_plan(lic)

    tmp = Path(tempfile.mkdtemp(prefix="qbm_ent_"))
    orig = lic.license_file
    try:
        lic.license_file = lambda: tmp / "license.json"
        lic.save_license({"machine_id": "TEST", "key": "TR1-X"})
        # 月费档：是会员（解锁微信），但不解锁全部付费包
        lic.save_plan("monthly", time.time() + 86400,
                      ["pro-pack", "group-manager"])
        ent = lic.entitlements()
        assert ent["plan"] == "monthly"
        assert ent["full"] is False and ent["all_plugins"] is False
        assert ent["member"] is True
        assert ent["owned_plugins"] == ["pro-pack", "group-manager"]

        # 永久档：all_plugins=true → 解锁全部付费包
        lic.save_plan("permanent", 0, ["pro-pack", "group-manager"])
        ent = lic.entitlements()
        assert ent["full"] is True and ent["member"] is True

        # 会员到期：full/member 都变 false，单独购买记录保留
        lic.save_plan("monthly", time.time() - 1)
        ent = lic.entitlements()
        assert ent["full"] is False and ent["member"] is False
        assert ent["owned_plugins"] == ["pro-pack", "group-manager"]
    finally:
        lic.license_file = orig


def test_wechat_adapter_auto_sync_on_first_status():
    """微信页首次查状态应自动同步 iLink 适配器（付费用户不再显示未安装）。"""
    from qbotmanager.core import license as lic

    _trust_plan(lic)
    from qbotmanager.core.manager import Manager
    from qbotmanager.core.settings import Settings

    tmp = Path(tempfile.mkdtemp(prefix="qbm_wxsync_"))
    s = Settings(tmp)
    s.ensure_dirs()
    orig = lic.license_file
    try:
        lic.license_file = lambda: tmp / "license.json"
        lic.save_license({"machine_id": "TEST", "key": "TR1-X"})
        lic.save_plan("permanent", 0)
        m = Manager(s)
        st = m.wechat_status()
        assert st["installed"] is True, st
        assert (s.plugins_dir / "nonebot_adapter_ilink").is_dir()
    finally:
        lic.license_file = orig


def test_apply_wechat_gate_removes_and_restores_adapter():
    from qbotmanager.core import bot
    from qbotmanager.core.settings import Settings

    tmp = Path(tempfile.mkdtemp(prefix="qbm_gate_"))
    s = Settings(tmp)
    s.ensure_dirs()
    target = s.plugins_dir / "nonebot_adapter_ilink"
    target.mkdir(parents=True)
    (target / "client.py").write_text("x", encoding="utf-8")
    assert bot.apply_wechat_gate(s, full=False) is False
    assert not target.exists(), "试用模式应移除微信适配器"
    assert bot.apply_wechat_gate(s, full=True) is True
    assert (target / "client.py").exists(), "正式激活应恢复微信适配器"


def test_build_bot_env_gates_wechat():
    """build_bot_env 在试用闸门下应注入 AI_PLATFORM_WECHAT=0。"""
    from qbotmanager.core import bot
    from qbotmanager.core import license as lic

    _trust_plan(lic)
    from qbotmanager.core.settings import Settings

    tmp = Path(tempfile.mkdtemp(prefix="qbm_botgate_"))
    s = Settings(tmp)
    s.ensure_dirs()
    orig = lic.feature_gate
    try:
        # 微信通道看 member，不是 full（full = 解锁全部付费包）
        lic.feature_gate = lambda: {"full": False, "member": False, "reason": "试用"}
        env = bot.build_bot_env(s)
        assert env.get("AI_PLATFORM_WECHAT") == "0", "试用闸门应关闭微信 AI 处理"

        # 月费档：member=True 但没有 all_plugins → 微信照常开
        lic.feature_gate = lambda: {"full": False, "member": True, "reason": ""}
        env = bot.build_bot_env(s)
        assert env.get("AI_PLATFORM_WECHAT", "1") == "1", "会员档应恢复微信 AI 处理"
    finally:
        lic.feature_gate = orig


def test_entitlement_signature_is_required():
    """光改本地 license.json 不再解锁；只有带服务器签名的权益才生效。"""
    import base64
    import importlib

    from nacl.signing import SigningKey

    from qbotmanager.core import license as lic

    # 前面的用例用 _trust_plan 短接过校验，这里要拿回真身再测
    importlib.reload(lic)

    tmp = Path(tempfile.mkdtemp(prefix="qbm_ent_sig_"))
    orig = (lic.license_file, lic.PUBLIC_KEY_HEX, lic.machine_code)
    try:
        sk = SigningKey.generate()
        lic.PUBLIC_KEY_HEX = sk.verify_key.encode().hex()
        lic.machine_code = lambda: "TEST-MACHINE"
        lic.license_file = lambda: tmp / "license.json"

        # ① 裸改 license.json：plan=permanent + 塞一个已购插件，但没有签名
        lic.save_license({"machine_id": "M", "key": "K", "plan": "permanent",
                          "owned_plugins": ["pro-pack"]})
        assert lic.feature_gate()["full"] is False, "无签名不该解锁微信"
        ent = lic.entitlements()
        assert ent["full"] is False and ent["owned_plugins"] == []

        # ② 合法签名（覆盖 plan/到期/已购插件）→ 解锁
        payload = lic.entitlement_payload("TEST-MACHINE", "permanent", 0, ["pro-pack"])
        sig = base64.b64encode(sk.sign(payload.encode()).signature).decode()
        lic.save_plan("permanent", 0, ["pro-pack"], sig=sig)
        assert lic.feature_gate()["full"] is True
        assert lic.entitlements()["owned_plugins"] == ["pro-pack"]

        # ③ 签过之后又偷改字段（多塞一个已购）→ 签名失效，回到免费版
        data = lic.load_license() or {}
        data["owned_plugins"] = ["pro-pack", "group-manager"]
        lic.save_license(data)
        assert lic.entitlements()["owned_plugins"] == []
        assert lic.feature_gate()["full"] is False

        # ④ 换个机器码也应失效（权益绑定机器）
        lic.machine_code = lambda: "OTHER-MACHINE"
        assert lic.feature_gate()["full"] is False

        # ⑤ time_offset 封顶 ±1 天，改大也续不了期
        assert lic._effective_now({"time_offset": 10 ** 9}) - time.time() <= 86400 + 1
        assert abs(lic._effective_now({"time_offset": -10 ** 9}) - time.time()) <= 86400 + 1
    finally:
        lic.license_file, lic.PUBLIC_KEY_HEX, lic.machine_code = orig


def test_log_export_whitelist_and_content():
    """日志导出：名字走白名单（给路径也没用）、只取尾部、缺文件要报错。"""
    from qbotmanager.core import log_export as le

    tmp = Path(tempfile.mkdtemp(prefix="qbm_logexp_"))
    (tmp / "nonebot.log").write_text("机器人一行\n", encoding="utf-8")
    (tmp / "deploy.log").write_text("部署一行\n", encoding="utf-8")

    # 白名单外的名字连路径都不拼：目录穿越 / 绝对路径都不行
    for bad in ("../../etc/passwd", "C:/Windows/win.ini", "nope", "nonebot.log"):
        try:
            le.resolve(tmp, bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"非法日志名应被拒绝：{bad}")

    one = tmp / "out" / "one.log"
    res = le.export(tmp, "nonebot", one)
    assert res["bytes"] > 0
    text = one.read_text(encoding="utf-8")
    assert "机器人一行" in text and "部署一行" not in text

    every = tmp / "out" / "all.log"
    le.export_all(tmp, every)
    merged = every.read_text(encoding="utf-8")
    assert "===== nonebot" in merged and "===== deploy" in merged
    assert "机器人一行" in merged and "部署一行" in merged

    big = tmp / "big.log"
    big.write_bytes(b"x" * 100 + b"END")
    assert le.read_tail(big, 3) == b"END"
    assert le.read_tail(tmp / "missing.log") == b""
    try:
        le.export(tmp, "manager", tmp / "nope.log")
    except FileNotFoundError:
        pass
    else:
        raise AssertionError("日志文件不存在时应该抛 FileNotFoundError，让界面提示，而不是写个空文件")


def test_normalize_mcp_servers_rules():
    """MCP 配置逐项校验：type 白名单、stdio 要 command、其余要 url、名称长度。"""
    from qbotmanager.core import ai_config

    clean = ai_config.normalize_mcp_servers({
        "天气": {"type": "sse", "url": "https://example.com/sse", "enabled": False,
               "headers": {"X-A": "1"}, "多余字段": "丢掉"},
        "本地脚本": {"type": "stdio", "command": "python", "args": ["-m", "x"]},
        "默认类型": {"url": "https://example.com/sse"},
    })
    assert clean["天气"] == {"type": "sse", "enabled": False,
                            "url": "https://example.com/sse", "headers": {"X-A": "1"}}
    assert clean["本地脚本"]["command"] == "python" and clean["本地脚本"]["enabled"] is True
    assert clean["默认类型"]["type"] == "sse"
    assert ai_config.normalize_mcp_servers(None) == {}
    assert ai_config.normalize_mcp_servers({}) == {}

    bad_cases = {
        "缺 url": {"x": {"type": "sse"}},
        "缺 command": {"x": {"type": "stdio"}},
        "type 不认识": {"x": {"type": "udp", "url": "u"}},
        "名称是空的": {"": {"type": "sse", "url": "u"}},
        "名称太长": {"x" * 65: {"type": "sse", "url": "u"}},
        "配置不是对象": {"x": "not-a-dict"},
        "顶层不是对象": ["x"],
    }
    for why, payload in bad_cases.items():
        try:
            ai_config.normalize_mcp_servers(payload)
        except ValueError as exc:
            assert str(exc).strip(), why
        else:
            raise AssertionError(f"应该报错：{why}")


def test_save_entitlements_never_wipes_signature():
    """例行同步拿到「不带签名」的响应时不能覆盖本机权益（否则买过的插件当场失效）。"""
    from qbotmanager.core import license as lic

    _trust_plan(lic)

    tmp = Path(tempfile.mkdtemp(prefix="qbm_entguard_"))
    orig = lic.license_file
    try:
        lic.license_file = lambda: tmp / "license.json"
        lic.save_license({"machine_id": "TEST", "key": "TR1-X"})
        lic.save_plan("permanent", 0, ["market-pack"], sig="SIG-VALID", machine_id="TEST")

        # 1) 响应里没有 entitlement_sig：一个字都不许改
        assert lic.save_entitlements_from_account(
            {"plan": "none", "owned_plugins": []}) is False
        data = lic.load_license() or {}
        assert data.get("plan") == "permanent", data
        assert data.get("plan_sig") == "SIG-VALID", data
        assert data.get("owned_plugins") == ["market-pack"], data

        # 非 dict / 空响应同样不能写
        assert lic.save_entitlements_from_account(None) is False

        # 2) 带签名才落盘（含换机器后的机器码与已购清单）
        assert lic.save_entitlements_from_account({
            "plan": "monthly",
            "plan_expires_at": time.time() + 100,
            "owned_plugins": ["a", "b"],
            "entitlement_sig": "SIG-2",
            "entitlement_machine": "TEST",
        }) is True
        data = lic.load_license() or {}
        assert data.get("plan") == "monthly" and data.get("plan_sig") == "SIG-2", data
        assert data.get("owned_plugins") == ["a", "b"], data
        assert data.get("plan_machine") == "TEST", data
    finally:
        lic.license_file = orig


if __name__ == "__main__":
    test_message_store()
    print("OK message_store")
    test_message_store_dsh()
    print("OK message_store_dsh")
    test_settings_roundtrip()
    print("OK settings_roundtrip")
    test_settings_load_bad_port_keeps_creds()
    print("OK settings_load_bad_port_keeps_creds")
    test_settings_ignores_old_bg_fields()
    print("OK settings_ignores_old_bg_fields")
    test_start_all_rollback()
    print("OK start_all_rollback")
    test_find_root_fallback()
    print("OK find_root")
    test_machine_code()
    print("OK machine_code")
    test_trial_key_parsing()
    print("OK trial_key_parsing")
    test_verify_key_details_rejects_garbage()
    print("OK verify_key_details_rejects_garbage")
    test_status_without_license_isolated()
    print("OK status_without_license_isolated")
    test_account_file_isolated()
    print("OK account_file_isolated")
    test_effective_now_uses_time_offset()
    print("OK effective_now_uses_time_offset")
    test_check_startup_requires_online_when_window_expired()
    print("OK check_startup_requires_online_when_window_expired")
    test_check_startup_passes_within_window()
    print("OK check_startup_passes_within_window")
    test_check_startup_rejects_clock_rollback()
    print("OK check_startup_rejects_clock_rollback")
    test_check_startup_grants_grace_when_offline()
    print("OK check_startup_grants_grace_when_offline")
    test_server_candidates_prefers_https()
    print("OK server_candidates_prefers_https")
    test_auto_trial_network_error()
    print("OK auto_trial_network_error")
    test_update_check_parse()
    print("OK update_check_parse")
    test_migrate_roots()
    print("OK migrate_roots")
    test_ai_config_bridge()
    print("OK ai_config_bridge")
    test_ai_provider_presets()
    print("OK ai_provider_presets")
    test_ai_platform_env()
    print("OK ai_platform_env")
    test_qq_official_login_state()
    print("OK qq_official_login_state")
    test_qq_onebot_channel()
    print("OK qq_onebot_channel")
    test_dsh_config_bridge()
    print("OK dsh_config_bridge")
    test_unified_brain_config()
    print("OK unified_brain_config")
    test_write_preset()
    print("OK write_preset")
    test_ensure_bridge_skips_when_marked()
    print("OK ensure_bridge_skips_when_marked")
    test_dsh_install_skips_when_installed()
    print("OK dsh_install_skips_when_installed")
    test_dsh_uninstall()
    print("OK dsh_uninstall")
    test_start_dsh_cleans_bridge_port()
    print("OK start_dsh_cleans_bridge_port")
    test_dsh_running_requires_identity()
    print("OK dsh_running_requires_identity")
    test_dsh_running_caches_identity()
    print("OK dsh_running_caches_identity")
    test_ensure_port_closed_force()
    print("OK ensure_port_closed_force")
    test_stop_all_cleans_bridge_port()
    print("OK stop_all_cleans_bridge_port")
    test_feature_gate_not_activated()
    print("OK feature_gate_not_activated")
    test_feature_gate_trial_only_qq()
    print("OK feature_gate_trial_only_qq")
    test_feature_gate_permanent_unlocks_all()
    print("OK feature_gate_permanent_unlocks_all")
    test_feature_gate_monthly_is_member_not_all_plugins()
    print("OK feature_gate_monthly_is_member_not_all_plugins")
    test_feature_gate_expired_plan_locks()
    print("OK feature_gate_expired_plan_locks")
    test_save_plan_persists()
    print("OK save_plan_persists")
    test_entitlements_roundtrip()
    print("OK entitlements_roundtrip")
    test_entitlement_signature_is_required()
    print("OK entitlement_signature_is_required")

    test_wechat_adapter_auto_sync_on_first_status()
    print("OK wechat_adapter_auto_sync")
    test_apply_wechat_gate_removes_and_restores_adapter()
    print("OK apply_wechat_gate_removes_and_restores_adapter")
    test_build_bot_env_gates_wechat()
    print("OK build_bot_env_gates_wechat")
    test_log_export_whitelist_and_content()
    print("OK log_export")
    test_normalize_mcp_servers_rules()
    print("OK normalize_mcp_servers")
    test_save_entitlements_never_wipes_signature()
    print("OK save_entitlements_guard")
