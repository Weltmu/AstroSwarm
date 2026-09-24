# -*- coding: utf-8 -*-
"""聊天归档测试：JSONL 写入、初始化/写盘容错、身份映射、读取工具过滤。"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
if not os.environ.get("QBM_POINTER_DIR"):
    os.environ["QBM_POINTER_DIR"] = str(Path(tempfile.mkdtemp(prefix="qbm_test_ptr_")))


def _load_module():
    path = ROOT / "src" / "qbotmanager" / "assets" / "plugins" / "liqinghan" / "chat_archive.py"
    spec = importlib.util.spec_from_file_location("qbm_chat_archive", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _wait(pred, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.05)
    return False


def test_archive_writes_records_and_identity():
    mod = _load_module()
    tmp = Path(tempfile.mkdtemp(prefix="qbm_arch_"))
    ar = mod.ChatArchive(SimpleNamespace(data_dir=str(tmp), tz="Asia/Shanghai"))
    ar.record(session="p:10001", role="user", user_id="10001",
              nickname="Lee Verdant", group_id="", text="你好")
    ar.record(session="p:10001", role="assistant", user_id="astrobot",
              group_id="", text="嗯。", reply_ms=500,
              tool_calls=[{"name": "set_reminder", "ok": True}])
    day = tmp / "chat_archive" / time.strftime("%Y-%m-%d")
    f = day / "p_10001.jsonl"
    assert _wait(lambda: f.exists()), "归档文件应生成"
    lines = f.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2, lines
    rec = json.loads(lines[1])
    assert rec["role"] == "assistant"
    assert rec["session"] == "p:10001"
    assert rec["kind"] == "private"
    assert rec["reply_ms"] == 500
    assert rec["tool_calls"][0]["name"] == "set_reminder"
    ident_file = tmp / "chat_archive" / "identity_map.json"
    assert _wait(lambda: ident_file.exists()), "身份映射应自动生成"
    ident = json.loads(ident_file.read_text(encoding="utf-8"))
    assert ident["10001"]["nickname"] == "Lee Verdant"
    print("OK archive writes_records_and_identity")


def test_archive_init_failure_does_not_raise():
    mod = _load_module()
    tmp = Path(tempfile.mkdtemp(prefix="qbm_arch_fail_"))
    orig = mod.os.makedirs
    mod.os.makedirs = lambda *a, **k: (_ for _ in ()).throw(OSError("disk full"))
    try:
        ar = mod.ChatArchive(SimpleNamespace(data_dir=str(tmp), tz="Asia/Shanghai"))
        ar.record(session="p:x", role="user", user_id="x", text="hi")  # 必须不抛
        ar.bind_identity("x", qq="123")  # 必须不抛
    finally:
        mod.os.makedirs = orig
    print("OK archive init_failure_isolated")


def test_archive_bind_identity():
    mod = _load_module()
    tmp = Path(tempfile.mkdtemp(prefix="qbm_arch_bind_"))
    ar = mod.ChatArchive(SimpleNamespace(data_dir=str(tmp), tz="Asia/Shanghai"))
    assert ar.bind_identity("OPENID123", qq="10001", name="小明") is True
    ent = ar.identities()["OPENID123"]
    assert ent["qq"] == "10001" and ent["name"] == "小明"
    print("OK archive bind_identity")


def test_reader_filters_and_flags_problems():
    root = Path(tempfile.mkdtemp(prefix="qbm_arch_read_")) / "chat_archive"
    day = root / "2026-08-22"
    day.mkdir(parents=True)
    base = 1787376600
    rows = [
        {"ts": base, "time": "2026-08-22 11:30:00", "session": "p:10001",
         "kind": "private", "role": "user", "user_id": "10001",
         "nickname": "Lee Verdant", "group_id": "", "text": "你好"},
        {"ts": base + 30, "time": "2026-08-22 11:30:30", "session": "p:10001",
         "kind": "private", "role": "assistant", "user_id": "astrobot",
         "nickname": "", "group_id": "", "text": "嗯。", "reply_ms": 500},
        {"ts": base + 600, "time": "2026-08-22 11:40:00", "session": "g:1",
         "kind": "group", "role": "user", "user_id": "10001",
         "nickname": "Lee Verdant", "group_id": "1", "text": "@astrobot 在吗"},
        {"ts": base + 601, "time": "2026-08-22 11:40:01", "session": "g:1",
         "kind": "group", "role": "assistant", "user_id": "astrobot",
         "nickname": "", "group_id": "1", "text": "在。", "reply_ms": 120000},
        "not-json-line\n",
    ]
    with open(day / "p_10001.jsonl", "w", encoding="utf-8") as f:
        for r in rows[:2]:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
        f.write("not-json-line\n")
    with open(day / "g_1.jsonl", "w", encoding="utf-8") as f:
        for r in rows[2:4]:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    out = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "read_chat.py"),
         "--root", str(root), "--qq", "10001"],
        capture_output=True, text=True, encoding="utf-8")
    assert out.returncode == 0, out.stderr
    assert "你好" in out.stdout and "嗯。" in out.stdout
    assert "在吗" in out.stdout
    assert "回复过慢 120 秒" in out.stdout, out.stdout
    assert "损坏" in out.stderr or "损坏" in out.stdout

    out_priv = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "read_chat.py"),
         "--root", str(root), "--private", "--session", "p:10001"],
        capture_output=True, text=True, encoding="utf-8")
    assert "在吗" not in out_priv.stdout
    print("OK archive reader_filter_and_problems")


def test_reader_sorts_by_ts_and_flags_missing_reply():
    """回归：读出来必须按 ts 全局排序；「没回」只算私聊与被点名的群消息。

    背景（2026-09-13 服务器修复）：归档按「日期目录 → 会话文件」分块存，不排序会让
    --tail N 拿到的不是最新的 N 条；旧版把所有「用户连发」都当异常，还会把机器人隔了
    几小时的主动开口记成回复延迟，刷出一堆假异常。
    """
    root = Path(tempfile.mkdtemp(prefix="qbm_arch_order_")) / "chat_archive"
    day = root / "2026-08-22"
    day.mkdir(parents=True)
    base = 1787376600
    priv = [
        {"ts": base + 300, "time": "2026-08-22 11:35:00", "session": "p:10001",
         "kind": "private", "role": "user", "user_id": "10001",
         "nickname": "Lee Verdant", "group_id": "", "text": "现在几点了"},
        {"ts": base + 900, "time": "2026-08-22 11:45:00", "session": "p:10001",
         "kind": "private", "role": "assistant", "user_id": "astrobot",
         "nickname": "", "group_id": "", "text": "老记录别报过慢", "reply_ms": 999999},
    ]
    group = [
        {"ts": base + 100, "time": "2026-08-22 11:31:40", "session": "g:1",
         "kind": "group", "role": "user", "user_id": "10002",
         "nickname": "路人", "group_id": "1", "text": "大家早"},
        {"ts": base + 200, "time": "2026-08-22 11:33:20", "session": "g:1",
         "kind": "group", "role": "user", "user_id": "10002",
         "nickname": "路人", "group_id": "1", "text": "@机器人 在吗"},
        {"ts": base + 800, "time": "2026-08-22 11:43:20", "session": "g:1",
         "kind": "group", "role": "user", "user_id": "10002",
         "nickname": "路人", "group_id": "1", "text": "@机器人 帮我看看"},
        {"ts": base + 805, "time": "2026-08-22 11:43:25", "session": "g:1",
         "kind": "group", "role": "assistant", "user_id": "astrobot",
         "nickname": "", "group_id": "1", "text": "好", "reply_ms": 5000},
    ]
    for name, records in (("p_10001.jsonl", priv), ("g_1.jsonl", group)):
        with open(day / name, "w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    def run(*args):
        out = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "read_chat.py"),
             "--root", str(root), *args],
            capture_output=True, text=True, encoding="utf-8")
        assert out.returncode == 0, out.stderr
        return out

    problems = run("--problems")
    assert problems.stdout.count("没有回复") == 2, problems.stdout
    assert "大家早" not in problems.stdout, problems.stdout
    assert "回复过慢" not in problems.stdout, problems.stdout

    tail = run("--tail", "1")
    assert "老记录别报过慢" in tail.stdout, tail.stdout
    assert "现在几点了" not in tail.stdout, tail.stdout

    other = run("--problems", "--bot-name", "Eva")
    assert other.stdout.count("没有回复") == 1, other.stdout
    print("OK archive reader_sorts_by_ts_and_flags_missing_reply")


if __name__ == "__main__":
    test_archive_writes_records_and_identity()
    test_archive_init_failure_does_not_raise()
    test_archive_bind_identity()
    test_reader_filters_and_flags_problems()
    test_reader_sorts_by_ts_and_flags_missing_reply()
