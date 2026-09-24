"""法棍经济模块（魔改新增，beta）

- 每个群独立数据
- 货币：法棍；可吃法棍提升属性（力量/敏捷/智力/耐力）
- 玩法：签到 / 打工 / 打劫 / 插 / 吃法棍 / 吃湿润法棍 / 属性 / 法棍
- 所有指令回复都会拼接 AI 生成的俏皮话（AI 不可用时只发结果）
"""
import json
import random
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

import nonebot_plugin_localstore as store
from nonebot import on_command, logger, get_bot
from nonebot.adapters.onebot.v11 import MessageEvent, MessageSegment

from .chat import get_short_ai_text

__all__ = []

DATA_FILE = store.get_plugin_data_file("economy.json")

ATTRIBUTES = ["strength", "agility", "intelligence", "endurance"]
ATTR_NAMES = {
    "strength": "力量",
    "agility": "敏捷",
    "intelligence": "智力",
    "endurance": "耐力",
}

# 冷却（秒）
COOLDOWNS = {
    "work": 1800,
    "rob": 300,
    "insert": 300,
    "eat": 5,
}

WORK_RANGE = (3, 10)
SIGNIN_RANGE = (5, 20)
ROB_STEAL_RANGE = (1, 5)
ROB_SUCCESS_RATE = 0.5
INSERT_SUCCESS_RATE = 0.5
WET_DROP_RATE = 0.05
COUNTER_ROB_RATE = 0.3
WORK_ATTR_RATE = 0.10
SIGNIN_EVENT_RATE = 0.03
WET_BONUS_POINTS = 3


def _load() -> Dict:
    if DATA_FILE.exists():
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except Exception as e:
            logger.error(f"加载经济数据失败: {e}")
    return {"groups": {}}


def _save(data: Dict) -> None:
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


_data: Dict = _load()


def _group_data(gid: str) -> Dict:
    return _data["groups"].setdefault(gid, {})


def _user_data(gid: str, uid: str) -> Dict:
    return _group_data(gid).setdefault(
        uid,
        {
            "baguettes": 0,
            "strength": 0,
            "agility": 0,
            "intelligence": 0,
            "endurance": 0,
            "wet_baguettes": 0,
            "last_signin": "",
            "cooldowns": {},
        },
    )


def _random_attr() -> str:
    return random.choice(ATTRIBUTES)


def _set_cooldown(user: Dict, key: str) -> None:
    user.setdefault("cooldowns", {})[key] = time.time()


def _cooldown_left(user: Dict, key: str) -> int:
    last = user.get("cooldowns", {}).get(key, 0)
    remain = last + COOLDOWNS[key] - time.time()
    return int(remain) if remain > 0 else 0


def _get_group(event: MessageEvent) -> Optional[str]:
    gid = getattr(event, "group_id", None)
    return str(gid) if gid else None


def _get_target(event: MessageEvent) -> Optional[str]:
    for seg in event.message:
        if seg.type == "at":
            qq = seg.data.get("qq")
            if qq and qq != "all":
                return str(qq)
    return None


def _attr_desc(user: Dict) -> str:
    s = user.get("strength", 0)
    a = user.get("agility", 0)
    i = user.get("intelligence", 0)
    e = user.get("endurance", 0)
    b = user.get("baguettes", 0)
    w = user.get("wet_baguettes", 0)
    return f"法棍: {b} 根 | 湿润の法棍: {w} 根" + chr(10) + f"力量: {s} | 敏捷: {a} | 智力: {i} | 耐力: {e}"


async def _flavor(result_text: str) -> str:
    prompt = (
        f"群里刚发生了一件事：{result_text}。"
        "请用一句符合你人设、俏皮自然的话接话，不超过25个字，不要重复结果本身，"
        "不要用markdown，不要JSON，直接输出这句话。"
    )
    return await get_short_ai_text(prompt, max_tokens=120)


