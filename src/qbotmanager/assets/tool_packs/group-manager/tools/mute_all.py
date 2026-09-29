"""全员禁言工具：只返回结构化结果，不写死回复话术（语言表述由 agent 负责）。"""
import json

MAX_MUTE_MINUTES = 43200  # 全员禁言到点自动解除的上限：30 天


def handle(ctx, args):
    if not ctx.can("group_admin"):
        return json.dumps({"ok": False, "error": "permission_denied",
                           "permission": "group_admin"}, ensure_ascii=False)
    group_id = str(args.get("group_id") or "").strip()
    if not group_id:
        return json.dumps({"ok": False, "error": "missing_group_id"},
                          ensure_ascii=False)
    try:
        minutes = max(1, min(int(args.get("minutes", 5)), MAX_MUTE_MINUTES))
    except (TypeError, ValueError):
        return json.dumps({"ok": False, "error": "invalid_minutes"},
                          ensure_ascii=False)
    ctx.send("mute_all", {
        "group_id": group_id,
        "minutes": minutes,
    })
    return json.dumps({"ok": True, "action": "mute_all",
                       "group_id": group_id, "minutes": minutes},
                      ensure_ascii=False)
