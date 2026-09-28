import shutil
import subprocess
import urllib.request
from pathlib import Path

from .exceptions import CancelledError


class DownloadError(RuntimeError):
    pass


def _run_curl(url: str, dest: Path, timeout: int, cancel_event=None):
    if cancel_event is not None and cancel_event.is_set():
        raise CancelledError("下载已取消")
    cmd = [
        "curl", "-L", "--retry", "2", "--connect-timeout", "30",
        "--max-time", str(timeout), "-sS", "-o", str(dest), url,
    ]
    r = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if cancel_event is not None and cancel_event.is_set():
        raise CancelledError("下载已取消")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def _run_urllib(url: str, dest: Path, progress, timeout: int, cancel_event=None, resume: bool = True):
    """流式下载到 dest（.part 临时文件），支持断点续传与实时进度。"""
    headers = {"User-Agent": "Mozilla/5.0 (AstroSwarm)"}
    start = 0
    if resume and dest.exists():
        start = dest.stat().st_size
    if start:
        headers["Range"] = "bytes=" + str(start) + "-"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        total_hdr = resp.headers.get("Content-Length") or 0
        if resp.status == 206:
            total = start + int(total_hdr)
            mode = "ab"
        else:
            total = int(total_hdr)
            mode = "wb"
            start = 0
        done = start
        with open(dest, mode) as f:
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    raise CancelledError("下载已取消")
                chunk = resp.read(256 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
def download(url: str, dest: str | Path, progress=None, timeout: int = 600,
             cancel_event=None, resume: bool = True) -> Path:
    """优先 urllib 带进度下载，失败回退 curl（含断点续传）。"""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    part = dest.with_name(dest.name + ".part")
    if not resume:
        try:
            part.unlink()
        except OSError:
            pass
    last_err: Exception | None = None
    try:
        _run_urllib(url, part, progress, timeout=min(timeout, 600),
                    cancel_event=cancel_event, resume=resume)
        part.replace(dest)
        return dest
    except CancelledError:
        raise
    except Exception as e:
        last_err = e
    if shutil.which("curl"):
        rc, out = _run_curl(url, part, timeout, cancel_event=cancel_event)
        if rc == 0 and part.exists() and part.stat().st_size > 0:
            try:
                part.replace(dest)
            except OSError:
                raise DownloadError("下载失败: " + str(dest))
            return dest
        if "Could not resolve" in out or "Failed to connect" in out:
            raise DownloadError("无法连接下载源: " + out.strip()[-200:])
    raise DownloadError("下载失败: " + str(last_err))
def download_with_mirrors(base_url: str, dest: str | Path, progress=None,
                          prefixes=(), timeout: int = 600, cancel_event=None) -> Path:
    """依次尝试多个镜像前缀，全部失败才抛错。"""
    dest = Path(dest)
    last_err: Exception | None = None
    for prefix in prefixes:
        url = prefix + base_url
        try:
            return download(url, dest, progress=progress, timeout=timeout, cancel_event=cancel_event)
        except CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            last_err = e
            try:
                if dest.exists():
                    dest.unlink()
            except OSError:
                pass
    raise DownloadError(f"所有下载源均失败: {last_err}")
