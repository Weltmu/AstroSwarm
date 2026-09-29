# -*- coding: utf-8 -*-
"""智能体档案测试：档案加载、通道能力矩阵、唤醒词生成兜底、设置回环。"""
import sys
import tempfile
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
if not os.environ.get("QBM_POINTER_DIR"):
    os.environ["QBM_POINTER_DIR"] = str(Path(tempfile.mkdtemp(prefix="qbm_test_ptr_")))

from qbotmanager.core import agent_profile  # noqa: E402
from qbotmanager.core.settings import Settings  # noqa: E402


def test_profile_liqinghan_defaults():
    prof = agent_profile.load_profile("liqinghan")
    assert prof["id"] == "liqinghan"
    assert "李清菡" in prof["default_wake_words"]
    assert prof["tools"]


def test_profile_unknown_returns_none():
    assert agent_profile.load_profile("not-exists") is None


def test_capability_qq_group_has_admin_and_voice():
    caps = agent_profile.channel_capabilities("qq:group")
    assert {"group_admin", "voice", "proactive", "group_interject"} <= caps


def test_capability_wechat_private_disables_group_and_proactive():
    caps = agent_profile.channel_capabilities("wechat:private")
    assert "group_admin" not in caps
    assert "proactive" not in caps
    assert "group_interject" not in caps
    assert "chat" in caps


def test_capability_unknown_channel_empty():
    assert agent_profile.channel_capabilities("napcat:group") == set()


def test_enabled_tools_wechat_drops_admin_tools():
    tools = ["mute_user", "mute_all", "set_reminder", "game_guess", "describe_image"]
    # 微信无群管/无主动推送/无视觉，只保留普通聊天工具
    assert agent_profile.enabled_tools("wechat:private", tools) == ["game_guess"]


def test_wake_words_regex_extract_from_persona():
    words = agent_profile.extract_wake_words("你是李清菡，19岁大学生，群友都叫我学姐")
    assert "李清菡" in words and "学姐" in words


def test_wake_words_regex_empty_persona():
    assert agent_profile.extract_wake_words("") == []


def test_parse_wake_words_fences_and_bad_items():
    raw = "```json\n[\"李清菡\", \"学姐\", \"\", \"a,b\", 42]\n```"
    assert agent_profile.parse_wake_words(raw) == ["李清菡", "学姐"]


def test_parse_wake_words_not_json_returns_none():
    assert agent_profile.parse_wake_words("不是 JSON") is None


def test_generate_wake_words_uses_llm():
    called = {}

    def fake_llm(prompt):
        called["prompt"] = prompt
        return '["小菡", "菡菡"]'

    words = agent_profile.generate_wake_words("你叫李清菡，是大家的学姐", fake_llm)
    assert words == ["小菡", "菡菡"]
    assert "李清菡" in called["prompt"]


def test_generate_wake_words_falls_back_when_llm_garbage():
    def bad_llm(prompt):
        return "抱歉我无法回答"

    words = agent_profile.generate_wake_words("你叫李清菡，大家都叫我学姐", bad_llm)
    assert "李清菡" in words and "学姐" in words


def test_generate_wake_words_default_when_all_empty():
    def bad_llm(prompt):
        return ""

    assert agent_profile.generate_wake_words("没有名字", bad_llm, default=["星群"]) == ["星群"]


def test_settings_agent_fields_roundtrip():
    tmp = Path(tempfile.mkdtemp(prefix="qbm_agent_"))
    s = Settings(tmp)
    s.ensure_dirs()
    s.agent_profile_enabled = True
    s.agent_profile_id = "liqinghan"
    s.agent_wake_words = ["李清菡", "学姐"]
    s.agent_wake_auto = False
    s.vision_api_url = "https://api.siliconflow.cn/v1"
    s.vision_api_key = "sk-test"
    s.vision_model = "Qwen/Qwen3-Omni-30B-A3B-Instruct"
    s.save()
    s2 = Settings.load(tmp)
    assert s2.agent_profile_enabled is True
    assert s2.agent_profile_id == "liqinghan"
    assert s2.agent_wake_words == ["李清菡", "学姐"]
    assert s2.agent_wake_auto is False
    assert s2.vision_api_key == "sk-test"
    assert s2.vision_model.endswith("Omni-30B-A3B-Instruct")


if __name__ == "__main__":
    test_profile_liqinghan_defaults()
    print("OK profile_liqinghan_defaults")
    test_profile_unknown_returns_none()
    print("OK profile_unknown_returns_none")
    test_capability_qq_group_has_admin_and_voice()
    print("OK capability_qq_group")
    test_capability_wechat_private_disables_group_and_proactive()
    print("OK capability_wechat_private")
    test_capability_unknown_channel_empty()
    print("OK capability_unknown_channel")
    test_enabled_tools_wechat_drops_admin_tools()
    print("OK enabled_tools_wechat")
    test_wake_words_regex_extract_from_persona()
    print("OK wake_words_regex_extract")
    test_wake_words_regex_empty_persona()
    print("OK wake_words_regex_empty")
    test_parse_wake_words_fences_and_bad_items()
    print("OK parse_wake_words")
    test_parse_wake_words_not_json_returns_none()
    print("OK parse_wake_words_not_json")
    test_generate_wake_words_uses_llm()
    print("OK generate_wake_words_uses_llm")
    test_generate_wake_words_falls_back_when_llm_garbage()
    print("OK generate_wake_words_fallback")
    test_generate_wake_words_default_when_all_empty()
    print("OK generate_wake_words_default")
    test_settings_agent_fields_roundtrip()
    print("OK settings_agent_fields_roundtrip")
