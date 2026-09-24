import os
import subprocess
import threading
import time
import ctypes
from ctypes import wintypes
from pathlib import Path

# ---------------------------------------------------------------------------
# Windows 退出作业（Job Object）：GUI 进程专用。
# 把程序拉起的每个子进程都放进一个 KILL_ON_JOB_CLOSE 作业，
# 程序进程退出（含崩溃、被结束）时 Windows 自动终止作业内全部子进程，
# 从系统层面兜底"关闭程序不残留机器人/安装器等子进程"。
# CLI（--cli start）不启用，保留"命令行启动后服务留后台"的既有行为。
# ---------------------------------------------------------------------------
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_job_handle = None
_job_enabled = False


class _IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_ulonglong),
        ("WriteOperationCount", ctypes.c_ulonglong),
        ("OtherOperationCount", ctypes.c_ulonglong),
        ("ReadTransferCount", ctypes.c_ulonglong),
        ("WriteTransferCount", ctypes.c_ulonglong),
        ("OtherTransferCount", ctypes.c_ulonglong),
    ]


class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
        ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", _IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class _PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.POINTER(wintypes.ULONG)),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", ctypes.c_wchar * 260),
    ]


def install_exit_job():
    """在 GUI 进程创建 KILL_ON_JOB_CLOSE 作业（进程内只需调用一次）。"""
    global _job_handle, _job_enabled
    _job_enabled = True
    if os.name != "nt" or _job_handle is not None:
        return
    try:
        job = ctypes.windll.kernel32.CreateJobObjectW(None, None)
        if not job:
            return
        info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        ok = ctypes.windll.kernel32.SetInformationJobObject(
            job,
            _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(info),
            ctypes.sizeof(info),
        )
        if not ok:
            ctypes.windll.kernel32.CloseHandle(job)
            return
        _job_handle = job
    except Exception:  # noqa: BLE001
        _job_handle = None


def _assign_to_job(proc):
    """把刚拉起的子进程放入退出作业；失败静默，不阻塞业务。

    venv 的 python.exe 是个"壳"，Popen 返回后它才会拉起真实解释器，
    因此还要在后台短暂扫描几秒，把后出现的后代也补进作业，
    否则真实解释器会漏出作业，程序退出后变成孤儿。
    """
    if os.name != "nt" or not _job_enabled or _job_handle is None:
        return
    try:
        ctypes.windll.kernel32.AssignProcessToJobObject(
            _job_handle, ctypes.c_void_p(int(proc._handle)))
    except Exception:  # noqa: BLE001
        pass

    def _sweep():
        deadline = time.time() + 5.0
        seen = set()
        while time.time() < deadline:
            try:
                children = _descendants(proc.pid)
            except Exception:  # noqa: BLE001
                children = []
            for child in children:
                if child and child not in seen:
                    seen.add(child)
                    _assign_pid(child)
            time.sleep(0.2)

    threading.Thread(
        target=_sweep, daemon=True, name="job-sweep",
    ).start()


def _assign_pid(pid, via_pid=None):
    """按 PID 把进程加入退出作业（venv 真实解释器等后代）。"""
    if os.name != "nt" or not _job_enabled or _job_handle is None:
        return
    PROCESS_SET_QUOTA = 0x0100
    PROCESS_TERMINATE = 0x0001
    h = ctypes.windll.kernel32.OpenProcess(
        PROCESS_SET_QUOTA | PROCESS_TERMINATE, False, int(pid))
    if not h:
        return
    try:
        ctypes.windll.kernel32.AssignProcessToJobObject(
            _job_handle, ctypes.c_void_p(h))
    except Exception:  # noqa: BLE001
        pass
    finally:
        ctypes.windll.kernel32.CloseHandle(h)


def _descendants(pid):
    """用 Toolhelp32 快照返回 pid 的所有后代 PID（含孙进程）。"""
    TH32CS_SNAPPROCESS = 0x2
    kernel32 = ctypes.windll.kernel32
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if int(snap) in (-1, 0xFFFFFFFF):
        return []
    try:
        entry = _PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(_PROCESSENTRY32W)
        parent_map = {}
        if kernel32.Process32FirstW(snap, ctypes.byref(entry)):
            while True:
                parent_map[int(entry.th32ProcessID)] = int(entry.th32ParentProcessID)
                if not kernel32.Process32NextW(snap, ctypes.byref(entry)):
                    break
        result = []
        stack = [int(pid)]
        while stack:
            cur = stack.pop()
            for child, parent in parent_map.items():
                if parent == cur:
                    result.append(child)
                    stack.append(child)
        return result
    finally:
        kernel32.CloseHandle(snap)


