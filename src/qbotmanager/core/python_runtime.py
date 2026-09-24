"""Python 运行时：优先复用系统 Python（创建独立 venv），否则回退官方 embeddable 精简版。"""
import os
import re
import shutil
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

from ..constants import GET_PIP_URLS, PYTHON_EMBED_URLS
from .net import download
from .process import run_capture, run_stream

MIN_PYTHON = (3, 10)


def _pth_name(version: str) -> str:
    parts = version.split(".")
    return f"python{parts[0]}{parts[1]}._pth"


def _fetch_text(url: str, timeout: int = 90) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (AstroSwarm)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def _latest_wheel_url(index_url: str, package: str) -> str:
    """从 PEP 503 simple index 解析某包最新的 py3-none-any wheel 地址。"""
    base = index_url.rstrip("/") + "/"
    html = _fetch_text(base + package + "/")
    pattern = re.compile(
        'href="([^"]*' + re.escape(package) + r'-(\d+(?:\.\d+)+)-py3-none-any\.whl[^"]*)"'
    )
    best_url = None
    best_key = None
    for m in pattern.finditer(html):
        ver = tuple(int(x) for x in m.group(2).split("."))
        if best_key is None or ver > best_key:
            best_key = ver
            best_url = urllib.parse.urljoin(base, m.group(1))
    if not best_url:
        raise RuntimeError(f"在 {index_url} 找不到 {package} 的 wheel")
    return best_url


def _bootstrap_pip(settings, exe: Path, log=None, cancel_event=None) -> None:
    """用 pip/setuptools 的 wheel 直接解压进 site-packages，免 get-pip。"""
    sp = exe.parent / "Lib" / "site-packages"
    sp.mkdir(parents=True, exist_ok=True)
    index = settings.pip_index or "https://pypi.org/simple"
    if log:
        log("下载并安装 pip（wheel 方式）...")
    for pkg in ("setuptools", "pip"):
        wheel_url = _latest_wheel_url(index, pkg)
        wheel_path = settings.downloads_dir / f"{pkg}.whl"
        download(wheel_url, wheel_path, timeout=300, cancel_event=cancel_event)
        with zipfile.ZipFile(wheel_path) as z:
            z.extractall(sp)
        try:
            wheel_path.unlink()
        except OSError:
            pass
    rc, out = run_capture([str(exe), "-m", "pip", "--version"], timeout=120)
    if rc != 0:
        raise RuntimeError(f"pip 引导失败: {out[-400:]}")


# ---------------------------------------------------------------- 版本探测
def py_version(exe: Path):
    """返回 (major, minor) 元组；无法执行返回 None。"""
    try:
        rc, out = run_capture([str(exe), "-c", "import sys; print('%d.%d' % sys.version_info[:2])"], timeout=30)
        if rc == 0:
            parts = out.strip().split(".")[:2]
            if len(parts) == 2:
                return (int(parts[0]), int(parts[1]))
    except Exception:  # noqa: BLE001
        pass
    return None


def _is_venv_python(exe: Path) -> bool:
    """判断 python.exe 是否位于某个虚拟环境（Scripts 目录）。"""
    parent = exe.parent
    if parent.name.lower() == "scripts":
        if (parent.parent / "pyvenv.cfg").exists():
            return True
    return False


def _usable(exe: Path) -> bool:
    if not exe.exists():
        return False
    ver = py_version(exe)
    return ver is not None and ver >= MIN_PYTHON


def find_system_python(log=None) -> Path | None:
    """按优先级探测系统安装的 Python 3.10+，返回可用的 python.exe。"""
    candidates = []  # (version, path)
    seen = set()

    # 1) py 启动器（注册过的安装）
    py_launcher = shutil.which("py")
    if py_launcher:
        rc, out = run_capture([py_launcher, "-0p"], timeout=30)
        if rc == 0:
            for line in out.splitlines():
                m = re.search(r"(-?\s*)(\d+\.\d+)\s+\*?\s*(\S+python\.exe)", line)
                if m:
                    try:
                        ver = tuple(int(x) for x in m.group(2).split("."))
                    except ValueError:
                        continue
                    p = Path(m.group(3).strip('"'))
                    if p.exists():
                        candidates.append((ver, p))

    # 2) PATH 中的 python
    for name in ("python", "python3"):
        w = shutil.which(name)
        if w:
            p = Path(w)
            if p.name.lower() == "python.exe" and not _is_venv_python(p):
                candidates.append((py_version(p) or (0, 0), p))

    # 3) 常见安装目录
    roots = []
    lap = os.environ.get("LOCALAPPDATA")
    if lap:
        roots.append(Path(lap) / "Programs" / "Python")
    pf = os.environ.get("ProgramFiles")
    if pf:
        roots.append(Path(pf) / "Python")
    pfx = os.environ.get("ProgramFiles(x86)")
    if pfx:
        roots.append(Path(pfx) / "Python")
    for drive in ("C:\\", "D:\\"):
        if os.path.exists(drive):
            roots.append(Path(drive) / "Python")
    for root in roots:
        if not root.exists():
            continue
        for p in sorted(root.glob("Python*/python.exe")):
            if _is_venv_python(p):
                continue
            candidates.append((py_version(p) or (0, 0), p))

    best = None
    for ver, p in candidates:
        key = str(p).lower()
        if key in seen:
            continue
        seen.add(key)
        if ver >= MIN_PYTHON:
            if best is None or ver > best[0]:
                best = (ver, p)
    if best:
        if log:
            log(f"检测到系统 Python {best[0][0]}.{best[0][1]}: {best[1]}")
        return best[1]
    return None


