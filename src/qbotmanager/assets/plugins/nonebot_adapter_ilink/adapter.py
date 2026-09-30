# -*- coding: utf-8 -*-
"""iLink 适配器：启动时登录（恢复 token 或扫码），并跑长轮询监听。"""
import asyncio
import json
import time
from pathlib import Path

from nonebot import get_plugin_config, logger
from nonebot.adapters import Adapter as BaseAdapter
from nonebot.drivers import Driver

from .bot import Bot
from .client import IlinkClient, SessionExpired
from .config import Config
from .event import Event


def build_event(data: dict, self_id: str) -> Event:
    """iLink 原始消息 → NoneBot 事件。"""
    items = data.get("item_list") or []
    text = ""
    for item in items:
        if item.get("type") == 1 and item.get("text_item"):
            text = str(item["text_item"].get("text", ""))
            break
        if item.get("type") == 3 and item.get("voice_item"):
            text = str(item["voice_item"].get("text", ""))
            break
    group_id = str(data.get("group_id") or "")
    message_type = "group" if group_id else "private"
    return Event(
        self_id=self_id,
        time=(data.get("create_time_ms") or time.time() * 1000) / 1000.0,
        message_id=str(data.get("message_id") or data.get("seq") or ""),
        from_user_id=str(data.get("from_user_id") or ""),
        to_user_id=str(data.get("to_user_id") or ""),
        message_type=message_type,
        raw_message=text,
        context_token=str(data.get("context_token") or ""),
        group_id=group_id,
        raw=data,
    )


class Adapter(BaseAdapter):
    @classmethod
    def get_name(cls) -> str:
        return "WeChat iLink"

    def __init__(self, driver: Driver, **kwargs):
        super().__init__(driver, **kwargs)
        self.ilink_config: Config = get_plugin_config(Config)
        state_file = self.ilink_config.ilink_state_file or str(
            Path.cwd() / "data" / "nonebot_adapter_ilink" / "ilink_state.json"
        )
        self.client = IlinkClient(
            base_url=self.ilink_config.ilink_base_url,
            state_file=state_file,
            bot_type=self.ilink_config.ilink_bot_type,
            log=lambda m: logger.info(f"[ilink] {m}"),
        )
        self.bot: Bot | None = None
        self._monitor_task: asyncio.Task | None = None
        self._login_task: asyncio.Task | None = None
        driver.on_startup(self._startup)
        driver.on_shutdown(self._shutdown)

    async def _startup(self):
        # 微信登录放到后台：扫码未完成时不能阻塞 uvicorn 启动，
        # 否则 QQ 的 OneBot 反向 WS 服务起不来，QQ 消息进不来。
        self._login_task = asyncio.create_task(self._login())

    async def _login(self):
        ok = await self.client.ensure_login(qr_callback=self._show_qr)
        if not ok:
            logger.error("[ilink] 微信登录失败，请查看上方二维码信息后重启")
            return
        self.bot = Bot(self, self.client.bot_id or "ilink", self.client)
        self.bot_connect(self.bot)
        logger.success(f"[ilink] 微信通道已上线 bot_id={self.bot.self_id}")
        self._monitor_task = asyncio.create_task(self._monitor())

    def _show_qr(self, content: str):
        logger.warning("[ilink] 请用微信扫码连接 ClawBot：")
        logger.warning(content)
        # 无头端（服务器）看不到日志：把二维码内容落到 state 文件旁边，控制台读它显示
        try:
            import json as _json
            import time as _time
            from pathlib import Path as _Path

            state = getattr(self.client, "state_file", None)
            if state:
                p = _Path(state).parent / "ilink_qrcode.json"
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(
                    _json.dumps({"ts": _time.time(), "content": content}, ensure_ascii=False),
                    encoding="utf-8",
                )
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[ilink] 写二维码文件失败: {e}")

    async def _call_api(self, bot, api: str, **data):
        """适配器 API 调用入口（NoneBot 抽象方法），委托给 Bot。"""
        return await bot.call_api(api, **data)

    async def _monitor(self):
        while True:
            try:
                await self.client.monitor(on_message=self._on_message, on_session_expired=self._relogin)
                break
            except SessionExpired:
                logger.warning("[ilink] 会话过期，尝试重新扫码...")
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"[ilink] 监听异常: {e}")
                await asyncio.sleep(30)

    async def _relogin(self):
        ok = await self.client.relogin(qr_callback=self._show_qr)
        if ok and self.bot is not None:
            self.bot.self_id = self.client.bot_id or self.bot.self_id

    async def _on_message(self, data: dict):
        # 缓存最近一次会话的 context_token（微信主动发消息必须带它）
        try:
            import json as _json
            import time as _time
            from pathlib import Path as _Path

            uid = str(data.get("from_user_id") or data.get("user_id") or "")
            ctx = str(data.get("context_token") or "")
            state = getattr(self.client, "state_file", None)
            if uid and ctx and state:
                p = _Path(state).parent / "ilink_tokens.json"
                cache = {}
                try:
                    cache = _json.loads(p.read_text(encoding="utf-8"))
                    cache = cache if isinstance(cache, dict) else {}
                except Exception:  # noqa: BLE001
                    cache = {}
                cache[uid] = {"context_token": ctx, "ts": _time.time()}
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(_json.dumps(cache, ensure_ascii=False), encoding="utf-8")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[ilink] 缓存 context_token 失败: {e}")

        if self.bot is None:
            return
        event = build_event(data, self.bot.self_id)
        if not event.raw_message:
            return
        # 消息落盘：AstroSwarm 消息中心/微信页直接读取，不依赖 AI 是否回复
        try:
            f = Path.cwd() / "data" / "nonebot_adapter_ilink" / "messages.jsonl"
            f.parent.mkdir(parents=True, exist_ok=True)
            with open(f, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({
                    "ts": event.time or time.time(),
                    "from_user_id": event.from_user_id,
                    "to_user_id": event.to_user_id,
                    "message_type": event.message_type,
                    "text": event.raw_message,
                }, ensure_ascii=False) + "\n")
        except Exception:  # noqa: BLE001
            pass
        await self.bot.handle_event(event)

    async def _shutdown(self):
        if self._monitor_task:
            self._monitor_task.cancel()
        await self.client.close()
