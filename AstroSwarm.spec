# -*- mode: python ; coding: utf-8 -*-
import os

from PyInstaller.utils.hooks import collect_all

# QML 与 Qt 插件必须跟「当前构建环境」里的 PySide6 走。
# 这里曾经写死 `.build_venv/Lib/site-packages/PySide6/...`，而那个 venv 是 PySide6 6.8.3
# 的残骸（连 python.exe 都没有），于是 6.8 的 QML / 多媒体插件被混进 6.11 的包里，
# 打出来的 exe 一启动就 "DLL load failed while importing QtCore: 找不到指定的程序"。
_PYSIDE = os.path.dirname(__import__("PySide6").__file__)

datas = [
    ('src/qbotmanager/ui/bg.qml', 'qbotmanager/ui'),
    ('src/qbotmanager/ui/bg.qml', '.'),
      ('src/qbotmanager/assets/fonts', 'qbotmanager/assets/fonts'),
      ('src/qbotmanager/assets/agreements', 'qbotmanager/assets/agreements'),
      ('src/qbotmanager/assets/plans.json', 'qbotmanager/assets'),
      ('src/qbotmanager/assets/wizard_bg.jpg', 'qbotmanager/assets'),
    ('src/qbotmanager/assets/plugins/nonebot_adapter_ilink', 'qbotmanager/assets/plugins/nonebot_adapter_ilink'),
    ('src/qbotmanager/assets/plugins/ai', 'qbotmanager/assets/plugins/ai'),
    ('src/qbotmanager/assets/plugins/liqinghan', 'qbotmanager/assets/plugins/liqinghan'),
    ('src/qbotmanager/assets/plugins/qbm_bridge_client', 'qbotmanager/assets/plugins/qbm_bridge_client'),
    ('src/qbotmanager/core/agent', 'qbotmanager/core/agent'),
    # 打包版 AgentRuntime 源码副本（qbotmanager 模块在 PYZ，无法从磁盘读；放 appr/ 下由 ensure_agent_runtime 拷贝）
    ('src/qbotmanager/__init__.py', 'appr/qbotmanager'),
    ('src/qbotmanager/core/__init__.py', 'appr/qbotmanager/core'),
    ('src/qbotmanager/core/knowledge_base.py', 'appr/qbotmanager/core'),
    ('src/qbotmanager/core/agent', 'appr/qbotmanager/core/agent'),
    ('src/qbotmanager/assets/dsh_plugins', 'qbotmanager/assets/dsh_plugins'),
    ('src/qbotmanager/assets/llbot_tutorial', 'qbotmanager/assets/llbot_tutorial'),
    ('src/qbotmanager/assets/persona_template', 'qbotmanager/assets/persona_template'),
    (os.path.join(_PYSIDE, 'qml', 'Qt5Compat'), 'PySide6/qml/Qt5Compat'),
    (os.path.join(_PYSIDE, 'qml', 'QtMultimedia'), 'PySide6/qml/QtMultimedia'),
    (os.path.join(_PYSIDE, 'qml', 'QtQuick'), 'PySide6/qml/QtQuick'),
    (os.path.join(_PYSIDE, 'qml', 'QtQml'), 'PySide6/qml/QtQml'),
    (os.path.join(_PYSIDE, 'plugins', 'multimedia'), 'PySide6/plugins/multimedia'),
]
binaries = []
hiddenimports = ['_cffi_backend']

for _pkg in (
    'PySide6.QtMultimedia',
    'PySide6.QtMultimediaWidgets',
    'PySide6.QtQml',
    'PySide6.QtQuick',
    'pynacl',
    'nacl',
    'cffi',
):
    _d, _b, _h = collect_all(_pkg)
    datas += _d
    binaries += _b
    hiddenimports += _h

a = Analysis(
    ['src/main.py'],
    pathex=['src'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

# ---- 剔掉「构建机污染」的 DLL（这次发版踩的坑就在这里）----
# PyInstaller 会顺着 PATH 把构建机上装的东西卷进包里。这台机器上 Codex 运行时缓存
# （构建机上装着的 Codex 运行时缓存里的 poppler 与 libheif）就被卷进来过，后果是包里多出一个
# 顶层的 icuuc.dll（ICU 78，poppler 带来的）+ icudt78.dll（33MB）。
# 而 PySide6 的 Qt6Core.dll 要的是 Windows 自带的 icuuc.dll，被顶层这个顶掉之后，
# 用户机一启动就报 "ImportError: DLL load failed while importing QtCore: 找不到指定的程序"。
# 这些 DLL 跟星群没有任何关系，另外 ucrtbase.dll / api-ms-win-*.dll 这类系统垫片也一律不进包。
def _is_host_junk(dest, src):
    s = str(src or "").replace("/", "\\").lower()
    base = str(dest or "").replace("/", "\\").lower().rsplit("\\", 1)[-1]
    if "codex-runtimes" in s:
        return True
    if base == "ucrtbase.dll" or base.startswith("api-ms-win-"):
        return True
    return False


_keep, _junk = [], []
for _t in a.binaries:
    (_junk if _is_host_junk(_t[0], _t[1]) else _keep).append(_t)
a.binaries = _keep
if _junk:
    print("[spec] 剔除构建机污染 DLL %d 个: %s" % (len(_junk), sorted({t[0] for t in _junk})))

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='AstroSwarm',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='D:/ai/QBotManager/assets/logo.ico',
)
