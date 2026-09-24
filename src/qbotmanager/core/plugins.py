"""插件安装：商店 pip 安装 / 第三方 zip 解压 / 依赖检测与安装。"""
import re
import zipfile
from pathlib import Path

from .bot import read_plugins, write_plugins
from .process import run_capture
from .python_runtime import ensure_runtime, install_with_fallback

# 第三方 zip 的安全上限（与无头端 console_ext 的安装边界一致）：
# 只看压缩包大小是不够的 —— 0.19MB 的包实测能解出 200MB（约 1000:1），
# 所以必须同时限制成员数与**解压后总体积**，否则一个 zip 就能把磁盘写满。
ZIP_MAX_MEMBERS = 500
ZIP_MAX_TOTAL = 200 * 1024 * 1024      # 解压后总量上限 200MB
ZIP_MAX_SINGLE = 50 * 1024 * 1024      # 单文件上限 50MB


def install_store_plugin(settings, name, log=None, progress=None,
                         module_name=None) -> None:
    """从 PyPI 安装 NoneBot 商店插件（自动装依赖，失败切官方源），并写入 pyproject。

    module_name 可选：NoneBot 官方列表里显式给出的模块名；缺省时按惯例
    把包名中的 - 换成 _（如 nonebot-plugin-status -> nonebot_plugin_status）。
    """
    if not name or not name.strip():
        raise RuntimeError("插件名不能为空")
    name = name.strip()
    install_with_fallback(settings, [name], log=log, progress=progress)
    mod = (module_name or "").strip() or name.replace("-", "_")
    plugins = read_plugins(settings)
    if mod not in plugins:
        plugins.append(mod)
        write_plugins(settings, plugins)
    if log:
        log(f"商店插件已安装并启用: {mod}")


def extract_zip_plugin(settings, zip_path, log=None) -> Path:
    """把第三方插件 zip 解压到 src/plugins，返回解压出的插件目录。"""
    zip_path = Path(zip_path)
    if not zip_path.exists():
        raise RuntimeError("zip 文件不存在: " + str(zip_path))
    settings.plugins_dir.mkdir(parents=True, exist_ok=True)
    root = settings.plugins_dir.resolve()
    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()
        if not names:
            raise RuntimeError("zip 为空")
        members = 0
        total = 0
        for info in z.infolist():
            if info.is_dir():
                continue
            name = info.filename
            members += 1
            if members > ZIP_MAX_MEMBERS:
                raise RuntimeError(f"压缩包成员太多（上限 {ZIP_MAX_MEMBERS} 个）")
            mode = (info.external_attr >> 16) & 0xF000
            if mode == 0xA000:
                raise RuntimeError("zip 含符号链接，已拒绝: " + name)
            pure = Path(name.replace("\\", "/"))
            if pure.is_absolute() or re.match(r"^[A-Za-z]:", name) or ".." in pure.parts:
                raise RuntimeError("zip 包含非法路径: " + name)
            target = (root / pure).resolve()
            if target != root and root not in target.parents:
                raise RuntimeError("zip 包含非法路径: " + name)
            size = int(info.file_size or 0)
            if size > ZIP_MAX_SINGLE:
                raise RuntimeError(f"单个文件过大（{size // 1024 // 1024}MB）: {name}")
            total += size
            if total > ZIP_MAX_TOTAL:
                raise RuntimeError("解压后体积过大（超过 200MB），已拒绝")
        z.extractall(root)
    # 找出解压出的顶层目录
    top = zip_path.name
    if top.lower().endswith(".zip"):
        top = top[:-4]
    candidate = settings.plugins_dir / top
    if candidate.exists() and candidate.is_dir():
        return candidate
    for p in settings.plugins_dir.iterdir():
        if p.is_dir() and p.name != ".gitkeep":
            return p
    if log:
        log("zip 插件已解压到 " + str(settings.plugins_dir))
    return settings.plugins_dir


# ---------------------------------------------------------------- 依赖检测
def _requirements_deps(text: str) -> list:
    deps = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        line = re.split(r"\s+#", line, maxsplit=1)[0].strip()
        if line:
            deps.append(line)
    return deps


