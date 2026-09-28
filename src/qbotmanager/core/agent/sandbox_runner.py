# -*- coding: utf-8 -*-
"""沙箱子进程入口：在受限环境里加载插件并执行一个工具（被 sandbox.py 拉起）。

协议（stdin/stdout，一行一条 JSON）：
  父 → 子：{"pack_dir":..., "tool":..., "args":..., "ctx": {...}}
  子 → 父：{"call": {"action":..., "params":...}}   插件请求主程序做事
  父 → 子：{"reply": {...}}                          主程序回执
  子 → 父：{"result": "..."} 或 {"error":..., "traceback":...}

限制（够用就好，不是内核级沙箱）：
- 导入白名单：os / io / socket / subprocess / importlib / pathlib / nonebot … 全部拒绝；
- 文件读写：builtins.open 被替换成拒绝函数（插件读写数据一律走主程序动作）；
- 联网：socket/urllib.request 都不可导入，联网只能走 ctx.send("http_request", ...)；
- 插件的 print 会被重定向到 stderr，避免污染协议；
- 超时与进程回收由父进程负责（超时强杀）。
"""
import builtins
import json
import sys
import traceback

# plugin 可用的标准库白名单（含 urllib.parse，只给 URL 解析，不给联网）
ALLOWED_TOP = {
    "json", "re", "time", "datetime", "math", "random", "string",
    "collections", "itertools", "functools", "hashlib", "hmac", "base64",
    "binascii", "typing", "dataclasses", "enum", "statistics", "decimal",
    "unicodedata", "textwrap", "uuid", "csv", "difflib", "copy", "heapq",
    "bisect", "operator", "numbers", "fractions",
}
ALLOWED_EXACT = {"urllib.parse"}

DENY_TOP = {
    "os", "sys", "io", "socket", "ssl", "select", "signal", "subprocess",
    "threading", "multiprocessing", "asyncio", "ctypes", "importlib",
    "pathlib", "shutil", "tempfile", "glob", "pickle", "shelve", "sqlite3",
    "webbrowser", "http", "urllib", "ftplib", "smtplib", "imaplib",
    "poplib", "telnetlib", "xmlrpc", "requests", "httpx", "aiohttp",
    "urllib3", "nonebot", "qbotmanager", "inspect", "ast", "platform",
    "getpass", "resource", "pty", "fcntl", "mmap", "winreg", "msvcrt",
    "code", "codeop", "runpy", "site", "sysconfig", "zipfile", "tarfile",
    "gzip", "bz2", "lzma", "logging", "warnings", "traceback",
}

MAX_RESULT_CHARS = 60000


def _preload():
    """先把白名单模块全部导入（此时还没装守卫），避免插件触发内部惰性导入。"""
    for name in sorted(ALLOWED_TOP):
        try:
            __import__(name)
        except Exception:  # noqa: BLE001 —— 个别模块在精简解释器里缺依赖不影响其他
            continue
    for name in sorted(ALLOWED_EXACT):
        try:
            __import__(name)
        except Exception:  # noqa: BLE001
            continue


_PRELOADED = None


def _install_guard():
    global _PRELOADED
    _PRELOADED = set(sys.modules)
    real_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        top = str(name).split(".")[0]
        if top in DENY_TOP:
            raise ImportError(f"sandbox_denied: 不允许导入 {top}")
        if top in ALLOWED_TOP or name in ALLOWED_EXACT:
            return real_import(name, globals, locals, fromlist, level)
        if top.startswith("_") and name in _PRELOADED:
            return real_import(name, globals, locals, fromlist, level)
        raise ImportError(f"sandbox_denied: 不允许导入 {name}")

    builtins.__import__ = guarded_import

    def denied_open(*_args, **_kwargs):
        raise PermissionError("sandbox_denied: 沙箱里不能直接读写文件")

    builtins.open = denied_open
    builtins.input = lambda *a, **k: (_ for _ in ()).throw(
        RuntimeError("sandbox_denied: 沙箱里不能读输入"))
    builtins.breakpoint = lambda *a, **k: None


