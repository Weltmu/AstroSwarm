# -*- coding: utf-8 -*-
"""nonebot-adapter-ilink：微信 ClawBot（官方 iLink 协议）NoneBot 适配器。

接入后，微信 ClawBot 私聊消息会以 NoneBot 事件进入统一事件流，
内置 AI 插件等即可跨平台复用同一个 AI 大脑。
"""
from nonebot import get_driver
from nonebot.plugin import PluginMetadata

from .adapter import Adapter
from .config import Config

__plugin_meta__ = PluginMetadata(
    name="nonebot-adapter-ilink",
    description="微信 ClawBot（官方 iLink）适配器：扫码登录、长轮询收消息、发送文字",
    usage="配置 ILINK_BASE_URL 等环境变量后，插件启动时会引导扫码登录",
    type="adapter",
    config=Config,
)

driver = get_driver()
driver.register_adapter(Adapter)
