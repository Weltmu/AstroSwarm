# -*- coding: utf-8 -*-
"""聊天归档读取器：按时间/会话/用户过滤 JSONL，输出对话 + 异常清单。

用法示例：
  python3 read_chat.py --root ~/agent/data/chat_archive \
      --qq 10001 --since "2026-08-22 11:30"
  python3 read_chat.py --root ~/agent/data/chat_archive --private --problems
  python3 read_chat.py --root ... --bind <机器码> --qq 10001 --name 某人
  python3 read_chat.py --root ... --group --bot-name Eva --since "2026-09-21"
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime


def _force_utf8_stdout():
    """让本脚本在 cp936（简体中文 Windows 控制台）下也输出 UTF-8。

    归档里有中文昵称/消息，Windows 控制台默认按 cp936 编码 stdout。调用方
    （tests/test_chat_archive.py、管道、CI）用 UTF-8 解码读取时会直接
    UnicodeDecodeError（是输出编码问题，不是产品缺陷）。
    errors="replace" 保证任何情况下都不因为一个字符把整条管道打断。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001 —— 老 Python / 被重定向成非 TextIOWrapper 时忽略
            pass


def _load_identity(root):
    p = os.path.join(root, "identity_map.json")
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _parse_time(s):
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return int(datetime.strptime(s, fmt).timestamp())
        except ValueError:
            continue
    raise ValueError(f"时间格式无法解析: {s}")


