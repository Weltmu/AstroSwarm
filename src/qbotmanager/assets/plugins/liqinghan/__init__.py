# -*- coding: utf-8 -*-
"""李清菡智能体 NoneBot 插件（AstroSwarm 内置，可选启用）。

启用条件：程序侧注入 QBM_AGENT_PROFILE_ENABLED=1（AI 大脑页开启李清菡档案）。
QQ 消息由本插件直接消费（官方适配器）；微信消息走现有 qbm_bridge_client
→ 本地 18650 桥 → 同一李清菡 agent（共享大脑与记忆）。
"""
import asyncio
import os

from nonebot import get_driver, logger, on_message
from nonebot.adapters import Bot as BaseBot
from nonebot.plugin import PluginMetadata

_ENABLED = os.environ.get("QBM_AGENT_PROFILE_ENABLED") == "1"
_AGENT = None
_CHANNEL = None
_BRIDGE = None
_TASKS = []

if _ENABLED:
    from .agent import Agent, setup_logging
    from .bridge import WechatBridge
    from .config import Config
    from .qq_official import DispatchChannel, to_data

    __plugin_meta__ = PluginMetadata(
        name="liqinghan",
        description="李清菡智能体（AstroSwarm 内置）：真人感 agent + 记忆 + 群管 + 游戏",
        usage="在 AstroSwarm「AI 大脑 → 智能体档案」启用并重启机器人",
        type="application",
        supported_adapters={"~QQ", "~nonebot_adapter_ilink"},
    )

    _cfg = Config()
    setup_logging(_cfg)
    _CHANNEL = DispatchChannel()
    _AGENT = Agent(_cfg, _CHANNEL)
    _BRIDGE = WechatBridge(
        _AGENT, _CHANNEL, port=int(os.environ.get("QBM_AGENT_BRIDGE_PORT", "18650")))

    _qq_msg = on_message(priority=20, block=False)

    @_qq_msg.handle()
    async def _handle_qq_message(bot: BaseBot, event):
        if _AGENT is None:
            return
        mod = type(event).__module__ or ""
        if "nonebot.adapters.qq" not in mod:
            return
        try:
            is_group = bool(getattr(event, "group_openid", None))
            source = "qq:group" if is_group else "qq:c2c"
            data = to_data(event, bot_qq=_cfg.bot_qq, source=source)
            _CHANNEL.set_current(bot, event, source)
            await _AGENT.on_event(data)
        except Exception as e:  # noqa: BLE001
            logger.exception(f"[liqinghan] QQ 消息处理失败: {e}")

    _driver = get_driver()

    @_driver.on_startup
    async def _startup():
        global _TASKS
        try:
            await _BRIDGE.start()
        except OSError as e:
            logger.warning(f"[liqinghan] 微信桥启动失败（18650 被占用？）: {e}")
        _TASKS = _AGENT.run_tasks()
        logger.info("[liqinghan] 李清菡智能体已启动，模型=%s", _cfg.ds_model)

    @_driver.on_shutdown
    async def _shutdown():
        await _BRIDGE.stop()
        for t in _TASKS:
            t.cancel()
        if _TASKS:
            await asyncio.gather(*_TASKS, return_exceptions=True)
        _TASKS.clear()
else:
    __plugin_meta__ = PluginMetadata(
        name="liqinghan",
        description="李清菡智能体（未启用，可在 AstroSwarm 设置中开启）",
        usage="在 AstroSwarm「AI 大脑 → 智能体档案」启用并重启机器人",
        type="application",
    )