async def _reply(cmd, result_text: str):
    await cmd.finish(await _flavored_text(result_text))


async def _flavored_text(result_text: str) -> str:
    flavor = await _flavor(result_text)
    if flavor:
        return f"{result_text}，{flavor}"
    return result_text


# ============ 签到 ============
signin_cmd = on_command("签到", priority=5, block=True)


@signin_cmd.handle()
async def handle_signin(event: MessageEvent):
    gid = _get_group(event)
    if not gid:
        await signin_cmd.finish("经济玩法只在群聊中可用哦~")
    uid = str(event.user_id)
    user = _user_data(gid, uid)
    today = datetime.now().strftime("%Y-%m-%d")
    if user.get("last_signin") == today:
        await signin_cmd.finish("今天已经签过到啦，明天再来吧~")
    reward = random.randint(*SIGNIN_RANGE)
    user["baguettes"] += reward
    user["last_signin"] = today
    extra = ""
    if random.random() < SIGNIN_EVENT_RATE:
        attr = _random_attr()
        user[attr] += 1
        extra = f" 触发意外事件，{ATTR_NAMES[attr]}+1！"
    _save(_data)
    await _reply(signin_cmd, f"签到成功，获得法棍 {reward} 个{extra}")


# ============ 打工 ============
work_cmd = on_command("打工", priority=5, block=True)


@work_cmd.handle()
async def handle_work(event: MessageEvent):
    gid = _get_group(event)
    if not gid:
        await work_cmd.finish("经济玩法只在群聊中可用哦~")
    uid = str(event.user_id)
    user = _user_data(gid, uid)
    left = _cooldown_left(user, "work")
    if left:
        await work_cmd.finish(f"打工还没到冷却时间，还要等 {left} 秒~")
    reward = random.randint(*WORK_RANGE)
    user["baguettes"] += reward
    _set_cooldown(user, "work")
    extra = ""
    if random.random() < WORK_ATTR_RATE:
        attr = _random_attr()
        user[attr] += 1
        extra = f" 好运爆发，{ATTR_NAMES[attr]}+1！"
    _save(_data)
    await _reply(work_cmd, f"打工完成，获得法棍 {reward} 个{extra}")


# ============ 吃法棍 ============
eat_cmd = on_command("吃法棍", aliases={"吃个法棍"}, priority=5, block=True)


@eat_cmd.handle()
async def handle_eat(event: MessageEvent):
    gid = _get_group(event)
    if not gid:
        await eat_cmd.finish("经济玩法只在群聊中可用哦~")
    uid = str(event.user_id)
    user = _user_data(gid, uid)
    left = _cooldown_left(user, "eat")
    if left:
        await eat_cmd.finish(f"刚吃过啦，等 {left} 秒再吃~")
    if user.get("baguettes", 0) < 1:
        await eat_cmd.finish("你还没有法棍，先去打工或签到吧~")
    user["baguettes"] -= 1
    attr = _random_attr()
    user[attr] += 1
    _set_cooldown(user, "eat")
    _save(_data)
    await _reply(eat_cmd, f"你吃掉了一根法棍，{ATTR_NAMES[attr]}+1！")


# ============ 吃湿润法棍 ============
eat_wet_cmd = on_command("吃湿润法棍", aliases={"吃湿润的法棍"}, priority=5, block=True)


@eat_wet_cmd.handle()
async def handle_eat_wet(event: MessageEvent):
    gid = _get_group(event)
    if not gid:
        await eat_wet_cmd.finish("经济玩法只在群聊中可用哦~")
    uid = str(event.user_id)
    user = _user_data(gid, uid)
    if user.get("wet_baguettes", 0) < 1:
        await eat_wet_cmd.finish("你没有湿润の法棍哦~")
    user["wet_baguettes"] -= 1
    gains = []
    for _ in range(WET_BONUS_POINTS):
        attr = _random_attr()
        user[attr] += 1
        gains.append(ATTR_NAMES[attr])
    counter = {}
    for name in gains:
        counter[name] = counter.get(name, 0) + 1
    summary = "，".join([f"{name}+{cnt}" for name, cnt in counter.items()])
    _save(_data)
    await _reply(eat_wet_cmd, f"你吃掉了湿润の法棍，属性大幅提升！（{summary}）")


