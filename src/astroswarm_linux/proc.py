"""POSIX 进程适配：进程组拉起与整树终止。"""
import os
import signal
import subprocess
import sys
from pathlib import Path


def spawn(args, *, cwd, env, log_path):
    """以独立进程组启动进程，stdout/stderr 追加写入 log_path。"""
    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    stream = open(log_path, "ab")
    try:
        popen = subprocess.Popen(
            args,
            cwd=str(cwd),
            env={**os.environ, **env},
            stdout=stream,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    finally:
        stream.close()
    return popen


def is_alive(popen) -> bool:
    return popen.poll() is None


def kill_tree(popen, timeout: float = 5.0) -> None:
    """SIGTERM 整个进程组，超时后 SIGKILL。"""
    if popen.poll() is not None:
        return
    pid = popen.pid
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    except (AttributeError, ProcessLookupError, PermissionError):
        try:
            popen.terminate()
        except Exception:  # noqa: BLE001
            pass
    try:
        popen.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        except (AttributeError, ProcessLookupError, PermissionError):
            try:
                popen.kill()
            except Exception:  # noqa: BLE001
                pass