def _iter_records(root, since, until):
    skipped = 0
    for day in sorted(os.listdir(root)):
        day_dir = os.path.join(root, day)
        if not os.path.isdir(day_dir):
            continue
        for name in sorted(os.listdir(day_dir)):
            if not name.endswith(".jsonl"):
                continue
            path = os.path.join(day_dir, name)
            try:
                with open(path, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            rec = json.loads(line)
                        except ValueError:
                            skipped += 1
                            continue
                        ts = int(rec.get("ts") or 0)
                        if since and ts < since:
                            continue
                        if until and ts > until:
                            continue
                        yield rec
            except OSError:
                skipped += 1
    if skipped:
        print(f"[提示] {skipped} 行损坏/无法读取，已跳过", file=os.sys.stderr)


def _scope(rec, args):
    if args.private and not str(rec.get("session") or "").startswith("p:"):
        return False
    if args.group and not str(rec.get("session") or "").startswith("g:"):
        return False
    if args.session and str(rec.get("session") or "") != args.session:
        return False
    return True


def _identity_match(rec, args, identity):
    uid = str(rec.get("user_id") or "")
    ent = identity.get(uid, {})
    if args.qq:
        if uid != args.qq and str(ent.get("qq") or "") != args.qq:
            return False
    if args.name:
        name = str(ent.get("name") or ent.get("nickname") or "")
        if args.name not in name and args.name not in uid:
            return False
    return True


def _display_name(uid, nickname, identity):
    ent = identity.get(str(uid), {})
    if ent.get("name"):
        return str(ent["name"])
    if ent.get("qq"):
        return f"{nickname or uid}（QQ {ent['qq']}）"
    return nickname or uid


def _kind(session):
    s = str(session or "")
    if s.startswith("p:"):
        return "私聊"
    if s.startswith("g:"):
        return "群聊"
    return "其他"


# 群聊里“明确在找机器人”的判据：@ 它，或者正文里点名。
# 默认名字覆盖内置 AI 插件常见的自称；服务器上可用 --bot-name 追加自己的名字。
DEFAULT_BOT_NAMES = ("机器人", "bot", "Eva")


def _is_addressed(text, names=DEFAULT_BOT_NAMES):
    line = str(text or "").lower()
    for name in names:
        name = str(name or "").strip().lower()
        if name and name in line:
            return True
    return False


def main():
    _force_utf8_stdout()
    ap = argparse.ArgumentParser(description="读取聊天归档")
    ap.add_argument("--root", default="data/chat_archive", help="归档根目录")
    ap.add_argument("--since", help="起始时间，如 2026-08-22 11:30")
    ap.add_argument("--until", help="结束时间")
    ap.add_argument("--session", help="精确会话，如 p:10001")
    ap.add_argument("--qq", help="QQ 号（匹配 user_id 或身份绑定）")
    ap.add_argument("--name", help="昵称/名字子串")
    ap.add_argument("--private", action="store_true", help="只看私聊")
    ap.add_argument("--group", action="store_true", help="只看群聊")
    ap.add_argument(
        "--bot-name",
        action="append",
        default=None,
        help="机器人名字（可重复）：群聊里点名它却没回才算异常，默认 "
             + "/".join(DEFAULT_BOT_NAMES),
    )
    ap.add_argument("--tail", type=int, default=0, help="只看最后 N 条")
    ap.add_argument("--problems", action="store_true", help="只输出异常记录")
    ap.add_argument("--bind", metavar="USER_ID", help="绑定身份（配合 --qq/--name）")
    args = ap.parse_args()

    identity = _load_identity(args.root)
    if args.bind:
        ent = dict(identity.get(args.bind, {}))
        if args.qq:
            ent["qq"] = args.qq
        if args.name:
            ent["name"] = args.name
        ent["bound_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        identity[args.bind] = ent
        with open(os.path.join(args.root, "identity_map.json"), "w", encoding="utf-8") as f:
            json.dump(identity, f, ensure_ascii=False, indent=2)
        print(f"已绑定 {args.bind} -> {json.dumps(ent, ensure_ascii=False)}")
        return

    since = _parse_time(args.since)
    until = _parse_time(args.until)
    bot_names = tuple(args.bot_name) if args.bot_name else DEFAULT_BOT_NAMES
    raw = [r for r in _iter_records(args.root, since, until) if _scope(r, args)]
    # 归档按"日期目录→会话文件"分块存储，这里统一按 ts 排序：
    # 否则 --tail N 拿到的不是"最新 N 条"，人工阅读时顺序也会乱。
    raw.sort(key=lambda r: int(r.get("ts") or 0))
    if args.qq or args.name:
        matched_sessions = {
            str(r.get("session") or "")
            for r in raw
            if r.get("role") == "user" and _identity_match(r, args, identity)
        }
        rows = [
            r for r in raw
            if _identity_match(r, args, identity)
            or str(r.get("session") or "") in matched_sessions
        ]
    else:
        rows = raw
    if args.tail > 0:
        rows = rows[-args.tail:]

    # 群聊只有“明确找机器人但没人回”才算问题；普通聊天不要求每条都回。
    problems = []
    missing_reply_idx = set()
    for idx, rec in enumerate(rows):
        if rec.get("role") != "user":
            continue
        session = str(rec.get("session") or "")
        ts = int(rec.get("ts") or 0)
        # 只检查连续用户消息里的最后一条，避免同一段连发报 N 次
        if idx + 1 < len(rows):
            nxt = rows[idx + 1]
            if (
                str(nxt.get("session") or "") == session
                and nxt.get("role") == "user"
            ):
                continue
        replied = False
        for nxt in rows[idx + 1:]:
            if str(nxt.get("session") or "") != session:
                continue
            if nxt.get("role") == "assistant" and int(nxt.get("ts") or 0) - ts <= 300:
                replied = True
                break
            if nxt.get("role") == "user" and int(nxt.get("ts") or 0) - ts > 300:
                break
        if not replied:
            addressed = _is_addressed(rec.get("text", ""), bot_names)
            if session.startswith("p:") or addressed:
                missing_reply_idx.add(idx)
                problems.append(
                    f"{rec.get('time')} [{session}] 用户发言后 5 分钟内没有回复"
                )

    printed = 0
    for idx, rec in enumerate(rows):
        session = str(rec.get("session") or "")
        role = str(rec.get("role") or "")
        uid = str(rec.get("user_id") or "")
        nickname = str(rec.get("nickname") or "")
        text = str(rec.get("text") or "")
        name = _display_name(uid, nickname, identity)
        reply_ms = rec.get("reply_ms")
        # 历史数据里存在"主动开口被误记成回复延迟"的条目（已修，见 agent.py）；
        # 超过 5 分钟的一律视为无效，避免刷出假异常。
        if reply_ms is not None and int(reply_ms) > 300000:
            reply_ms = None
        tools = rec.get("tool_calls") or []
        error = rec.get("error")

        is_problem = False
        if role == "system" or error:
            is_problem = True
            problems.append(f"{rec.get('time')} [{session}] 事件处理失败: {error}")
        for t in tools:
            if not t.get("ok"):
                is_problem = True
                problems.append(
                    f"{rec.get('time')} [{session}] 工具失败 {t.get('name')}: {t.get('error')}")
        if role == "assistant" and reply_ms is not None and reply_ms > 60000:
            is_problem = True
            problems.append(
                f"{rec.get('time')} [{session}] 回复过慢 {reply_ms / 1000:.0f} 秒")
        if idx in missing_reply_idx:
            is_problem = True
        if args.problems and not is_problem:
            continue
        line = f"{rec.get('time')} [{_kind(session)}] {name}: {text}"
        if reply_ms is not None and role == "assistant":
            line += f"  [延迟 {reply_ms / 1000:.1f}s]"
        if tools:
            line += "  [工具: " + ", ".join(
                f"{t.get('name')}{'✗' if not t.get('ok') else '✓'}"
                for t in tools) + "]"
        print(line)
        printed += 1

    print(f"\n== 共 {printed} 条" + (f"，异常 {len(problems)} 处" if problems else "") + " ==")
    if problems:
        print("\n== 异常清单 ==")
        for p in problems:
            print("•", p)


if __name__ == "__main__":
    main()