def _pyproject_deps(text: str) -> list:
    """解析 pyproject.toml 的 [project].dependencies（优先 tomllib，失败正则兜底）。"""
    try:
        import tomllib
        data = tomllib.loads(text)
        deps = data.get("project", {}).get("dependencies") or []
        return [d for d in deps if isinstance(d, str) and d.strip()]
    except Exception:  # noqa: BLE001
        pass
    m = re.search(r"\[project\](.*?)(\n\[[^\]]+\]|\Z)", text, re.S)
    if not m:
        return []
    dm = re.search(r"dependencies\s*=\s*\[(.*?)\]", m.group(1), re.S)
    if not dm:
        return []
    raw = dm.group(1)
    parts = raw.splitlines() if "\n" in raw else raw.split(",")
    deps = []
    for part in parts:
        item = part.strip().rstrip(",").strip("'\"").strip()
        if item:
            deps.append(item)
    return deps


def _dedupe_deps(deps) -> list:
    seen = set()
    out = []
    for d in deps:
        key = d.strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(d.strip())
    return out


def detect_dependencies_from_zip(zip_path) -> list:
    """扫描 zip 内的 requirements.txt / pyproject.toml，返回去重后的依赖列表。"""
    zip_path = Path(zip_path)
    deps = []
    if not zip_path.exists():
        return deps
    with zipfile.ZipFile(zip_path) as z:
        for n in z.namelist():
            low = n.lower()
            if not (low.endswith("requirements.txt") or low.endswith("pyproject.toml")):
                continue
            text = z.read(n).decode("utf-8", errors="replace")
            if low.endswith("pyproject.toml"):
                deps += _pyproject_deps(text)
            else:
                deps += _requirements_deps(text)
    return _dedupe_deps(deps)


def detect_dependencies_from_dir(plugin_dir) -> list:
    """扫描已解压插件目录里的 requirements.txt / pyproject.toml。"""
    plugin_dir = Path(plugin_dir)
    deps = []
    req = plugin_dir / "requirements.txt"
    if req.exists():
        deps += _requirements_deps(req.read_text(encoding="utf-8", errors="replace"))
    pf = plugin_dir / "pyproject.toml"
    if pf.exists():
        deps += _pyproject_deps(pf.read_text(encoding="utf-8", errors="replace"))
    return _dedupe_deps(deps)


def _dep_package_name(dep: str) -> str:
    """从依赖说明里取出包名（nonebot2[fastapi]>=2.0.0; python_version<"3.11" -> nonebot2）。"""
    return re.split(r"[<>=!~;\[(]", dep.strip())[0].strip()


def missing_dependencies(settings, deps, log=None, on_progress=None, cancel_event=None) -> list:
    """用运行时 pip show 判断哪些依赖未安装（返回缺失的原始依赖描述）。

    on_progress(done, total, dep) 可选，供 UI 实时显示检查进度；cancel_event 支持取消。
    """
    if not deps:
        return []
    py = ensure_runtime(settings, log=log, cancel_event=cancel_event)
    missing = []
    for i, dep in enumerate(deps, 1):
        if cancel_event is not None and cancel_event.is_set():
            from .exceptions import CancelledError
            raise CancelledError("依赖检查已取消")
        name = _dep_package_name(dep)
        if not name:
            continue
        if on_progress:
            on_progress(i, len(deps), dep)
        try:
            rc, _ = run_capture([str(py), "-m", "pip", "show", name], timeout=60)
        except Exception:  # noqa: BLE001
            rc = 1
        if rc != 0:
            missing.append(dep)
    return missing


def list_store_plugins(settings) -> list:
    """返回 pyproject 中 pip 安装的商店插件（过滤本地目录/文件写法）。"""
    out = []
    for name in read_plugins(settings):
        name = str(name or "").strip()
        if not name:
            continue
        if name.startswith("@") or name.startswith("."):
            continue
        if name.endswith(".py") or "." in name or "/" in name or "\\" in name:
            continue
        if name not in out:
            out.append(name)
    return out


def list_local_plugins(settings) -> list:
    """列出 src/plugins 下的目录。"""
    if not settings.plugins_dir.exists():
        return []
    return sorted(p.name for p in settings.plugins_dir.iterdir()
                  if p.is_dir() and p.name != "__pycache__")
