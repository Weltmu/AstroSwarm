# -*- coding: utf-8 -*-
"""微信桥客户端：把 ilink 微信消息转发到 dsh 的 qbm-bridge（同一大脑/记忆）。

启用条件：dsh 通道开启（AstroSwarm 设置自动注入 AI_PLATFORM_WECHAT=0，
旧 AI 插件不再处理微信，避免双回复）。本插件是内置组件，不可卸载。
"""
import httpx
from pydantic import BaseModel
from nonebot import get_plugin_config, logger, on_message
from nonebot.adapters import Bot as BaseBot
from nonebot.plugin import PluginMetadata

__plugin_meta__ = PluginMetadata(
    name="qbm-bridge-client",
    description="微信消息转发到 dsh 统一大脑（AstroSwarm 内置）",
    usage="无需手动调用：微信消息会自动转发到 dsh 统一大脑。",
    type="application",
)


class PluginConfig(BaseModel):
    """桥客户端配置（默认本地回环，程序自动注入）。"""

    qbm_bridge_url: str = "http://127.0.0.1:18650/v1/message"
    qbm_bridge_timeout: int = 180
    qbm_bridge_enabled: bool = True


config = get_plugin_config(PluginConfig)


def _is_wechat(event) -> bool:
    mod = type(event).__module__ or ""
    return "nonebot_adapter_ilink" in mod or hasattr(event, "context_token")


async def _bridge_reply(text: str, user_id: str, is_group: bool) -> str:
    payload = {
        "session_key": f"wechat:{'group' if is_group else 'private'}:{user_id}",
        "text": text,
        "sender_name": "微信用户",
        "is_group": bool(is_group),
    }
    timeout = httpx.Timeout(config.qbm_bridge_timeout)
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(config.qbm_bridge_url, json=payload)
        r.raise_for_status()
        data = r.json()
        # 协议 v1 是扁平 {session_id, reply}；兼容早期/异常版本的嵌套结构
        reply = data.get("reply") or ""
        if isinstance(reply, dict):
            reply = reply.get("reply") or ""
        return str(reply).strip()


if config.qbm_bridge_enabled:
    bridge = on_message(priority=8, block=False)

    @bridge.handle()
    async def _forward_to_dsh(bot: BaseBot, event):
        if not _is_wechat(event):
            return
        raw = str(getattr(event, "raw_message", "") or "").strip()
        if not raw and hasattr(event, "get_plaintext"):
            raw = str(event.get_plaintext() or "").strip()
        if not raw:
            return
        user_id = str(event.get_user_id() or "")
        if not user_id:
            return
        is_group = getattr(event, "message_type", 0) == "group"
        try:
            reply = await _bridge_reply(raw, user_id, is_group)
        except Exception as e:  # noqa: BLE001
            logger.error(f"[qbm-bridge-client] 转发失败: {e}")
            return
        if not reply:
            return
        try:
            await bot.send(event, reply)
        except Exception as e:  # noqa: BLE001
            logger.error(f"[qbm-bridge-client] 回发失败: {e}")
