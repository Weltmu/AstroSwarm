"""主动聊天建议工具：返回结构化建议种子，具体怎么说由 agent 按人设组织。"""
import json
import random

_IDEAS = [
    {"type": "riddle", "seed": "出一个谜语让大家猜，猜对有彩头"},
    {"type": "sharing_chain", "seed": "发起「今天最开心的一件事」接龙"},
    {"type": "fun_fact", "seed": "分享一个冷知识并问问大家知不知道"},
    {"type": "number_game", "seed": "提议玩一把猜数字小游戏"},
    {"type": "weekend_plan", "seed": "问问大家周末安排，找共同话题"},
]


def handle(ctx, args):
    return json.dumps({"ok": True, "suggestion": random.choice(_IDEAS)},
                      ensure_ascii=False)
