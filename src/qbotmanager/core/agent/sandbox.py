# -*- coding: utf-8 -*-
"""插件沙箱（主程序侧）：AI 工坊生成的插件只能在独立子进程里跑。

原则（用户 2026-09-27 拍板）：
- 生成的插件默认没有全权限：权限只按 manifest 声明给，动作（发消息、记忆、
  联网、写数据）一律回到主程序校验后执行；
- 子进程 + 超时强杀 + 导入白名单 + 禁文件读写 + 默认断网（见 sandbox_runner.py）；
- 官方能力包不受影响（它们不走沙箱）。

执行放在独立线程的私有事件循环里，避免依赖调用方事件循环支不支持子进程；
插件请求动作时再桥回主事件循环执行（工具里 await 到的都是真实结果）。
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

RUNNER = Path(__file__).with_name("sandbox_runner.py")
DEFAULT_TIMEOUT = 15.0        # 单个工具执行总时长上限（秒）
HOST_CALL_TIMEOUT = 25.0      # 单个动作在主程序侧的执行上限
MAX_CALLS = 24                # 单次执行里最多请求多少个动作
MAX_ARGS_CHARS = 20000


class SandboxError(RuntimeError):
    """沙箱执行失败（崩溃、协议错误、缺执行器）。"""


class SandboxTimeout(SandboxError):
    """沙箱执行超时（已强杀子进程）。"""


def _ctx_payload(ctx) -> dict:
    extra = {}
    raw_extra = getattr(ctx, "extra", None) or {}
    if isinstance(raw_extra, dict):
        for key, value in list(raw_extra.items())[:20]:
            if isinstance(value, (str, int, float, bool)) or value is None:
                extra[str(key)] = value
    perms = []
    for perm in ("send_message", "group_admin", "timer", "memory",
                 "network", "media"):
        try:
            if ctx.can(perm):
                perms.append(perm)
        except Exception:  # noqa: BLE001
            continue
    return {
        "platform": getattr(ctx, "platform", "") or "",
        "scene": getattr(ctx, "scene", "") or "",
        "user_id": getattr(ctx, "user_id", "") or "",
        "group_id": getattr(ctx, "group_id", "") or "",
        "nickname": getattr(ctx, "nickname", "") or "",
        "is_superuser": bool(getattr(ctx, "is_superuser", False)),
        "extra": extra,
        "permissions": perms,
    }


def _kill(proc) -> None:
    try:
        if proc.returncode is None:
            proc.kill()
    except Exception:  # noqa: BLE001
        pass


async def _run_async(pack_dir: Path, tool_name: str, args: dict, ctx,
                     host, main_loop, timeout: float) -> str:
    if host is None:
        raise SandboxError("sandbox_host_missing：这次执行没有动作执行器")
    payload = {
        "pack_dir": str(pack_dir),
        "tool": tool_name,
        "args": args,
        "ctx": _ctx_payload(ctx),
    }
    raw = json.dumps(payload, ensure_ascii=False, default=str)
    if len(raw) > MAX_ARGS_CHARS * 4:
        raise SandboxError("sandbox_args_too_large：这次要传的参数太大了")
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-I", str(RUNNER),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(pack_dir),
            creationflags=creationflags,
        )
    except NotImplementedError as exc:  # 事件循环不支持子进程
        raise SandboxError(f"sandbox_unavailable：{exc}") from exc
    loop = asyncio.get_running_loop()
    deadline = loop.time() + float(timeout or DEFAULT_TIMEOUT)
    calls = 0

    async def read_line():
        remaining = deadline - loop.time()
        if remaining <= 0:
            raise SandboxTimeout(
                f"sandbox_timeout：插件跑了超过 {int(timeout or DEFAULT_TIMEOUT)} 秒，已停掉")
        try:
            line = await asyncio.wait_for(proc.stdout.readline(), remaining)
        except asyncio.TimeoutError as exc:
            raise SandboxTimeout(
                f"sandbox_timeout：插件跑了超过 {int(timeout or DEFAULT_TIMEOUT)} 秒，已停掉") from exc
        return line

    async def send(obj: dict):
        proc.stdin.write((json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8"))
        await proc.stdin.drain()

    try:
        await send(payload)
        while True:
            line = await read_line()
            if not line:
                err = b""
                try:
                    err = await asyncio.wait_for(proc.stderr.read(), 3)
                except Exception:  # noqa: BLE001
                    err = b""
                detail = err.decode("utf-8", "ignore")[-600:] if err else ""
                raise SandboxError(
                    "sandbox_crashed：插件进程挂了" + (f"：{detail}" if detail else ""))
            try:
                msg = json.loads(line.decode("utf-8", "ignore"))
            except Exception as exc:  # noqa: BLE001
                raise SandboxError(f"sandbox_bad_protocol：{exc}") from exc
            if "result" in msg:
                return str(msg.get("result") or "")
            if "error" in msg:
                detail = str(msg.get("detail") or "")
                tb = str(msg.get("traceback") or "")
                raise SandboxError(
                    f"sandbox_{msg.get('error')}：{detail}" + (f"\n{tb}" if tb else ""))
            call = msg.get("call") or {}
            action = str(call.get("action") or "")
            params = call.get("params") or {}
            calls += 1
            if calls > MAX_CALLS:
                await send({"reply": {"ok": False, "error": "too_many_calls"}})
                continue
            if not isinstance(params, dict):
                await send({"reply": {"ok": False, "error": "bad_params"}})
                continue
            try:
                fut = asyncio.run_coroutine_threadsafe(
                    host(action, params, ctx), main_loop)
                reply = await asyncio.wait_for(
                    asyncio.wrap_future(fut), HOST_CALL_TIMEOUT)
            except asyncio.TimeoutError:
                reply = {"ok": False, "error": "host_timeout", "action": action}
            except Exception as exc:  # noqa: BLE001
                reply = {"ok": False, "error": "host_error",
                         "detail": str(exc), "action": action}
            if not isinstance(reply, dict):
                reply = {"ok": True, "action": action, "value": reply}
            await send({"reply": reply})
        finally_cleanup = True
    finally:
        try:
            if proc.stdin and not proc.stdin.is_closing():
                proc.stdin.close()
        except Exception:  # noqa: BLE001
            pass
        _kill(proc)
        try:
            await proc.wait()
        except Exception:  # noqa: BLE001
            pass


def _run_blocking(pack_dir: Path, tool_name: str, args: dict, ctx, host,
                  main_loop, timeout: float) -> str:
    return asyncio.run(_run_async(pack_dir, tool_name, args, ctx, host,
                                  main_loop, timeout))


async def run_tool(pack_dir, tool_name: str, args: dict, ctx, host,
                   timeout: float | None = None) -> str:
    """在沙箱子进程里执行一个插件工具，返回它给的 JSON 文本。"""
    pack_dir = Path(pack_dir)
    if not (pack_dir / "tools" / f"{tool_name}.py").exists():
        raise SandboxError(f"sandbox_tool_missing：{tool_name}.py 不存在")
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None, _run_blocking, pack_dir, tool_name, args or {}, ctx, host, loop,
        float(timeout or DEFAULT_TIMEOUT))
