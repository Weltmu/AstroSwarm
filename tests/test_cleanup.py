# -*- coding: utf-8 -*-
"""缓存与废文件自动清理测试。"""
import sys
import tempfile
import os
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
if not os.environ.get("QBM_POINTER_DIR"):
    os.environ["QBM_POINTER_DIR"] = str(Path(tempfile.mkdtemp(prefix="qbm_test_ptr_")))

from qbotmanager.core import cleanup  # noqa: E402
from qbotmanager.core.settings import Settings  # noqa: E402


def test_trim_large_logs_keep_tail():
    tmp = Path(tempfile.mkdtemp(prefix="qbm_cl_log_"))
    s = Settings(tmp)
    s.ensure_dirs()
    (s.logs_dir / "manager.log").write_text("A" * 4000, encoding="utf-8")
    (s.logs_dir / "nonebot.log").write_text("B" * 3000, encoding="utf-8")
    cleanup.run(settings=s, max_log_bytes=1000, max_message_bytes=1000,
                max_activate_bytes=1000, max_session_days=0)
    assert (s.logs_dir / "manager.log").stat().st_size <= 1000
    assert (s.logs_dir / "nonebot.log").stat().st_size <= 1000
    assert (s.logs_dir / "manager.log").read_text(encoding="utf-8").endswith("AAA")
    print("OK cleanup trim_large_logs_keep_tail")


def test_remove_stale_tmp_and_part():
    tmp = Path(tempfile.mkdtemp(prefix="qbm_cl_tmp_"))
    s = Settings(tmp)
    s.ensure_dirs()
    d = s.downloads_dir
    d.mkdir(parents=True, exist_ok=True)
    (d / "plugin.zip.part").write_text("x", encoding="utf-8")
    cache = s.root / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    (cache / "bg.tmp.mp4").write_text("x", encoding="utf-8")
    (cache / "keep.bin").write_text("y", encoding="utf-8")
    cleanup.run(settings=s, max_log_bytes=1000, max_message_bytes=1000,
                max_activate_bytes=1000, max_session_days=0)
    assert not (d / "plugin.zip.part").exists()
    assert not (cache / "bg.tmp.mp4").exists()
    assert (cache / "keep.bin").exists()
    print("OK cleanup remove_stale_tmp_and_part")


def test_trim_messages_jsonl():
    tmp = Path(tempfile.mkdtemp(prefix="qbm_cl_msg_"))
    s = Settings(tmp)
    s.ensure_dirs()
    p = s.bot_dir / "data" / "nonebot_adapter_ilink" / "messages.jsonl"
    p.parent.mkdir(parents=True)
    p.write_text("m\n" * 2000, encoding="utf-8")
    cleanup.run(settings=s, max_log_bytes=1000, max_message_bytes=500,
                max_activate_bytes=1000, max_session_days=0)
    assert p.stat().st_size <= 500
    print("OK cleanup trim_messages_jsonl")


def test_trim_activate_log():
    tmp = Path(tempfile.mkdtemp(prefix="qbm_cl_act_"))
    s = Settings(tmp)
    s.ensure_dirs()
    appdata = tmp / "appdata"
    appdata.mkdir()
    p = appdata / "activate.log"
    p.write_text("Z" * 3000, encoding="utf-8")
    cleanup.run(settings=s, max_log_bytes=1000, max_message_bytes=1000,
                max_activate_bytes=1000, max_session_days=0, appdata_dir=appdata)
    assert p.stat().st_size <= 1000
    print("OK cleanup trim_activate_log")


def test_remove_old_dsh_sessions():
    tmp = Path(tempfile.mkdtemp(prefix="qbm_cl_sess_"))
    s = Settings(tmp)
    s.ensure_dirs()
    sess = s.root / "dsh" / "home" / "sessions" / "ws" / "sid"
    sess.mkdir(parents=True)
    f = sess / "session.jsonl.zstd"
    f.write_text("x", encoding="utf-8")
    import os
    import time
    old = time.time() - 100 * 86400
    os.utime(f, (old, old))
    cleanup.run(settings=s, max_log_bytes=1000, max_message_bytes=1000,
                max_activate_bytes=1000, max_session_days=30)
    assert not sess.exists(), "超过保留期的 dsh 会话应被清理"
    print("OK cleanup remove_old_dsh_sessions")