def _create_venv(settings, sys_py: Path, log=None) -> Path:
    """用系统 Python 在 bot/.venv 创建独立虚拟环境并确保 pip 可用。"""
    venv_py = settings.venv_python
    venv_root = venv_py.parent.parent
    venv_root.mkdir(parents=True, exist_ok=True)
    if log:
        log(f"正在用系统 Python 创建独立虚拟环境: {venv_root} ...")
    rc, out = run_capture([str(sys_py), "-m", "venv", str(venv_root)], timeout=300)
    if rc != 0:
        raise RuntimeError(f"创建虚拟环境失败: {out[-500:]}")
    if not venv_py.exists():
        raise RuntimeError("虚拟环境创建后未找到 python.exe")

    rc, out = run_capture([str(venv_py), "-m", "pip", "--version"], timeout=60)
    if rc == 0:
        return venv_py
    if log:
        log("虚拟环境缺少 pip，尝试 ensurepip ...")
    rc, out = run_capture([str(venv_py), "-m", "ensurepip", "--upgrade"], timeout=180)
    if rc == 0:
        rc, out = run_capture([str(venv_py), "-m", "pip", "--version"], timeout=60)
        if rc == 0:
            return venv_py
    # 最后手段：get-pip.py
    if log:
        log("正在使用 get-pip.py 引导 pip ...")
    last_err = None
    for url in GET_PIP_URLS:
        try:
            script = settings.downloads_dir / "get-pip.py"
            script.parent.mkdir(parents=True, exist_ok=True)
            download(url, script, timeout=300)
            rc, out = run_capture([str(venv_py), str(script)], timeout=600)
            if rc == 0:
                return venv_py
            last_err = out[-300:]
        except Exception as e:  # noqa: BLE001
            last_err = e
    raise RuntimeError(f"虚拟环境 pip 不可用: {last_err}")


def _deploy_embedded(settings, progress=None, log=None, cancel_event=None) -> Path:
    """下载并解压 embeddable Python 到根目录/python，启用 site-packages 并引导 pip。"""
    exe = settings.python_dir / "python.exe"
    settings.python_dir.mkdir(parents=True, exist_ok=True)
    ver = settings.python_version
    if log:
        log(f"未检测到可用的系统 Python，准备内置 Python {ver}（免安装精简版）...")
    zip_path = settings.downloads_dir / f"python-{ver}-embed-amd64.zip"
    if not zip_path.exists():
        if log:
            log("下载 Python 运行时 ...")
        last_err = None
        for url_tpl in PYTHON_EMBED_URLS:
            url = url_tpl.format(v=ver)
            try:
                download(url, zip_path, progress=progress)
                break
            except Exception as e:  # noqa: BLE001
                last_err = e
        else:
            raise RuntimeError(f"Python 运行时下载失败: {last_err}")

    if log:
        log("解压 Python 运行时 ...")
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(settings.python_dir)

    # 启用 site-packages（embeddable 默认关闭）
    pth = settings.python_dir / _pth_name(ver)
    if pth.exists():
        lines = pth.read_text(encoding="utf-8").splitlines()
        lines = ["import site" if ln.strip() == "#import site" else ln for ln in lines]
        pth.write_text("\n".join(lines) + "\n", encoding="utf-8")

    if not exe.exists():
        raise RuntimeError(f"Python 运行时解压后未找到 {exe}")

    _bootstrap_pip(settings, exe, log=log, cancel_event=cancel_event)
    if log:
        log("Python 运行时就绪: " + str(exe))
    return exe


