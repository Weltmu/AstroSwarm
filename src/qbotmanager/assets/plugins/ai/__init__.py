# -*- coding: utf-8 -*-
"""AI 对话插件（AstroSwarm 星群内置，不可卸载，可通过设置停用）。

环境变量 AI_DISABLED=1 时不注册任何功能（AstroSwarm 设置里的总开关控制）。
旧版本插件的数据会自动迁移到本插件目录（仅迁移一次）。
"""
import os as _os

from nonebot import get_driver, get_plugin_config, logger, on_message, require
from nonebot.adapters import Bot as BaseBot

require("nonebot_plugin_localstore")

from nonebot.plugin import PluginMetadata

from .config import PluginConfig

_DISABLED = _os.environ.get("AI_DISABLED") == "1"

if _DISABLED:
    __plugin_meta__ = PluginMetadata(
        name="ai",
        description="AI 对话插件（已停用，可在 AstroSwarm 设置中开启）",
        usage="由 AstroSwarm 控制 AI 对话能力开关",
        type="application",
        config=PluginConfig,
    )
else:
    from .adapters import build_channel
    from .brain import (
        group_manager,
        group_probability_states,
        group_timers,
        handle_message,
    )
    from .config import *  # noqa: F401,F403
    from .context import load_contexts
    from .manager import chat_manager
    from .platform import ChannelContext, ChannelMessage  # noqa: F401

    # 主动聊天是付费能力包：它的实现随本插件一起被导入过，等于免费也能用。
    # 现在只有部署端在确认授权（签名验签通过 + 已购/会员未到期）后才会置位这个变量。
    if _os.environ.get("ASTROSWARM_PACK_PROACTIVE") == "1":
        from .proactive import *  # noqa: F401,F403  主动聊天模块（导入时自动注册后台任务）
    else:
        logger.info(
            "主动聊天能力包未授权，跳过加载（在控制台「插件详情页」购买后点「我已付款，刷新权益」，"
            "再重启一次机器人即可生效）"
        )

    __plugin_meta__ = PluginMetadata(
        name="ai",
        description="AI 对话插件（AstroSwarm 内置）：大模型对话、主动聊天、人格设定",
        usage="在 AstroSwarm「AI 大脑」页配置人设与主动聊天",
        type="application",
        homepage="https://github.com/Weltmu",
        config=PluginConfig,
        supported_adapters={"~onebot.v11", "~QQ", "~nonebot_adapter_ilink"},
    )

    # 初始化管理器和上下文
    load_contexts()
    get_plugin_config(PluginConfig)

    # 创建消息处理器，不限制规则，在 handle 中自行判断
    chat = on_message(priority=50, block=False)

    @chat.handle()
    async def _(bot: BaseBot, event):
        """统一通道入口：按事件类型分发到对应适配器 → 归一化 → AI 大脑。"""
        logger.info(
            f"[ai] 收到事件 {type(event).__module__} "
            f"text={getattr(event, 'get_plaintext', lambda: '')()[:60]}")
        built = await build_channel(chat, bot, event)
        if built is None:
            logger.info("[ai] 平台分发返回 None，跳过")
            return
        msg, ctx = built
        await handle_message(msg, ctx)

    driver = get_driver()

    @driver.on_shutdown
    async def shutdown_hook():
        """Driver 关闭时清理定时任务"""
        if group_manager:
            await group_manager.shutdown()
