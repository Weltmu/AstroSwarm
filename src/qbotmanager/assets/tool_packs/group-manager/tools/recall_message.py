"""撤回消息工具：只返回结构化结果，不写死回复话术（语言表述由 agent 负责）。"""
import json


def handle(ctx, args):
    message_id = str(args.get("message_id") or "").strip()
    group_id = str(args.get("group_id") or "").strip()
    if not message_id:
        return json.dumps({"ok": False, "error": "missing_message_id"},
                          ensure_ascii=False)
    ctx.send("recall_message", {
        "group_id": group_id,
        "message_id": message_id,
    })
    return json.dumps({"ok": True, "action": "recall_message",
                       "group_id": group_id, "message_id": message_id},
                      ensure_ascii=False)