def ensure_python(settings, progress=None, log=None, cancel_event=None) -> Path:
    """确保 Python 运行时可用，返回 python.exe 路径。

    优先级：
    1. 已保存/指定的运行时（settings.python_exe）
    2. 已存在的虚拟环境 bot/.venv
    3. 已部署的内置 embeddable
    4. 系统安装的 Python 3.10+（为其创建独立 venv，不污染系统）
    5. 下载内置 embeddable
    """
    # 1) 已保存的运行时
    if getattr(settings, "_python_exe", ""):
        py = Path(settings._python_exe)
        if _usable(py):
            return py
        # 路径存在但验证暂时失败（如瞬时错误）时不清空持久化配置，
        # 避免一次误判把 settings.json 里的 python_exe 抹成空字符串
        if not py.exists():
            settings._python_exe = ""
            settings.python_source = ""
            settings.save()

    # 2) 已有虚拟环境
    venv_py = settings.venv_python
    if _usable(venv_py):
        rc, _ = run_capture([str(venv_py), "-m", "pip", "--version"], timeout=60)
        if rc == 0:
            settings.python_exe = str(venv_py)
            settings.python_source = settings.python_source or "venv"
            settings.save()
            return venv_py

    # 3) 已部署的内置 embeddable
    embedded = settings.python_dir / "python.exe"
    if embedded.exists() and (embedded.parent / "Lib" / "site-packages" / "pip").exists():
        settings.python_exe = str(embedded)
        settings.python_source = "embedded"
        settings.save()
        return embedded

    # 4) 系统 Python -> 独立 venv
    sys_py = find_system_python(log=log)
    if sys_py is not None:
        venv_py = _create_venv(settings, sys_py, log=log)
        settings.python_exe = str(venv_py)
        settings.python_source = "system"
        settings.save()
        if log:
            log("Python 运行时就绪（复用系统 Python 的独立虚拟环境）: " + str(venv_py))
        return venv_py

    # 5) 内置 embeddable
    exe = _deploy_embedded(settings, progress=progress, log=log, cancel_event=cancel_event)
    settings.python_exe = str(exe)
    settings.python_source = "embedded"
    settings.save()
    return exe


def ensure_runtime(settings, log=None, cancel_event=None) -> Path:
    """确保 Python 运行时可用（返回 python.exe）。"""
    return ensure_python(settings, log=log, cancel_event=cancel_event)


def pip_args(settings):
    args = []
    if settings.pip_index:
        args += ["-i", settings.pip_index]
    return args


def install_packages(settings, packages, log=None, progress=None, direct=False,
                     index=None, cancel_event=None) -> None:
    """用运行时 pip 安装包（流式输出，可实时回传进度）。

    index 指定时强制使用该源；否则按 settings.pip_index；direct=True 时不使用任何镜像源。
    progress 回调约定：
      progress(-1)   -> 阶段切换 / 无百分比信息（UI 显示忙碌进度条）
      progress(0-100) -> 下载阶段百分比
    """
    py = ensure_runtime(settings, log=log)
    if log:
        log("安装依赖: " + ", ".join(packages))
    if progress:
        progress(-1)

    def _on_line(line):
        if log:
            log(line)
        if progress:
            m = re.search(r"(\d+)%", line)
            if m:
                try:
                    progress(min(100, max(0, int(m.group(1)))))
                    return
                except ValueError:
                    pass
            if "Installing collected packages" in line:
                progress(-1)

    cmd = [str(py), "-m", "pip", "install", "--upgrade"]
    if index is not None:
        cmd += ["-i", index]
    elif not direct:
        cmd += pip_args(settings)
    cmd += packages
    rc, out = run_stream(
        cmd,
        timeout=1800,
        on_line=_on_line,
    )
    if progress and rc == 0:
        progress(100)
    if rc != 0:
        raise RuntimeError(f"安装依赖失败: {out[-800:]}")



class DependencyInstallError(RuntimeError):
    """依赖安装失败（镜像源与官方源都失败），带失败原因分类。"""

    def __init__(self, packages, reason, detail):
        super().__init__(detail)
        self.packages = list(packages)
        self.reason = reason  # "network" | "other"


NET_ERROR_HINTS = (
    "timeout", "timed out", "read timed", "connect timed", "connectionerror",
    "connection refused", "connection reset", "network is unreachable",
    "proxyerror", "cannot connect", "ssl", "certificate verify",
    "could not resolve", "name resolution", "getaddrinfo", "temporary failure",
    "nodename nor servname", "retries exceeded", "403 forbidden", "401 unauthorized",
)


def classify_pip_error(text: str) -> str:
    """把 pip 报错粗略归类：网络原因('network') 或其他原因('other')。"""
    low = (text or "").lower()
    for kw in NET_ERROR_HINTS:
        if kw in low:
            return "network"
    return "other"


FALLBACK_INDEXES = (
    "https://mirrors.aliyun.com/pypi/simple/",
    "https://pypi.org/simple",
)


def install_with_fallback(settings, packages, log=None, progress=None, cancel_event=None) -> None:
    """安装依赖：按顺序尝试 配置的镜像源（默认清华）-> 阿里云镜像 -> 官方 PyPI。

    全部失败时抛出 DependencyInstallError（含失败原因分类，便于 UI 提示挂代理重试）。
    """
    if not packages:
        return
    configured = (settings.pip_index or "").rstrip("/") or "https://pypi.org/simple"
    order = []
    for idx in (configured, *FALLBACK_INDEXES):
        key = idx.rstrip("/")
        if key not in order:
            order.append(key)
    errors = []
    for i, idx in enumerate(order):
        try:
            install_packages(settings, packages, log=log, progress=progress,
                             index=idx, cancel_event=cancel_event)
            return
        except Exception as e:  # noqa: BLE001
            errors.append(f"[{idx}] {e}")
            if i < len(order) - 1 and log:
                log("当前源安装失败，自动切换备用源重试 ...")
    detail = "\n".join(errors)
    raise DependencyInstallError(packages, classify_pip_error(detail), detail)
