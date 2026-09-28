# -*- coding: utf-8 -*-
"""AstroSwarm 开发预览启动器（源码直跑 + 自动重启）。

用法：
  .build_venv\\Scripts\\python.exe tools\\dev_preview_launcher.py

行为：
- 直接运行 src/main.py（不走 PyInstaller 打包），启动快、改完源码立即生效；
- 每秒扫描 src 下的 .py 文件，检测到变化自动重启程序；
- 程序崩溃时把 stderr 写入 logs/dev_preview_stderr.log 并显示尾部，等源码变化后重启；
- 用户正常关闭程序（退出码 0）后监视器一并退出。

注意：自动重启会强制结束程序，若正在运行机器人服务请先手动停止。
"""
import hashlib
import os
import subprocess
import sys
import tempfile
import time
import atexit
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
PY = ROOT / ".build_venv" / "Scripts" / "python.exe"
PYW = ROOT / ".build_venv" / "Scripts" / "pythonw.exe"
MAIN = SRC / "main.py"
STDERR_LOG = ROOT / "logs" / "dev_preview_stderr.log"
LOCK_FILE = ROOT / "logs" / "dev_preview.lock"


def _pid_is_launcher(pid: int) -> bool:
    """检查指定 PID 是否仍是一个活着的预览监视器。"""
    try:
        cmd = (
            "Get-CimInstance Win32_Process -Filter \"ProcessId={0}\" "
            "-ErrorAction SilentlyContinue | "
            "Where-Object {{ $_.CommandLine -match 'dev_preview_launcher[.]py' }} | "
            "Select-Object -ExpandProperty ProcessId".format(int(pid))
        )
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", cmd],
            capture_output=True, text=True, timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return r.stdout.strip() != ""
    except Exception:  # noqa: BLE001
        return False


def _acquire_lock() -> bool:
    """单实例锁：已有一个活着的预览监视器时返回 False，避免双击堆积多个监视器。"""
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    if LOCK_FILE.exists():
        try:
            pid = int(LOCK_FILE.read_text(encoding="utf-8").strip())
            if _pid_is_launcher(pid):
                return False
        except (ValueError, OSError):
            pass
    try:
        LOCK_FILE.write_text(str(os.getpid()), encoding="utf-8")
        atexit.register(_release_lock)
        return True
    except OSError:
        return True  # 锁写失败不阻塞启动


def _release_lock():
    try:
        if LOCK_FILE.exists():
            LOCK_FILE.unlink()
    except OSError:
        pass


def _snapshot() -> tuple:
    """返回 (指纹, 文件数)：只统计 src 下 .py（忽略 __pycache__）。"""
    h = hashlib.sha256()
    count = 0
    for p in sorted(SRC.rglob("*.py")):
        if "__pycache__" in p.parts:
            continue
        rel = str(p.relative_to(SRC)).replace("\\", "/")
        st = p.stat()
        h.update(rel.encode("utf-8"))
        h.update(str(st.st_mtime_ns).encode("ascii"))
        h.update(str(st.st_size).encode("ascii"))
        count += 1
    return h.hexdigest(), count


def _launch(selftest: bool = False):
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    if selftest:
        out = Path(tempfile.gettempdir()) / "qbm_dev_selftest.json"
        cmd = [str(PY), str(MAIN), "--selftest", str(out)]
        proc = subprocess.run(cmd, cwd=SRC, env=env)
        if proc.returncode == 0:
            print("SELFTEST_OK", out.read_text(encoding="utf-8")[:300])
        else:
            print("SELFTEST_FAIL", proc.returncode)
        return None
    STDERR_LOG.parent.mkdir(parents=True, exist_ok=True)
    logf = open(STDERR_LOG, "a", encoding="utf-8", errors="replace")
    exe = PYW if PYW.exists() else PY
    proc = subprocess.Popen(
        [str(exe), str(MAIN)],
        cwd=SRC, env=env, stdout=logf, stderr=logf,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return proc


def _tail_stderr(n=20):
    try:
        lines = STDERR_LOG.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(lines[-n:])
    except OSError:
        return "(无错误日志)"


def _kill_tree(proc):
    """结束整个进程树（Windows 必须用 taskkill /T，否则 venv 壳进程的
    真实解释器子进程会变成孤儿继续运行）。"""
    if proc is None or proc.poll() is not None:
        return
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                capture_output=True, timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except Exception:  # noqa: BLE001
            pass
    else:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def _kill_stale_apps():
    """清理历史遗留的预览程序进程（命令行含 src\\main.py 的 python/pythonw）。

    旧版监视器只杀 venv 壳进程，真实解释器可能成为孤儿并占着单实例互斥体，
    导致新启动的预览程序直接退出。dev 工具场景下直接清理是安全的。
    """
    try:
        ps = (
            "Get-CimInstance Win32_Process | "
            "Where-Object { $_.CommandLine -match 'QBotManager[/\\\\]src[/\\\\]main[.]py' } | "
            "Select-Object -ExpandProperty ProcessId"
        )
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True, text=True, timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        for line in (r.stdout or "").split():
            if line.strip().isdigit():
                pid = int(line.strip())
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    capture_output=True, timeout=10,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                print(f"已清理遗留预览进程 (PID {pid})")
    except Exception:  # noqa: BLE001
        pass


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--selftest":
        _launch(selftest=True)
        return 0

    if not _acquire_lock():
        print("已有 AstroSwarm 开发预览监视器在运行，请先关闭旧窗口。")
        return 0

    print("=" * 60)
    print("AstroSwarm 开发预览版（源码直跑）")
    print("源码目录:", SRC)
    print("改代码保存后，程序会在 1 秒内自动重启。")
    print("关闭本窗口或按 Ctrl+C 退出监视（程序也会被结束）。")
    print("=" * 60)

    # 先清掉旧监视器可能遗留的孤儿进程，避免单实例互斥体被占住
    _kill_stale_apps()

    # 提醒：打包版正在运行时避免冲突
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-Process -Name AstroSwarm, QBotManager -ErrorAction SilentlyContinue | "
             "Select-Object -ExpandProperty Id"],
            capture_output=True, text=True, timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if out.stdout.strip():
            print("注意：检测到打包版 AstroSwarm.exe（或旧版 QBotManager.exe）正在运行，请先关闭它，"
                  "否则两个实例可能争用端口/配置。")
    except Exception:  # noqa: BLE001
        pass

    sig, count = _snapshot()
    print(f"已扫描 {count} 个源码文件")
    proc = _launch()
    print(f"预览程序已启动（PID {proc.pid if proc else '?'}）")
    try:
        while True:
            time.sleep(1.0)
            new_sig, _ = _snapshot()
            changed = new_sig != sig
            if proc is not None and proc.poll() is None:
                if changed:
                    sig = new_sig
                    print("\n检测到源码变化，自动重启 ...")
                    _kill_tree(proc)
                    proc = _launch()
                    print(f"已重启（PID {proc.pid}）")
                continue
            # 程序已退出
            code = proc.returncode if proc is not None else 0
            if code == 0:
                print("\n预览程序已正常关闭，监视器退出。")
                return 0
            print(f"\n预览程序异常退出（code={code}），最近错误：\n{_tail_stderr()}")
            print("等待源码变化后自动重启 ...")
            while True:
                time.sleep(1.0)
                new_sig, _ = _snapshot()
                if new_sig != sig:
                    sig = new_sig
                    proc = _launch()
                    print(f"已重新启动（PID {proc.pid}）")
                    break
    except KeyboardInterrupt:
        print("\n正在退出 ...")
        _kill_tree(proc)
    return 0


if __name__ == "__main__":
    sys.exit(main())