class _HostCall:
    """子进程 → 父进程的同步请求通道（一行 JSON 一问一答）。"""

    def __init__(self, out, inp):
        self._out = out
        self._in = inp
        self.calls = 0

    def __call__(self, action, params=None):
        self.calls += 1
        payload = json.dumps(
            {"call": {"action": str(action), "params": dict(params or {})}},
            ensure_ascii=False, default=str)
        self._out.write(payload + "\n")
        self._out.flush()
        line = self._in.readline()
        if not line:
            raise RuntimeError("sandbox_host_closed")
        try:
            msg = json.loads(line)
        except Exception:  # noqa: BLE001
            raise RuntimeError("sandbox_bad_reply")
        reply = msg.get("reply")
        if not isinstance(reply, dict):
            reply = {"ok": False, "error": "bad_reply"}
        return reply


class _Store:
    """记忆 / 提醒的沙箱代理：读写都交给主程序，插件拿到的是真实结果。"""

    def __init__(self, call):
        self._call = call

    def add_reminder(self, minutes, text, target=""):
        res = self._call("reminder_add", {
            "minutes": int(minutes), "text": str(text), "target": str(target or ""),
        })
        if not res.get("ok"):
            raise RuntimeError(str(res.get("error") or "reminder_failed"))
        return str(res.get("reminder_id") or "")

    def remember(self, user, fact):
        res = self._call("memory_write", {"user": str(user or ""), "fact": str(fact)})
        if not res.get("ok"):
            raise RuntimeError(str(res.get("error") or "memory_failed"))
        return True

    def fetch_memory(self, user=""):
        res = self._call("memory_read", {"user": str(user or "")})
        if not res.get("ok"):
            raise RuntimeError(str(res.get("error") or "memory_failed"))
        return res.get("memory")


class SandboxCtx:
    """给插件的假上下文：只有声明的权限、动作全部走主程序。"""

    def __init__(self, data):
        self.platform = str(data.get("platform") or "")
        self.scene = str(data.get("scene") or "")
        self.user_id = str(data.get("user_id") or "")
        self.group_id = str(data.get("group_id") or "")
        self.nickname = str(data.get("nickname") or "")
        self.is_superuser = bool(data.get("is_superuser"))
        self.extra = dict(data.get("extra") or {})
        self.cfg = {}
        self._permissions = {str(p) for p in (data.get("permissions") or [])}
        self.effect_results = []
        self.calls = 0
        self._call = None
        self.store = None

    def bind(self, call):
        self._call = call
        self.store = _Store(call)
        return self

    @property
    def source(self):
        if not self.platform:
            return ""
        if self.platform == "qq":
            return "qq:group" if self.scene == "group" else "qq:c2c"
        return f"{self.platform}:{self.scene or 'private'}"

    def can(self, permission):
        return str(permission) in self._permissions

    def send(self, action, params=None):
        res = self._call(str(action), params)
        self.effect_results.append(res)
        return res


def _load_module(path):
    import importlib.util  # 守卫安装前导入，之后插件自己拿不到 importlib

    spec = importlib.util.spec_from_file_location("workshop_plugin", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    # 子进程命令行默认走系统编码（Windows 简体中文是 GBK），协议统一成 UTF-8
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            continue
    raw = sys.stdin.readline()
    if not raw:
        return 2
    payload = json.loads(raw)
    pack_dir = str(payload.get("pack_dir") or ".")
    tool = str(payload.get("tool") or "")
    module_path = f"{pack_dir}/tools/{tool}.py".replace("\\", "/")
    stdout, stdin = sys.stdout, sys.stdin
    try:
        module = _load_module(module_path)
        handle = getattr(module, "handle")
    except Exception as exc:  # noqa: BLE001
        stdout.write(json.dumps({
            "error": "load_failed", "detail": str(exc),
            "traceback": traceback.format_exc()[-2000:],
        }, ensure_ascii=False) + "\n")
        stdout.flush()
        return 0
    _preload()
    _install_guard()
    sys.stdout = sys.stderr  # 插件里的 print 不再污染协议
    ctx = SandboxCtx(payload.get("ctx") or {}).bind(_HostCall(stdout, stdin))
    try:
        out = handle(ctx, dict(payload.get("args") or {}))
        if isinstance(out, str):
            text = out
        else:
            text = json.dumps(out, ensure_ascii=False, default=str)
        if len(text) > MAX_RESULT_CHARS:
            text = text[:MAX_RESULT_CHARS] + "…(truncated)"
        msg = {"result": text}
    except SystemExit:
        msg = {"error": "sys_exit"}
    except BaseException as exc:  # noqa: BLE001 —— 插件异常不能拖垮协议
        msg = {"error": "tool_exception", "detail": str(exc),
               "traceback": traceback.format_exc()[-2000:]}
    stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
    stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
