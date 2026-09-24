"""设定定时提醒：只返回结构化结果，不写死回复话术（语言表述由 agent 负责）。"""
import json
import time


def handle(ctx, args):
    try:
        minutes = max(1, int(args.get("minutes", 1)))
    except (TypeError, ValueError):
        return json.dumps({"ok": False, "error": "invalid_minutes"},
                          ensure_ascii=False)
    text = str(args.get("text") or "").strip()
    target = str(args.get("target") or "").strip()
    store = getattr(ctx, "store", None)
    if store is None or not hasattr(store, "add_reminder"):
        return json.dumps({"ok": False, "error": "store_unavailable"},
                          ensure_ascii=False)
    try:
        rid = store.add_reminder(minutes, text, target)
    except Exception as exc:  # noqa: BLE001
        return json.dumps({"ok": False, "error": "store_error",
                           "detail": str(exc)}, ensure_ascii=False)
    remind_at = time.strftime(
        "%Y-%m-%d %H:%M:%S",
        time.localtime(time.time() + minutes * 60))
    return json.dumps({
        "ok": True,
        "reminder_id": str(rid or ""),
        "minutes": minutes,
        "text": text,
        "target": target,
        "remind_at": remind_at,
    }, ensure_ascii=False)
