# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

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
    ('.build_venv/Lib/site-packages/PySide6/qml/Qt5Compat', 'PySide6/qml/Qt5Compat'),
    ('.build_venv/Lib/site-packages/PySide6/qml/QtMultimedia', 'PySide6/qml/QtMultimedia'),
    ('.build_venv/Lib/site-packages/PySide6/qml/QtQuick', 'PySide6/qml/QtQuick'),
    ('.build_venv/Lib/site-packages/PySide6/qml/QtQml', 'PySide6/qml/QtQml'),
    ('.build_venv/Lib/site-packages/PySide6/plugins/multimedia', 'PySide6/plugins/multimedia'),
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
