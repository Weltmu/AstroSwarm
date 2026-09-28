# -*- coding: utf-8 -*-
"""iLink 协议客户端：登录（二维码/配对码）、长轮询收消息、发送文字、会话过期重登。"""
import asyncio
import base64
import json
import random
import time
from pathlib import Path
from typing import Awaitable, Callable, Optional

import httpx

SESSION_EXPIRED_ERRCODE = -14


class SessionExpired(Exception):
    """iLink 会话过期（errcode -14），需要重新扫码。"""


def _uin() -> str:
    return base64.b64encode(str(random.randint(0, 0xFFFFFFFF)).encode()).decode()


def _base_info() -> dict:
    return {
        "channel_version": "2.4.3",
        "bot_agent": "nonebot-adapter-ilink/0.1.0",
    }


def _headers(token: Optional[str] = None) -> dict:
    h = {
        "Content-Type": "application/json",
        "AuthorizationType": "ilink_bot_token",
        "X-WECHAT-UIN": _uin(),
        "iLink-App-Id": "bot",
        "iLink-App-ClientVersion": str((2 << 16) | (4 << 8) | 3),
    }
    if token:
        h["Authorization"] = "Bearer " + token
    return h


class IlinkClient:
    def __init__(
        self,
        base_url: str = "https://ilinkai.weixin.qq.com",
        state_file: str = "",
        bot_type: str = "3",
        log: Optional[Callable[[str], None]] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.bot_type = bot_type
        self.state_file = Path(state_file) if state_file else None
        self.log = log or (lambda m: None)
        self.http = httpx.AsyncClient(timeout=45)
        self.token: str = ""
        self.baseurl: str = self.base_url
        self.bot_id: str = ""
        self.user_id: str = ""
        self.get_updates_buf: str = ""
        self.last_poll_ts: float = 0.0  # 最近一次 getupdates 成功时间（连接心跳）
        self.verify_code: str = ""  # 手机端配对码，由外部通过 submit_verify_code 写入
        self._load_state()

    def _log(self, msg: str):
        self.log(f"[{time.strftime('%H:%M:%S')}] {msg}")

    def submit_verify_code(self, code: str):
        self.verify_code = code

    # ---------- 状态持久化 ----------
    def _load_state(self):
        if not self.state_file or not self.state_file.exists():
            return
        try:
            data = json.loads(self.state_file.read_text(encoding="utf-8"))
            self.token = data.get("token", "")
            self.baseurl = data.get("baseurl") or self.base_url
            self.bot_id = data.get("bot_id", "")
            self.user_id = data.get("user_id", "")
            self.get_updates_buf = data.get("get_updates_buf", "")
            self.last_poll_ts = float(data.get("last_poll_ts") or 0)
            if self.token:
                self._clear_status()
                self._log("已从状态文件恢复登录（token 有效期内无需重扫）")
        except Exception as e:
            self._log(f"读取状态文件失败: {e}")

    def _save_state(self):
        if not self.state_file:
            return
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            self.state_file.write_text(
                json.dumps(
                    {
                        "token": self.token,
                        "baseurl": self.baseurl,
                        "bot_id": self.bot_id,
                        "user_id": self.user_id,
                        "login_time": time.time(),
                        "get_updates_buf": self.get_updates_buf,
                        "last_poll_ts": self.last_poll_ts,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        except Exception as e:
            self._log(f"保存状态文件失败: {e}")

    def _write_status(self, status: str, extra: str = ""):
        """把扫码进度写到状态文件旁边，AstroSwarm UI 可实时展示。"""
        if not self.state_file:
            return
        try:
            p = self.state_file.parent / "ilink_login_status.json"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(
                json.dumps(
                    {"login_status": status, "ts": time.time(), "extra": extra},
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        except Exception as e:
            self._log(f"写入扫码状态失败: {e}")

    def _clear_status(self):
        if not self.state_file:
            return
        try:
            p = self.state_file.parent / "ilink_login_status.json"
            if p.exists():
                p.unlink()
        except Exception:
            pass

    def _read_verify_code_file(self) -> str:
        """读取 UI 写入的配对码文件（读后即删，类似 PoC 的 verify_code.txt）。"""
        if not self.state_file:
            return ""
        p = self.state_file.parent / "ilink_verify_code.txt"
        try:
            if p.exists():
                code = p.read_text(encoding="utf-8").strip()
                p.unlink(missing_ok=True)
                return code
        except Exception as e:
            self._log(f"读取配对码文件失败: {e}")
        return ""

    # ---------- HTTP ----------
    async def _get(self, path: str, token: Optional[str] = None, timeout: float = 45):
        r = await self.http.get(self.baseurl.rstrip("/") + "/" + path, headers=_headers(token), timeout=timeout)
        return r.json()

    async def _post(self, path: str, body: dict, token: Optional[str] = None, timeout: float = 45):
        r = await self.http.post(
            self.baseurl.rstrip("/") + "/" + path, json=body, headers=_headers(token), timeout=timeout
        )
        return r.json()

    # ---------- 登录 ----------
    async def ensure_login(
        self,
        qr_callback: Optional[Callable[[str], None]] = None,
        timeout_sec: int = 600,
    ) -> bool:
        """已有 token 直接复用；否则走扫码登录。"""
        if self.token:
            return True
        return await self.login(qr_callback=qr_callback, timeout_sec=timeout_sec)

    async def login(
        self,
        qr_callback: Optional[Callable[[str], None]] = None,
        timeout_sec: int = 600,
    ) -> bool:
        for attempt in range(4):
            data = await self._post(
                f"ilink/bot/get_bot_qrcode?bot_type={self.bot_type}",
                {"local_token_list": []},
                timeout=30,
            )
            qrcode = data.get("qrcode")
            if not qrcode:
                data = await self._get(f"ilink/bot/get_bot_qrcode?bot_type={self.bot_type}", timeout=30)
                qrcode = data.get("qrcode")
            if not qrcode:
                self._log(f"获取二维码失败（第{attempt + 1}次）: {str(data)[:200]}")
                await asyncio.sleep(3)
                continue
            content = data.get("qrcode_img_content") or qrcode
            if qr_callback:
                qr_callback(content)
            self._log("请用微信扫码（ClawBot 私密通道，扫码后微信会出现 ClawBot 会话）")
            result = await self._wait_login(qrcode, timeout_sec)
            if result.get("token"):
                self.token = result["token"]
                self.baseurl = result.get("baseurl") or self.base_url
                self.bot_id = result.get("bot_id", "")
                self.user_id = result.get("user_id", "")
                self.get_updates_buf = ""
                self._save_state()
                self._clear_status()
                self._log(f"登录成功 bot_id={self.bot_id}")
                return True
            self._log("本次扫码未完成，自动刷新重试")
        self._log("多次登录失败")
        return False

    async def relogin(self, qr_callback: Optional[Callable[[str], None]] = None) -> bool:
        self.token = ""
        self.get_updates_buf = ""
        self._save_state()
        return await self.login(qr_callback=qr_callback)

    async def _wait_login(self, qrcode: str, timeout_sec: int) -> dict:
        deadline = time.time() + timeout_sec
        verify_code = ""
        while time.time() < deadline:
            endpoint = "ilink/bot/get_qrcode_status?qrcode=" + qrcode
            if verify_code:
                endpoint += "&verify_code=" + verify_code
            try:
                status = await self._get(endpoint, timeout=40)
            except Exception as e:
                self._log(f"轮询扫码状态失败: {e}")
                await asyncio.sleep(1)
                continue
            state = status.get("status", "")
            if status.get("bot_token") or state == "confirmed":
                return {
                    "token": status.get("bot_token"),
                    "baseurl": status.get("baseurl") or status.get("base_url") or self.base_url,
                    "bot_id": status.get("ilink_bot_id", ""),
                    "user_id": status.get("ilink_user_id", ""),
                }
            if state == "expired":
                self._write_status("expired", "二维码已过期")
                self._log("二维码已过期")
                return {}
            if state == "scaned_but_redirect" or status.get("scaned_but_redirect"):
                host = status.get("redirect_host") or status.get("redirectBase") or ""
                if host:
                    host = str(host).lstrip("/")
                    self.baseurl = "https://" + host
                    self._log(f"扫码轮询已切换到新节点: {self.baseurl}")
                    self._write_status("redirect", self.baseurl)
                else:
                    self._log(f"服务端要求切换轮询节点但未给 redirect_host: {str(status)[:200]}")
                continue
            if state == "binded_redirect" or status.get("binded_redirect"):
                self._write_status("binded_redirect", "该微信已绑定过 ClawBot")
                self._log("该微信已绑定过 ClawBot（binded_redirect），无法重复绑定；"
                          "请确认是否已用其它程序/账号登录过，或换一个微信号扫码")
                return {}
            if state == "scaned":
                self._write_status("scaned", "已扫码，请在微信里继续操作")
                self._log("已扫码，请在微信里继续操作（确认连接，如显示配对码请提交）...")
                verify_code = ""
            elif state == "need_verifycode" or status.get("need_verifycode"):
                if not verify_code:
                    self._write_status("need_verifycode", "手机微信显示数字配对码")
                    self._log("手机微信显示数字配对码：请在 AstroSwarm 微信页点「输入配对码」提交")
                    for _ in range(150):
                        code = self._read_verify_code_file()
                        if not code and self.verify_code:
                            code = self.verify_code
                            self.verify_code = ""
                        if code:
                            verify_code = code
                            self._log("已收到配对码，继续轮询")
                            break
                        await asyncio.sleep(2)
            elif state == "verify_code_blocked":
                self._write_status("verify_code_blocked", "配对码错误次数过多")
                self._log("配对码错误次数过多，二维码将刷新")
                return {}
            elif state and state != "wait":
                self._log(f"扫码状态: {state} 原始响应: {json.dumps(status, ensure_ascii=False)[:200]}")
            await asyncio.sleep(1)
        self._write_status("timeout", "等待扫码超时")
        return {}

    # ---------- 收消息 ----------
    async def monitor(
        self,
        on_message: Callable[[dict], Awaitable[None]],
        on_session_expired: Optional[Callable[[], Awaitable[None]]] = None,
    ):
        consecutive_fail = 0
        while True:
            try:
                resp = await self._post(
                    "ilink/bot/getupdates",
                    {"get_updates_buf": self.get_updates_buf, "base_info": _base_info()},
                    token=self.token,
                    timeout=45,
                )
            except (httpx.ReadTimeout, asyncio.TimeoutError):
                # iLink getupdates 是长轮询：没有新消息时服务端会一直保持连接直到读超时，
                # 这属于"连接存活"而非失败。这里刷新心跳时间戳，让 UI 能主动显示已连接，
                # 不必等用户发消息才更新；网络断开/协议错误仍走下面的失败分支。
                self.last_poll_ts = time.time()
                self._save_state()
                continue
            except Exception as e:
                consecutive_fail += 1
                self._log(f"getupdates 请求异常: {e}")
                await asyncio.sleep(30 if consecutive_fail >= 3 else 2)
                continue
            ret = resp.get("ret")
            errcode = resp.get("errcode")
            if ret not in (None, 0) or errcode not in (None, 0):
                if errcode == SESSION_EXPIRED_ERRCODE or ret == SESSION_EXPIRED_ERRCODE:
                    self._log("会话过期（errcode -14），需要重新扫码")
                    if on_session_expired:
                        await on_session_expired()
                    raise SessionExpired()
                consecutive_fail += 1
                self._log(f"getupdates 失败 ret={ret} errcode={errcode} errmsg={resp.get('errmsg')}")
                await asyncio.sleep(30 if consecutive_fail >= 3 else 2)
                continue
            consecutive_fail = 0
            self.last_poll_ts = time.time()
            self._save_state()
            if resp.get("get_updates_buf"):
                self.get_updates_buf = resp["get_updates_buf"]
            for msg in resp.get("msgs") or []:
                if msg.get("message_type") == 1:
                    await on_message(msg)

    # ---------- 发消息 ----------
    async def send_text(self, to_user_id: str, context_token: str, text: str) -> bool:
        if not to_user_id or not context_token:
            self._log("发送失败：缺少 to_user_id 或 context_token")
            return False
        body = {
            "msg": {
                "from_user_id": "",
                "to_user_id": to_user_id,
                "client_id": f"adapter-{random.randint(0, 0xFFFFFFFF):08x}",
                "message_type": 2,
                "message_state": 2,
                "context_token": context_token,
                "item_list": [{"type": 1, "text_item": {"text": text}}],
            },
            "base_info": _base_info(),
        }
        try:
            resp = await self._post("ilink/bot/sendmessage", body, token=self.token, timeout=20)
            if resp.get("ret") not in (None, 0):
                self._log(f"发送失败: {str(resp)[:200]}")
                return False
            return True
        except Exception as e:
            self._log(f"发送异常: {e}")
            return False

    async def close(self):
        await self.http.aclose()