def start_process(cmd, cwd=None, on_line=None, env=None, log_file=None):
    """启动一个子进程，输出写入日志文件并实时回传给 on_line。

    关键点：子进程 stdout/stderr 重定向到日志文件而不是管道，
    这样父进程（管理器/CLI）退出后子进程不会因管道关闭而崩溃，
    从而支持“关闭管理器、服务留在后台继续运行”。
    返回 Popen 对象。Windows 下隐藏控制台窗口。
    """
    if log_file is None:
        import tempfile
        log_file = os.path.join(tempfile.gettempdir(), "qbotmanager_proc.log")
    Path(log_file).parent.mkdir(parents=True, exist_ok=True)
    out_handle = open(log_file, "a", encoding="utf-8", errors="replace")

    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NO_WINDOW
    merged_env = dict(os.environ)
    if env:
        merged_env.update(env)
    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd) if cwd else None,
        stdout=out_handle,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        creationflags=creationflags,
        env=merged_env,
    )
    _assign_to_job(proc)

    if on_line:
        def _reader():
            try:
                with open(log_file, "r", encoding="utf-8", errors="replace") as rf:
                    rf.seek(0, os.SEEK_END)
                    while True:
                        line = rf.readline()
                        if line:
                            line = line.rstrip("\r\n")
                            if line:
                                on_line(line)
                        elif proc.poll() is None:
                            time.sleep(0.1)
                        else:
                            break
            except (ValueError, OSError):
                pass

        threading.Thread(target=_reader, daemon=True, name="proc-reader").start()
    return proc


def stop_process_tree(proc, timeout=15):
    """终止进程及其子进程树（Windows 用 taskkill，带超时保护）。"""
    if proc is None:
        return
    if proc.poll() is not None:
        return
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                capture_output=True, timeout=timeout,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception:  # noqa: BLE001
            try:
                proc.kill()
            except OSError:
                pass
    else:
        try:
            proc.terminate()
        except OSError:
            pass


def run_stream(cmd, cwd=None, timeout=None, env=None, on_line=None, cancel_event=None):
    """流式执行命令：实时把每行输出回传给 on_line，返回 (returncode, 尾部输出)。

    适合 pip 安装这类耗时命令，让 UI 能实时展示进度；进程仍在运行时保持
    on_line 被调用，不会像 run_capture 一样等到结束才一次性返回。
    cancel_event 置位时 kill 子进程并返回 (-2, ...)。
    """
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NO_WINDOW
    merged_env = dict(os.environ)
    if env:
        merged_env.update(env)
    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=creationflags,
        env=merged_env,
    )
    _assign_to_job(proc)

    lines = []

    def _reader():
        try:
            for raw in proc.stdout:
                line = raw.rstrip("\r\n")
                if line:
                    lines.append(line)
                    if len(lines) > 40:
                        lines.pop(0)
                    if on_line:
                        on_line(line)
        except (ValueError, OSError):
            pass

    t = threading.Thread(target=_reader, daemon=True, name="proc-stream-reader")
    t.start()

    deadline = time.time() + (timeout if timeout else 1800)
    cancelled = False
    while proc.poll() is None and time.time() < deadline:
        if cancel_event is not None and cancel_event.is_set():
            cancelled = True
            try:
                proc.kill()
            except OSError:
                pass
            break
        time.sleep(0.2)
    if proc.poll() is None and not cancelled and time.time() >= deadline:
        proc.kill()
        lines.append("[timeout]")
    elif cancelled:
        lines.append("[cancelled]")
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        pass
    return (-2 if cancelled else proc.returncode), "\n".join(lines)


def run_capture(cmd, cwd=None, timeout=None, env=None):
    """同步执行命令，返回 (returncode, 合并输出)。"""
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NO_WINDOW
    merged_env = dict(os.environ)
    if env:
        merged_env.update(env)
    proc = subprocess.Popen(
        cmd, cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace",
        creationflags=creationflags, env=merged_env,
    )
    _assign_to_job(proc)
    try:
        out, err = proc.communicate(timeout=timeout)
        return proc.returncode, (out or "") + (err or "")
    except subprocess.TimeoutExpired:
        try:
            proc.kill()
        except OSError:
            pass
        try:
            out, err = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            out, err = "", ""
        return -1, (out or "") + (err or "") + "\n[timeout]"
