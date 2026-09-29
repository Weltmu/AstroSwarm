"""AI 主持小游戏：状态机 + 判定（谜语 / 猜数字 / 石头剪刀布），金币奖励走 store"""
import json
import random
import re
import time


GAME_TTL = 1800  # 半小时没人玩自动结束


def start(store, group_id, kind, hint="", answer="", reward=10):
    state = {
        "kind": kind,
        "hint": hint,
        "answer": str(answer),
        "reward": max(1, min(int(reward), 50)),
        "hits": 0,
        "started": int(time.time()),
    }
    store.set_game(group_id, json.dumps(state, ensure_ascii=False))
    return state


def get(store, group_id):
    raw = store.get_game(group_id)
    if not raw:
        return None
    try:
        s = json.loads(raw)
    except Exception:  # noqa: BLE001
        return None
    if time.time() - s.get("started", 0) > GAME_TTL:
        store.clear_game(group_id)
        return None
    return s


def clear(store, group_id):
    store.clear_game(group_id)


def _judge_number(s, text):
    m = re.search(r"-?\d{1,3}", text)
    if not m:
        return None
    g = int(m.group())
    ans = int(s.get("answer") or 0)
    if g == ans:
        return ("win", g)
    return ("hint", "高了" if g > ans else "低了")


def _judge_riddle(s, text):
    ans = str(s.get("answer") or "").strip().lower()
    t = text.lower()
    if ans and (ans in t or t in ans):
        return ("win", ans)
    return ("miss", None)


def _judge_rps(text):
    for w, v in (("石头", "rock"), ("剪刀", "scissors"), ("布", "paper")):
        if w in text:
            return ("rps", v)
    return None


def judge(s, text):
    kind = s.get("kind")
    if kind == "number":
        return _judge_number(s, text)
    if kind == "riddle":
        return _judge_riddle(s, text)
    if kind == "rps":
        return _judge_rps(text)
    return None


def submit(store, group_id, qq, text):
    """处理一次作答。返回 (state, outcome, extra)；outcome=None 表示不是游戏输入"""
    s = get(store, group_id)
    if not s:
        return None, None, None
    res = judge(s, text)
    if res is None:
        return s, None, None
    if res[0] == "win":
        bal = store.add_coins(qq, s.get("reward", 10))
        store.clear_game(group_id)
        return s, "win", (res[1], bal)
    if res[0] == "hint":
        s["hits"] = s.get("hits", 0) + 1
        store.set_game(group_id, json.dumps(s, ensure_ascii=False))
        return s, "hint", (res[1], s["hits"])
    if res[0] == "miss":
        s["hits"] = s.get("hits", 0) + 1
        store.set_game(group_id, json.dumps(s, ensure_ascii=False))
        return s, "miss", (None, s["hits"])
    if res[0] == "rps":
        bot = random.choice(["rock", "scissors", "paper"])
        win = (res[1], bot) in (("rock", "scissors"), ("scissors", "paper"), ("paper", "rock"))
        draw = res[1] == bot
        if win:
            bal = store.add_coins(qq, s.get("reward", 10))
            store.clear_game(group_id)
            return s, "rps", (res[1], bot, "win", bal)
        return s, "rps", (res[1], bot, "draw" if draw else "lose", None)
    return s, None, None