# ============ 打劫 ============
rob_cmd = on_command("打劫", priority=5, block=True)


@rob_cmd.handle()
async def handle_rob(event: MessageEvent):
    gid = _get_group(event)
    if not gid:
        await rob_cmd.finish("经济玩法只在群聊中可用哦~")
    uid = str(event.user_id)
    target_uid = _get_target(event)
    if not target_uid:
        await rob_cmd.finish("要打劫谁？@一下目标~")
    if target_uid == uid:
        await rob_cmd.finish("不能打劫自己哦~")
    user = _user_data(gid, uid)
    left = _cooldown_left(user, "rob")
    if left:
        await rob_cmd.finish(f"打劫还在冷却，等 {left} 秒~")
    target = _user_data(gid, target_uid)
    _set_cooldown(user, "rob")
    if random.random() < ROB_SUCCESS_RATE:
        steal = random.randint(*ROB_STEAL_RANGE)
        if target.get("baguettes", 0) <= 0:
            user["baguettes"] = max(0, user.get("baguettes", 0) - 1)
            _save(_data)
            await _reply(rob_cmd, "对方比你还穷，打劫失败，还搭进去 1 根法棍……")
            return
        target["baguettes"] -= steal
        user["baguettes"] += steal
        attr = _random_attr()
        user[attr] += 1
        _save(_data)
        await _reply(rob_cmd, f"打劫成功！抢走 {steal} 根法棍，{ATTR_NAMES[attr]}+1！")
    else:
        user["baguettes"] = max(0, user.get("baguettes", 0) - 1)
        _save(_data)
        await _reply(rob_cmd, "打劫失败，被对方反抢，丢了 1 根法棍……")


# ============ 插 ============
insert_cmd = on_command("插", priority=5, block=True)


@insert_cmd.handle()
async def handle_insert(event: MessageEvent):
    gid = _get_group(event)
    if not gid:
        await insert_cmd.finish("经济玩法只在群聊中可用哦~")
    uid = str(event.user_id)
    target_uid = _get_target(event)
    if not target_uid:
        await insert_cmd.finish("要插谁？@一下目标~")
    if target_uid == uid:
        await insert_cmd.finish("不能插自己哦~")
    user = _user_data(gid, uid)
    left = _cooldown_left(user, "insert")
    if left:
        await insert_cmd.finish(f"插还在冷却，等 {left} 秒~")
    if user.get("baguettes", 0) < 1:
        await insert_cmd.finish("插人也要法棍啊，先去打工吧~")
    target = _user_data(gid, target_uid)
    user["baguettes"] -= 1
    _set_cooldown(user, "insert")
    if random.random() < INSERT_SUCCESS_RATE:
        attr = _random_attr()
        user[attr] += 1
        tattr = _random_attr()
        target[tattr] = max(0, target.get(tattr, 0) - 1)
        wet = ""
        if random.random() < WET_DROP_RATE:
            user["wet_baguettes"] += 1
            wet = " 居然掉落了一根湿润の法棍！"
        _save(_data)
        await _reply(insert_cmd, f"你成功插了对方一下，{ATTR_NAMES[attr]}+1，对方{ATTR_NAMES[tattr]}-1{wet}！")
    else:
        result = "插失败了，法棍掰折了，-1 根法棍……"
        if random.random() < COUNTER_ROB_RATE:
            lost = random.randint(1, 3)
            user["baguettes"] = max(0, user.get("baguettes", 0) - lost)
            target["baguettes"] += lost
            result += f" 还被对方反制夺走了 {lost} 根法棍！"
        _save(_data)
        await _reply(insert_cmd, result)


