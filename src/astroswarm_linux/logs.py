"""日志尾部读取与跟随（SSE 用）。"""
import time
from pathlib import Path

import anyio

# ---------------------------------------------------------------- 可控的日志来源
# 调用方（网页）只能给「名字」，**永远不能给路径**：下面的字典是唯一映射，
# 传进来的字符串不参与任何路径拼接，`../../etc/passwd` 这类输入连走到文件系统
# 的机会都没有（不在字典里 → 直接 400）。
# 两个文件都在 platform_info.log_home() = <数据目录>/logs/ 下：
#   headless.log = 无头端自己的进程日志（uvicorn 访问日志 + 管理器动作）
#   nonebot.log  = NoneBot 机器人自己的日志（deploy.bot_log_path() 用的同一个）
LOG_FILES = {
    "headless": "headless.log",
    "nonebot": "nonebot.log",
}
LOG_FILE_DEFAULT = "headless"
LOG_NAME_LIST = "/".join(LOG_FILES)


def resolve_log(name) -> tuple:
    """把 ?name= 映射成 (规范名, 绝对路径)。非法名字抛 ValueError，由接口层转 400。"""
    from . import platform_info

    key = str(name or "").strip().lower()
    if key in ("", "all", "default"):
        key = LOG_FILE_DEFAULT
    filename = LOG_FILES.get(key)
    if filename is None:
        raise ValueError(key)
    return key, platform_info.log_home() / filename


def tail(path: Path, n: int = 200) -> str:
    path = Path(path)
    if not path.exists():
        return ""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(lines[-n:]) + ("\n" if lines else "")


def _prepare(path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("", encoding="utf-8")
    return path


def _read_new(path: Path, pos: int):
    """读一次新增内容，返回 (chunk, 新位置)。不阻塞、不循环。"""
    try:
        size = path.stat().st_size
        if size < pos:          # 被截断/轮转过了，从头读
            pos = 0
        if size > pos:
            with open(path, "rb") as f:
                f.seek(pos)
                chunk = f.read()
            return chunk.decode("utf-8", errors="replace"), size
    except OSError:
        pass
    return "", pos


def follow(path: Path, interval: float = 0.5, start_from_end: bool = True,
           stop=None, max_seconds: float | None = None):
    """同步跟读日志；stop（threading.Event）被置位或超过 max_seconds 就退出。

    生成器必须有退出条件：交给 StreamingResponse 后走 anyio.to_thread，日志空闲时
    线程会卡在 next() 里，客户端断开也收不回（worker 线程只增不减）。
    这里给了 stop/max_seconds 两个出口；/api/logs/stream 走下面的 afollow（不占线程）。
    """
    path = _prepare(path)
    pos = path.stat().st_size if start_from_end else 0
    deadline = time.monotonic() + max_seconds if max_seconds else None
    while not (stop is not None and stop.is_set()):
        chunk, pos = _read_new(path, pos)
        if chunk:
            yield chunk
        if deadline is not None and time.monotonic() >= deadline:
            return
        if stop is not None:
            if stop.wait(interval):     # 可被立刻打断的 sleep
                return
        else:
            time.sleep(interval)


async def afollow(path: Path, interval: float = 0.5, start_from_end: bool = True,
                  max_seconds: float | None = 600):
    """异步跟读日志：**不占线程**，客户端断开时能真正取消。

    为什么 /api/logs/stream 必须用它：同步迭代器会被 starlette 丢进
    iterate_in_threadpool，而 anyio.to_thread.run_sync 默认要等线程跑完才传播取消 ——
    线程卡在 next() 上就永远等不到，于是每断开一次泄漏一个 OS 线程（永不退出），
    控制台刷新几次就能把进程拖到 can't start new thread。
    这里每次等待都在事件循环上，取消立刻生效；max_seconds 到点主动结束，
    让 EventSource 重连（默认 10 分钟）。
    """
    path = _prepare(path)
    pos = path.stat().st_size if start_from_end else 0
    deadline = time.monotonic() + max_seconds if max_seconds else None
    while True:
        chunk, pos = _read_new(path, pos)
        if chunk:
            yield chunk
        if deadline is not None and time.monotonic() >= deadline:
            return
        await anyio.sleep(interval)