def test_remove_stale_plugin_zips_keep_fresh():
    tmp = Path(tempfile.mkdtemp(prefix="qbm_cl_zip_"))
    s = Settings(tmp)
    s.ensure_dirs()
    zdir = s.downloads_dir / "plugins"
    zdir.mkdir(parents=True, exist_ok=True)
    old = zdir / "old-pack-1.0.0.zip"
    fresh = zdir / "fresh-pack-1.0.0.zip"
    old.write_text("x", encoding="utf-8")
    fresh.write_text("y", encoding="utf-8")
    import os
    import time
    old_ts = time.time() - 48 * 3600
    os.utime(old, (old_ts, old_ts))
    cleanup.run(settings=s, max_log_bytes=1000, max_message_bytes=1000,
                max_activate_bytes=1000, max_session_days=0, max_zip_hours=24)
    assert not old.exists(), "超过保留期的插件 zip 应被清理"
    assert fresh.exists(), "刚下载的插件 zip 不应被清理"
    print("OK cleanup remove_stale_plugin_zips_keep_fresh")


def test_remove_stale_runtime_zips():
    """部署用的运行时压缩包（Python 嵌入版 / Node 便携版）解压后应被清掉。"""
    tmp = Path(tempfile.mkdtemp(prefix="qbm_cl_rtzip_"))
    s = Settings(tmp)
    s.ensure_dirs()
    d = s.downloads_dir
    d.mkdir(parents=True, exist_ok=True)
    py_zip = d / "python-3.11.9-embed-amd64.zip"
    node_zip = d / "node-v22.11.0-win-x64.zip"
    fresh = d / "python-3.12.0-embed-amd64.zip"
    for p in (py_zip, node_zip, fresh):
        p.write_text("x", encoding="utf-8")
    old_ts = time.time() - 48 * 3600
    for p in (py_zip, node_zip):
        os.utime(p, (old_ts, old_ts))
    stats = cleanup.run(settings=s, max_log_bytes=1000, max_message_bytes=1000,
                        max_activate_bytes=1000, max_session_days=0,
                        max_zip_hours=24)
    assert not py_zip.exists(), "过期的 Python 运行时包应被清理"
    assert not node_zip.exists(), "过期的 Node 运行时包应被清理"
    assert fresh.exists(), "刚下载的运行时包不应被清理"
    assert stats["zip_removed"] == 2, stats
    print("OK cleanup remove_stale_runtime_zips")


def test_remove_stale_mei_dirs():
    """%TEMP%\\_MEI*（强杀残留，单个约 450 MB）与 is-*.tmp 只清过期的。"""
    tmp = Path(tempfile.mkdtemp(prefix="qbm_cl_mei_"))
    s = Settings(tmp)
    s.ensure_dirs()
    temp_root = Path(tempfile.mkdtemp(prefix="qbm_cl_tmproot_"))
    old = temp_root / "_MEI111111"          # 我们自己的旧残留（带指纹）
    new = temp_root / "_MEI222222"          # 本次运行新解压出来的
    foreign = temp_root / "_MEI333333"      # 别家 PyInstaller 软件的残留
    inst = temp_root / "is-3C4D.tmp"
    for d in (old, new, foreign, inst):
        (d / "sub").mkdir(parents=True)
        (d / "sub" / "payload.bin").write_text("x", encoding="utf-8")
    (old / "appr").mkdir()
    (new / "appr").mkdir()
    (foreign / "other_vendor_app").mkdir()
    old_ts = time.time() - 10 * 3600
    for d in (old, foreign, inst):
        for p in [d] + list(d.rglob("*")):
            os.utime(p, (old_ts, old_ts))
    # keep 指向本进程正在使用的 _MEIPASS：即使过期也不能删
    assert cleanup.remove_stale_temp_dirs(
        temp_root, 6, keep=old, patterns=("_MEI*",),
        markers=("appr", "qbotmanager")) == 0
    assert old.exists(), "keep 指定的目录不能删"
    stats = cleanup.run(settings=s, max_log_bytes=1000, max_message_bytes=1000,
                        max_activate_bytes=1000, max_session_days=0,
                        temp_dir=temp_root, max_mei_hours=6)
    assert not old.exists(), "过期的 _MEI 目录应被清理"
    assert new.exists(), "本次运行新产生的 _MEI 目录不应被清理"
    assert foreign.exists(), "不带指纹（别家软件）的 _MEI 目录不能删"
    assert not inst.exists(), "中断安装残留 is-*.tmp 应被清理"
    assert stats["mei_removed"] == 1, stats
    assert stats["installer_tmp_removed"] == 1, stats
    print("OK cleanup remove_stale_mei_dirs")


