# -*- coding: utf-8 -*-
"""日志文件白名单与导出（桌面端「导出日志」用；口径与无头端 /api/logs/download 一致）。

三条规矩，和无头端保持一模一样：

- 调用方只能给「来源名」，白名单之外的字符串连路径拼接的机会都没有；
- 一次读进内存再写盘：日志在被持续追加，先按 stat 算长度再读会读到「长出来的那截」，
  导出文件就会多出半行 / 长度对不上；
- 只取文件尾部 MAX_EXPORT_BYTES，避免把几 GB 的大日志整份读进内存。

来源名与 core/cleanup._LOG_FILES 是同一批文件（清理和导出看到的必须是同一组）。
"""
from pathlib import Path

LOG_FILES = {
    "nonebot": "nonebot.log",
    "manager": "manager.log",
    "deploy": "deploy.log",
    "dsh": "dsh.log",
    "liqinghan": "liqinghan.log",
}
LOG_NAME_LIST = "/".join(LOG_FILES)
DEFAULT_NAME = "nonebot"
MAX_EXPORT_BYTES = 4 * 1024 * 1024


def resolve(logs_dir, name) -> tuple:
    """把「来源名」映射成 (规范名, 绝对路径)。非法名字抛 ValueError，由调用方提示。"""
    key = str(name or "").strip().lower()
    if key in ("", "all", "default"):
        key = DEFAULT_NAME
    filename = LOG_FILES.get(key)
    if filename is None:
        raise ValueError(key)
    return key, Path(logs_dir) / filename


def read_tail(path, limit: int = MAX_EXPORT_BYTES) -> bytes:
    """读日志尾部（最多 limit 字节）。文件不存在 / 读不出来按空处理。"""
    path = Path(path)
    try:
        size = path.stat().st_size
        with open(path, "rb") as fh:
            if size > limit:
                fh.seek(size - limit)
            return fh.read()
    except OSError:
        return b""


def suggested_filename(name, stamp: str = "") -> str:
    """默认导出文件名：<来源>-<时间戳>.log（无头端给的是同一套命名）。"""
    key, _ = resolve(".", name)
    return f"{key}-{stamp}.log" if stamp else f"{key}.log"


def export(logs_dir, name, dest, limit: int = MAX_EXPORT_BYTES) -> dict:
    """导出某一份日志到 dest。文件不存在抛 FileNotFoundError，其余 IO 错误原样抛出。"""
    key, src = resolve(logs_dir, name)
    if not src.exists():
        raise FileNotFoundError(str(src))
    data = read_tail(src, limit)
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return {"name": key, "source": str(src), "path": str(dest), "bytes": len(data)}


def export_all(logs_dir, dest, limit: int = MAX_EXPORT_BYTES) -> dict:
    """把白名单里所有存在的日志各取尾部，拼成一份（每段带一行来源头）。

    界面上「来源」选的是「全部」时用它：一个人出问题时往往需要把机器人、部署、
    管理器几份日志一起发过来，一份一份导出太麻烦。
    """
    chunks = []
    sources = []
    for key, filename in LOG_FILES.items():
        src = Path(logs_dir) / filename
        if not src.exists():
            continue
        data = read_tail(src, limit)
        if not data:
            continue
        sources.append(key)
        chunks.append(f"===== {key} · {src} =====\n".encode("utf-8"))
        chunks.append(data)
        if not data.endswith(b"\n"):
            chunks.append(b"\n")
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    payload = b"".join(chunks)
    dest.write_bytes(payload)
    return {"name": "all", "sources": sources, "path": str(dest), "bytes": len(payload)}
