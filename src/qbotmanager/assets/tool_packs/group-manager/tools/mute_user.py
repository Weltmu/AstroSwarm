"""禁言工具：只返回结构化结果，不写死回复话术（语言表述由 agent 负责）。"""
import json

MAX_MUTE_MINUTES = 43200  # QQ 平台个人禁言上限：30 天


def handle(ctx, args):
    if not ctx.can("group_admin"):
        return json.dumps({"ok": False, "error": "permission_denied",
                           "permission": "group_admin"}, ensure_ascii=False)
    user_id = str(args.get("user_id") or "").strip()
    group_id = str(args.get("group_id") or "").strip()
    if not user_id or not group_id:
        return json.dumps({"ok": False, "error": "missing_target",
                           "user_id": user_id, "group_id": group_id},
                          ensure_ascii=False)
    try:
        minutes = max(1, min(int(args.get("minutes", 1)), MAX_MUTE_MINUTES))
    except (TypeError, ValueError):
        return json.dumps({"ok": False, "error": "invalid_minutes"},
                          ensure_ascii=False)
    ctx.send("mute_user", {
        "group_id": group_id,
        "user_id": user_id,
        "minutes": minutes,
    })
    return json.dumps({"ok": True, "action": "mute_user",
                       "group_id": group_id, "user_id": user_id,
                       "minutes": minutes}, ensure_ascii=False)