# ============ 属性 / 法棍 ============
stats_cmd = on_command("属性", aliases={"我的属性", "查看属性"}, priority=5, block=True)


@stats_cmd.handle()
async def handle_stats(event: MessageEvent):
    gid = _get_group(event)
    if not gid:
        await stats_cmd.finish("经济玩法只在群聊中可用哦~")
    user = _user_data(gid, str(event.user_id))
    text = await _flavored_text(_attr_desc(user))
    channel = await _try_temp_send(event, gid, text)
    if channel == "temp":
        await stats_cmd.finish("已通过临时会话发送属性给你~")
    elif channel == "failed":
        await stats_cmd.finish("发送失败，请检查你的隐私设置（允许临时会话）~")


baguette_cmd = on_command("法棍", aliases={"我的法棍"}, priority=5, block=True)


@baguette_cmd.handle()
async def handle_baguette(event: MessageEvent):
    gid = _get_group(event)
    if not gid:
        await baguette_cmd.finish("经济玩法只在群聊中可用哦~")
    user = _user_data(gid, str(event.user_id))
    b = user.get("baguettes", 0)
    w = user.get("wet_baguettes", 0)
    text = await _flavored_text(f"你有法棍 {b} 根，湿润の法棍 {w} 根")
    channel = await _try_temp_send(event, gid, text)
    if channel == "temp":
        await baguette_cmd.finish("已通过临时会话发送法棍信息给你~")
    elif channel == "failed":
        await baguette_cmd.finish("发送失败，请检查你的隐私设置（允许临时会话）~")


# ============ 临时会话发送 / 排行榜（魔改新增） ============

async def _try_temp_send(event: MessageEvent, gid: str, text: str) -> str:
    """优先通过群临时会话发送个人数据，失败则回退群聊。

    返回 "temp" / "group" / "failed"
    """
    try:
        bot = get_bot()
        await bot.send_private_msg(user_id=event.user_id, message=text)
        return "temp"
    except Exception as e:
        logger.warning(f"临时会话发送失败，回退群聊: {e}")
    try:
        bot = get_bot()
        await bot.send_group_msg(group_id=int(gid), message=text)
        return "group"
    except Exception as e:
        logger.error(f"回退群聊发送失败: {e}")
        return "failed"


async def _nickname(gid: str, uid: str) -> str:
    """获取群内昵称（优先群名片），失败返回 QQ 号"""
    try:
        info = await get_bot().get_group_member_info(group_id=int(gid), user_id=int(uid))
        name = (info.get("card") or "").strip() or (info.get("nickname") or "").strip()
        if name:
            return name
    except Exception as e:
        logger.warning(f"获取群昵称失败 {uid}: {e}")
    return uid


