# -*- coding: utf-8 -*-
"""聊天全量归档：异步落盘 JSONL + 身份映射（只写不读，绝不干扰回复流程）。

设计约束（2026-08-22 定稿）：
- 独立于 memory.py 的 60 条上下文裁剪：归档全量，喂给 AI 的逻辑一行不动；
- 后台线程 + 有界队列：磁盘慢/满只丢日志，不阻塞也不崩溃；
- 写失败只记 warning/exception，所有入口 try/except 兜底；
- 目录：<data_dir>/chat_archive/<YYYY-MM-DD>/<session>.jsonl
- 身份映射：<data_dir>/chat_archive/identity_map.json（openid/QQ → 昵称/QQ/备注）
"""
import json
import logging
import os
import queue
import threading
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

logger = logging.getLogger("chat_archive")

_IDENTITY_FIELDS = ("qq", "name", "note")


def _safe_name(session: str) -> str:
    return "".join(
        ch if ch.isalnum() or ch in "._-" else "_"
        for ch in str(session or "unknown")
    ) or "unknown"


def _make_tz(name: str):
    """时区对象：优先系统 zoneinfo；缺失/不可用时回退固定 UTC+8（Asia/Shanghai）。"""
    try:
        return ZoneInfo(name)
    except Exception:  # noqa: BLE001 —— 无 tzdata 的 Windows 环境回退
        return timezone(timedelta(hours=8))


class ChatArchive:
    """聊天归档写入器（单实例，随 Agent 生命周期）。"""

    def __init__(self, cfg):
        self.tz = str(getattr(cfg, "tz", "") or "Asia/Shanghai")
        self._tz = _make_tz(self.tz)
        data_dir = str(getattr(cfg, "data_dir", "") or "")
        self.root = os.path.join(data_dir, "chat_archive")
        self.identity_file = os.path.join(self.root, "identity_map.json")
        self._identities = {}
        self._queue = None
        self._thread = None
        try:
            os.makedirs(self.root, exist_ok=True)
            self._load_identities()
            self._queue = queue.Queue(maxsize=2000)
            self._thread = threading.Thread(
                target=self._writer_loop, name="chat-archive", daemon=True)
            self._thread.start()
        except Exception:  # noqa: BLE001 —— 归档初始化失败绝不影响机器人
            logger.exception("聊天归档初始化失败（归档停用，机器人正常运行）")
            self._queue = None

    # ------------------------------------------------------------ 对外接口
    def record(self, **fields):
        """非阻塞写入一条记录；队列满时丢弃并告警，不阻塞调用方。"""
        if self._queue is None:
            return
        try:
            self._queue.put_nowait(fields)
        except queue.Full:
            logger.warning("聊天归档队列已满，丢弃 1 条记录（不影响机器人）")

    def bind_identity(self, user_id, **fields):
        """手动绑定身份：openid/QQ → qq / name / note（维护工具用）。"""
        user_id = str(user_id or "")
        if not user_id or self._queue is None:
            return False
        ent = dict(self._identities.get(user_id) or {})
        for k, v in fields.items():
            if k in _IDENTITY_FIELDS and v:
                ent[k] = str(v)
        ent["bound_at"] = int(time.time())
        self._identities[user_id] = ent
        self._save_identities()
        return True

    def identities(self) -> dict:
        return dict(self._identities)

    # ------------------------------------------------------------ 内部实现
    def _load_identities(self):
        try:
            with open(self.identity_file, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                self._identities = data
        except Exception:  # noqa: BLE001
            self._identities = {}

    def _save_identities(self):
        try:
            tmp = self.identity_file + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._identities, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.identity_file)
        except Exception:  # noqa: BLE001
            logger.exception("身份映射写盘失败")

    def _writer_loop(self):
        while True:
            item = self._queue.get()
            try:
                self._write_one(item)
            except Exception:  # noqa: BLE001
                logger.exception("聊天归档写入失败")
            finally:
                self._queue.task_done()

    def _write_one(self, item):
        now = time.time()
        ts = int(item.get("ts") or now)
        dt = datetime.fromtimestamp(ts, self._tz)
        session = str(item.get("session") or "unknown")
        path = os.path.join(
            self.root, dt.strftime("%Y-%m-%d"), _safe_name(session) + ".jsonl")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        rec = {
            "ts": ts,
            "time": dt.strftime("%Y-%m-%d %H:%M:%S"),
            "session": session,
            "kind": "private" if session.startswith("p:")
            else ("group" if session.startswith("g:") else "other"),
            "role": str(item.get("role") or ""),
            "user_id": str(item.get("user_id") or ""),
            "nickname": str(item.get("nickname") or ""),
            "group_id": str(item.get("group_id") or ""),
            "text": str(item.get("text") or ""),
        }
        for key in ("reply_ms", "tool_calls", "error", "segments"):
            if item.get(key) is not None:
                rec[key] = item[key]
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()
        self._learn_identity(rec, ts)

    def _learn_identity(self, rec: dict, ts: int):
        uid = rec.get("user_id") or ""
        if not uid or rec.get("role") != "user":
            return
        ent = self._identities.get(uid)
        if ent is None:
            self._identities[uid] = {
                "nickname": rec.get("nickname") or "",
                "first_seen": ts,
                "last_seen": ts,
            }
            self._save_identities()
        elif rec.get("nickname") and rec.get("nickname") != ent.get("nickname"):
            ent["nickname"] = rec.get("nickname")
            ent["last_seen"] = ts
            self._save_identities()
