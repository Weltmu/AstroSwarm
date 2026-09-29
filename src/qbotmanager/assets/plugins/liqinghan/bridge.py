# -*- coding: utf-8 -*-
"""李清菡微信桥：与 dsh qbm_bridge 同协议的本地 HTTP 服务（默认 18650）。

qbm_bridge_client 插件把微信消息 POST 到 /v1/message，本桥把消息交给
李清菡 agent，并把回复原样返回（由客户端回发微信）。
"""
import asyncio
import json
import logging
import time


async def handle_payload(agent, payload, channel=None):
    """处理一条桥消息，返回 {session_id, reply}。"""
    session_key = str(payload.get("session_key") or "")
    text = str(payload.get("text") or "").strip()
    sender_name = str(payload.get("sender_name") or "微信用户")
    is_group = bool(payload.get("is_group", False))
    if not session_key or not text:
        return {"session_id": session_key, "reply": ""}
    parts = session_key.split(":", 2)
    openid = parts[2] if len(parts) == 3 else session_key
    if channel is not None:
        channel.set_source("wechat:private")
    data = {
        "post_type": "message",
        "message_type": "group" if is_group else "private",
        "session_key": session_key,
        "user_id": openid,
        "group_id": "",
        "message_id": f"wechat:{int(time.time() * 1000)}",
        "message": [{"type": "text", "data": {"text": text}}],
        "raw_message": text,
        "sender": {"nickname": sender_name, "card": sender_name},
        "source": "wechat:private",
    }
    try:
        await agent.on_event(data)
        reply = await agent.wait_for_reply(session_key, timeout=180)
    except Exception as e:  # noqa: BLE001
        logging.exception("微信桥处理失败：%s", e)
        reply = ""
    return {"session_id": session_key, "reply": reply}


class WechatBridge:
    """零依赖 asyncio HTTP 服务（POST /v1/message）。"""

    def __init__(self, agent, channel=None, host="127.0.0.1", port=18650):
        self.agent = agent
        self.channel = channel
        self.host = host
        self.port = port
        self._server = None

    async def start(self):
        self._server = await asyncio.start_server(
            self._handle, self.host, self.port)
        logging.info("李清菡微信桥已启动 http://%s:%s", self.host, self.port)

    async def stop(self):
        if self._server is not None:
            self._server.close()
            try:
                await self._server.wait_closed()
            except Exception:  # noqa: BLE001
                pass
            self._server = None

    async def _handle(self, reader, writer):
        try:
            request_line = await reader.readline()
            parts = request_line.decode("utf-8", "ignore").strip().split()
            if len(parts) < 2:
                await self._write_json(writer, 400, {"error": "bad request"})
                return
            method, path = parts[0], parts[1]
            headers = {}
            while True:
                line = await reader.readline()
                if line in (b"\r\n", b"\n", b""):
                    break
                k, _, v = line.decode("utf-8", "ignore").partition(":")
                headers[k.strip().lower()] = v.strip()
            body = b""
            try:
                n = int(headers.get("content-length") or "0")
            except ValueError:
                n = 0
            if n > 0 and n <= 65536:
                body = await reader.readexactly(n)
            if method == "POST" and path == "/v1/message":
                try:
                    payload = json.loads(body.decode("utf-8", "ignore"))
                    if not isinstance(payload, dict):
                        raise ValueError("payload 不是 JSON 对象")
                except (ValueError, json.JSONDecodeError) as e:
                    await self._write_json(writer, 400, {"error": str(e)})
                    return
                out = await handle_payload(self.agent, payload, self.channel)
                await self._write_json(writer, 200, out)
            elif method == "GET" and path in ("/healthz", "/"):
                await self._write_json(writer, 200, {"ok": True, "service": "liqinghan-bridge"})
            else:
                await self._write_json(writer, 404, {"error": "not found"})
        except Exception as e:  # noqa: BLE001
            logging.exception("微信桥请求处理异常")
            await self._write_json(writer, 500, {"error": str(e)})
        finally:
            try:
                writer.close()
            except Exception:  # noqa: BLE001
                pass

    @staticmethod
    async def _write_json(writer, status, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        reason = {200: "OK", 400: "Bad Request", 404: "Not Found", 500: "Internal Server Error"}
        writer.write(
            f"HTTP/1.1 {status} {reason.get(status, '')}\r\n"
            "Content-Type: application/json; charset=utf-8\r\n"
            f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode("utf-8"))
        writer.write(body)
        await writer.drain()
