"""记忆读取工具：只返回结构化结果，不写死回复话术（语言表述由 agent 负责）。"""
import json


def handle(ctx, args):
    store = getattr(ctx, "store", None)
    user = str(args.get("user") or "").strip()
    if store is None or not hasattr(store, "fetch_memory"):
        return json.dumps({"ok": False, "error": "store_unavailable"},
                          ensure_ascii=False)
    try:
        data = store.fetch_memory(user)
    except Exception as exc:  # noqa: BLE001
        return json.dumps({"ok": False, "error": "store_error",
                           "detail": str(exc)}, ensure_ascii=False)
    return json.dumps({"ok": True, "user": user, "memory": data},
                      ensure_ascii=False, default=str)