def test_remove_stale_temp_logs_keep_fresh():
    """%TEMP% 下的兜底日志只清过期的，正在写的保留。"""
    tmp = Path(tempfile.mkdtemp(prefix="qbm_cl_tlog_"))
    s = Settings(tmp)
    s.ensure_dirs()
    temp_root = Path(tempfile.mkdtemp(prefix="qbm_cl_tlogroot_"))
    old = temp_root / "qbotmanager_proc.log"
    fresh = temp_root / "astroswarm_cli.log"
    old.write_text("x", encoding="utf-8")
    fresh.write_text("y", encoding="utf-8")
    old_ts = time.time() - 30 * 3600
    os.utime(old, (old_ts, old_ts))
    stats = cleanup.run(settings=s, max_log_bytes=1000, max_message_bytes=1000,
                        max_activate_bytes=1000, max_session_days=0,
                        temp_dir=temp_root, max_temp_log_hours=24)
    assert not old.exists(), "过期兜底日志应被清理"
    assert fresh.exists(), "刚写的兜底日志不应被清理"
    assert stats["temp_logs_removed"] == 1, stats
    # 有内容才写一行摘要（logs/cleanup.log），供客户机排查
    cl = s.logs_dir / "cleanup.log"
    assert cl.is_file(), "有清理动作时应写 logs/cleanup.log"
    text = cl.read_text(encoding="utf-8")
    assert "cleanup" in text and "temp_logs_removed" in text, text
    assert text.count("\n") == 1, text
    print("OK cleanup remove_stale_temp_logs_keep_fresh")


def test_prune_pointer_backups():
    """指针目录 *.bak_* 每次升级留一份，只保留最新 3 份。"""
    d = Path(tempfile.mkdtemp(prefix="qbm_cl_bak_"))
    for i in range(5):
        p = d / ("settings.json.bak_%d" % i)
        p.write_text("x", encoding="utf-8")
        ts = time.time() - (10 - i) * 60
        os.utime(p, (ts, ts))
    removed = cleanup.prune_pointer_backups(d, keep=3)
    assert removed == 2, removed
    left = sorted(p.name for p in d.glob("*.bak_*"))
    assert left == ["settings.json.bak_2", "settings.json.bak_3",
                    "settings.json.bak_4"], left
    assert cleanup.prune_pointer_backups(d, keep=0) == 3
    assert list(d.glob("*.bak_*")) == []
    tmp = Path(tempfile.mkdtemp(prefix="qbm_cl_bak2_"))
    s = Settings(tmp)
    s.ensure_dirs()
    assert "bak_removed" in cleanup.run(settings=s, max_log_bytes=1000,
                                       max_message_bytes=1000,
                                       max_activate_bytes=1000,
                                       max_session_days=0)
    print("OK cleanup prune_pointer_backups")


if __name__ == "__main__":
    test_trim_large_logs_keep_tail()
    test_remove_stale_tmp_and_part()
    test_trim_messages_jsonl()
    test_trim_activate_log()
    test_remove_old_dsh_sessions()
    test_remove_stale_plugin_zips_keep_fresh()
    test_remove_stale_runtime_zips()
    test_remove_stale_mei_dirs()
    test_remove_stale_temp_logs_keep_fresh()
    test_prune_pointer_backups()
