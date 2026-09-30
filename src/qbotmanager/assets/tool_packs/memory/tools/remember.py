"""记忆写入工具：只返回结构化结果，不写死回复话术（语言表述由 agent 负责）。"""
import json


def handle(ctx, args):
    store = getattr(ctx, "store", None)
    if store is None or not hasattr(store, "remember"):
        return json.dumps({"ok": False, "error": "store_unavailable"},
                          ensure_ascii=False)
    user = str(args.get("user") or "").strip()
    fact = str(args.get("fact") or "").strip()
    try:
        store.remember(user, fact)
    except Exception as exc:  # noqa: BLE001
        return json.dumps({"ok": False, "error": "store_error",
                           "detail": str(exc)}, ensure_ascii=False)
    return json.dumps({"ok": True, "stored": True, "user": user,
                       "fact": fact}, ensure_ascii=False)
