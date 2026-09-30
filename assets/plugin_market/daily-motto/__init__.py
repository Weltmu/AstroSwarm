# -*- coding: utf-8 -*-
"""每日一言：收到「每日一言 / 每日一句」回复一句名言/短句。

官方通道适配插件：QQ 官方机器人（@ 或全量群消息）与微信 iLink 私聊均可用。
"""
import random

from nonebot import logger, on_message
from nonebot.adapters import Bot as BaseBot
from nonebot.plugin import PluginMetadata

__plugin_meta__ = PluginMetadata(
    name="每日一言",
    description="说「每日一言」随机回一句名言/短句",
    usage="私聊直接说，或群里 @ 机器人说：每日一言",
    type="application",
    homepage="https://github.com/Weltmu",
    supported_adapters={"~QQ", "~nonebot_adapter_ilink"},
)

QUOTES = [
    "星光不问赶路人，时光不负有心人。",
    "种一棵树最好的时间是十年前，其次是现在。",
    "世界上只有一种真正的英雄主义，就是认清生活的真相后依然热爱生活。",
    "路虽远，行则将至；事虽难，做则必成。",
    "凡是过往，皆为序章。",
    "慢慢来，比较快。",
    "与其临渊羡鱼，不如退而结网。",
    "心之所向，素履以往。",
    "不驰于空想，不骛于虚声。",
    "少年不惧岁月长，彼方尚有荣光在。",
]

motto = on_message(priority=30, block=False)


@motto.handle()
async def _handle_motto(bot: BaseBot, event):
    try:
        text = str(event.get_plaintext() or "").strip()
    except Exception:  # noqa: BLE001
        return
    if text not in ("每日一言", "每日一句", "来一句", "来句名言", "名言"):
        return
    logger.info("[daily-motto] 触发每日一言")
    await bot.send(event, random.choice(QUOTES))
