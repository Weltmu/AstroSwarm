# -*- coding: utf-8 -*-
"""桌面端配置读写：原子写、留备份、坏文件抢救（对齐无头端 headless_config）。

以前 settings.json 解析失败只 warning 后返回默认值，紧接着一次 save() 就把默认值
写回文件 —— QQ 端口、OneBot token、AI Key、外观会无声消失且无留证。
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from qbotmanager.core.settings import Settings  # noqa: E402


def _new_root() -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="qbm_settings_"))
    s = Settings(tmp)
    s.ensure_dirs()
    return tmp


def test_save_writes_atomic_and_keeps_backup():
    root = _new_root()
    s = Settings(root)
    s.nonebot_port = 12113
    s.qq_onebot_token = "TOKEN-ABC"
    s.ai_api_key = "sk-test-key-123456"
    s.save()

    assert s.settings_file.exists()
    assert s._last_good_file().exists(), "第一次保存也要留一份 .bak 当回滚目标"
    data = json.loads(s.settings_file.read_text(encoding="utf-8"))
    assert data["nonebot_port"] == 12113 and data["qq_onebot_token"] == "TOKEN-ABC"
    # 不留临时文件
    leftovers = [p for p in root.glob("settings.json.*.tmp")]
    assert leftovers == [], leftovers


def test_corrupt_config_rescued_not_silently_defaulted():
    """截断的配置：能读的字段要救回来，且留下 .corrupt 证据与错误标记。"""
    root = _new_root()
    s = Settings(root)
    s.nonebot_port = 12113
    s.qq_onebot_token = "TOKEN-ABC"
    s.ai_api_key = "sk-test-key-123456"
    s.save()

    raw = s.settings_file.read_text(encoding="utf-8")
    # 砍掉后半段，制造「写到一半」的截断文件（前半段仍完好）
    s.settings_file.write_text(raw[: int(len(raw) * 0.6)], encoding="utf-8")

    s2 = Settings.load(root)
    assert s2.config_error, "坏配置必须留下错误标记，不能静默"
    assert s2.config_backup and Path(s2.config_backup).exists(), "坏文件要另存 .corrupt.*"
    assert s2.config_rescued, "应当抢救回若干字段"
    # 被截断之前写下的字段必须还在（旧行为会全部退成默认值）
    assert s2.nonebot_port == 12113, s2.nonebot_port

    # 抢救之后再保存，不会把默认值写回去盖掉端口
    s2.save()
    data = json.loads(s2.settings_file.read_text(encoding="utf-8"))
    assert data["nonebot_port"] == 12113


def test_corrupt_config_falls_back_to_last_good():
    """整份坏掉（无法抢救）时用 .bak 兜底，而不是退成默认值。"""
    root = _new_root()
    s = Settings(root)
    s.nonebot_port = 12113
    s.qq_onebot_token = "TOKEN-ABC"
    s.save()
    # 再存一次，让 .bak 里也是这份完整配置
    s.save()
    s.settings_file.write_text("{ 这不是 JSON", encoding="utf-8")

    s2 = Settings.load(root)
    assert s2.config_error
    assert s2.nonebot_port == 12113, "应当从 .bak 拿回端口"
    assert s2.qq_onebot_token == "TOKEN-ABC", "应当从 .bak 拿回 OneBot token"


def test_restore_last_good():
    root = _new_root()
    s = Settings(root)
    s.nonebot_port = 12113
    s.save()
    s.nonebot_port = 9999
    s.save()                       # 这一次覆盖前，.bak 里存的是 12113 那份
    assert Settings.load(root).nonebot_port == 9999

    s2 = Settings.load(root)
    res = s2.restore_last_good()
    assert res.get("ok") is True
    assert Settings.load(root).nonebot_port == 12113


def test_broken_then_load_is_not_flagged_when_healthy():
    root = _new_root()
    s = Settings(root)
    s.nonebot_port = 12113
    s.save()
    s2 = Settings.load(root)
    assert s2.config_error == "" and s2.config_rescued == ()
