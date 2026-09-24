# -*- coding: utf-8 -*-
"""内置 AI 插件全局记忆（aichat_memory.json）读写。

以前桌面端只能管李清菡智能体档案的记忆库（agent.db），内置 AI 插件那份全局记忆
只有控制台能看能清；同一屏上「记忆条数」和「记忆时间线」来自两个不同的库，界面上看不出来。
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from qbotmanager.core import ai_config  # noqa: E402
from qbotmanager.core import ai_memory  # noqa: E402
from qbotmanager.core.settings import Settings  # noqa: E402


def _settings() -> Settings:
    tmp = Path(tempfile.mkdtemp(prefix="qbm_aimem_"))
    s = Settings(tmp)
    s.ensure_dirs()
    return s


def test_missing_file_is_empty_not_error():
    s = _settings()
    assert ai_memory.load(s) == {"global": [], "users": {}}
    assert ai_memory.summary(s)["total"] == 0
    assert ai_memory.summary(s)["file"] == str(ai_config.memory_file(s))


def test_directory_is_created_and_backup_is_used():
    """一般用户第一次改记忆时文件还不存在，不能因为「目录不存在」而失败。"""
    s = _settings()
    ai_memory._save(s, {"global": ["甲", "乙"], "users": {}})
    path = ai_config.memory_file(s)
    assert path.exists(), path
    assert json.loads(path.read_text(encoding="utf-8"))["global"] == ["甲", "乙"]
    assert ai_memory.load(s)["global"] == ["甲", "乙"]


def test_summary_counts_global_and_users():
    s = _settings()
    ai_memory._save(s, {
        "global": ["全局一", "全局二"],
        "users": {"10001": ["喜欢喝美式", {"text": "养了只猫"}], "10002": ["住杭州"]},
    })
    info = ai_memory.summary(s)
    assert info["total"] == 5 and info["global_count"] == 2
    assert [g["user"] for g in info["users"]] == ["10001", "10002"]
    # 记忆可能是字符串也可能是 dict，都要能压成一行文本
    assert ai_memory.item_text({"text": "养了只猫"}) == "养了只猫"
    assert ai_memory.item_text("住杭州") == "住杭州"


def test_broken_file_raises_instead_of_silently_empty():
    """文件坏了必须报错：静默当空 + 下一次保存 = 把用户的记忆全冲掉。"""
    s = _settings()
    path = ai_config.memory_file(s)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ 这不是 JSON", encoding="utf-8")
    try:
        ai_memory.load(s)
    except ValueError as exc:
        assert "解析失败" in str(exc)
    else:
        raise AssertionError("坏文件应当抛 ValueError")
    # 也绝不能因为一次误调用就把坏文件覆盖掉
    try:
        ai_memory.clear(s, "global")
    except ValueError:
        pass
    assert path.read_text(encoding="utf-8").startswith("{ 这不是 JSON")


def test_delete_and_clear_leave_backup():
    s = _settings()
    ai_memory._save(s, {"global": ["a", "b", "c"], "users": {"10001": ["x", "y"]}})

    res = ai_memory.delete(s, "global", index=1)
    assert res["removed"] == "b" and res["left"] == 2
    assert Path(res["backup"]).exists(), "删除前要留备份"
    assert ai_memory.load(s)["global"] == ["a", "c"]

    # 负数从末尾数
    res = ai_memory.delete(s, "user", user="10001", index=-1)
    assert res["removed"] == "y" and res["left"] == 1

    res = ai_memory.clear(s, "global")
    assert res["removed"] == 2
    assert ai_memory.load(s)["global"] == []
    assert ai_memory.load(s)["users"]["10001"] == ["x"], "清全局不能动用户记忆"

    res = ai_memory.clear(s, "all")
    assert res["removed"] == 1
    assert ai_memory.load(s) == {"global": [], "users": {}}


def test_delete_validates_arguments():
    s = _settings()
    ai_memory._save(s, {"global": ["a"], "users": {}})
    for bad in (
        {"scope": "", "index": 0},
        {"scope": "admin", "index": 0},
        {"scope": "user", "user": "", "index": 0},      # 不给用户
        {"scope": "global", "index": 5},                # 越界
        {"scope": "global", "index": "0"},              # 不是整数
    ):
        try:
            ai_memory.delete(s, bad.get("scope", ""), bad.get("user", ""), bad.get("index", 0))
        except ValueError:
            continue
        raise AssertionError(f"{bad} 应当被拒绝")
    # 空的库删也应当是明确报错，而不是静默成功
    ai_memory._save(s, {"global": [], "users": {}})
    try:
        ai_memory.delete(s, "global", index=0)
    except ValueError as exc:
        assert "空" in str(exc)
    else:
        raise AssertionError("空库删除应当报错")


def test_export_json_and_markdown():
    s = _settings()
    ai_memory._save(s, {"global": ["记得他怕辣"], "users": {"10001": ["住杭州"]}})
    name, body = ai_memory.export_text(s, "json")
    assert name.endswith(".json") and "记得他怕辣" in body
    name, body = ai_memory.export_text(s, "md")
    assert name.endswith(".md")
    assert "## 全局记忆（1 条）" in body and "## 用户 10001（1 条）" in body