def _render_board(title: str, rows: list) -> Optional[Path]:
    """把排行榜渲染成 PNG 图片，返回图片路径（失败返回 None）"""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception as e:
        logger.error(f"Pillow 不可用: {e}")
        return None
    try:
        font_title = ImageFont.truetype(r"C:\Windows\Fonts\msyhbd.ttc", 34)
        font_row = ImageFont.truetype(r"C:\Windows\Fonts\msyh.ttc", 25)
        font_foot = ImageFont.truetype(r"C:\Windows\Fonts\msyh.ttc", 17)
    except Exception:
        font_title = font_row = font_foot = None

    width = 720
    head_h = 110
    row_h = 56
    foot_h = 48
    n = max(len(rows), 1)
    height = head_h + row_h * n + foot_h
    img = Image.new("RGB", (width, height), (22, 30, 60))
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, width, head_h], fill=(40, 54, 108))
    if font_title:
        draw.text((36, 18), title, font=font_title, fill=(255, 222, 120))
        draw.text((36, 66), f"共 {len(rows)} 人上榜", font=font_foot, fill=(175, 198, 235))
    else:
        draw.text((36, 30), title, fill=(255, 255, 255))

    for i, (rank, name, value) in enumerate(rows):
        y = head_h + i * row_h
        fill = (38, 48, 92) if i % 2 == 0 else (29, 39, 76)
        draw.rectangle([16, y + 6, width - 16, y + row_h - 2], fill=fill)
        if rank == 1:
            rank_color = (255, 215, 0)
        elif rank == 2:
            rank_color = (200, 200, 200)
        elif rank == 3:
            rank_color = (210, 135, 60)
        else:
            rank_color = (255, 255, 255)
        draw.text((34, y + 11), f"{rank}", font=font_row, fill=rank_color)
        draw.text((92, y + 11), str(name)[:12], font=font_row, fill=(235, 240, 255))
        draw.text((width - 40, y + 11), str(value), font=font_row, fill=(110, 230, 175), anchor="ra")

    draw.text((36, height - foot_h + 12), "AstroSwarm 法棍经济系统", font=font_foot, fill=(115, 135, 175))
    out = store.get_plugin_data_dir() / f"board_{int(time.time() * 1000)}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "PNG")
    return out


async def _send_board(cmd, event: MessageEvent, gid: str, title: str, rows: list) -> None:
    """发送排行榜图片到群聊"""
    img_path = _render_board(title, rows)
    if not img_path:
        await cmd.finish("图片渲染失败，请稍后再试~")
    try:
        await get_bot().send_group_msg(group_id=int(gid), message=MessageSegment.image(str(img_path)))
    except Exception as e:
        logger.error(f"发送排行榜图片失败: {e}")
        await cmd.finish("排行榜图片发送失败~")


rank_cmd = on_command("排行榜", aliases={"综合排行榜", "属性排行榜"}, priority=5, block=True)


@rank_cmd.handle()
async def handle_rank(event: MessageEvent):
    gid = _get_group(event)
    if not gid:
        await rank_cmd.finish("排行榜只在群聊中使用哦~")
    group = _group_data(gid)
    scored = [
        (uid, u, sum(u.get(k, 0) for k in ATTRIBUTES))
        for uid, u in group.items()
    ]
    scored = [x for x in scored if x[2] > 0]
    if not scored:
        await rank_cmd.finish("当前群里还没有人拥有属性，快去签到打工吧~")
    scored.sort(key=lambda x: (x[2], x[1].get("baguettes", 0)), reverse=True)
    rows = []
    for rank, (uid, u, total) in enumerate(scored[:10], start=1):
        name = await _nickname(gid, uid)
        rows.append((rank, name, f"{total}点 · 法棍 {u.get('baguettes', 0)}"))
    await _send_board(rank_cmd, event, gid, "法棍经济 · 综合属性排行榜", rows)


baguette_rank_cmd = on_command("法棍榜", aliases={"法棍排行榜", "法棍数量榜"}, priority=5, block=True)


@baguette_rank_cmd.handle()
async def handle_baguette_rank(event: MessageEvent):
    gid = _get_group(event)
    if not gid:
        await baguette_rank_cmd.finish("法棍榜只在群聊中使用哦~")
    group = _group_data(gid)
    scored = [
        (uid, u.get("baguettes", 0), u.get("wet_baguettes", 0))
        for uid, u in group.items()
    ]
    scored = [x for x in scored if x[1] > 0]
    if not scored:
        await baguette_rank_cmd.finish("当前群里还没有人拥有法棍，快去签到打工吧~")
    scored.sort(key=lambda x: x[1], reverse=True)
    rows = []
    for rank, (uid, b, w) in enumerate(scored[:10], start=1):
        name = await _nickname(gid, uid)
        value = f"{b} 根" + (f" · 湿润 {w}" if w else "")
        rows.append((rank, name, value))
    await _send_board(baguette_rank_cmd, event, gid, "法棍经济 · 法棍数量排行榜", rows)

