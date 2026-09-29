# -*- coding: utf-8 -*-
"""一键跑项目测试：python tests/run_tests.py（用当前解释器）。"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
env = dict(os.environ)
env["PYTHONUTF8"] = "1"
env["PYTHONIOENCODING"] = "utf-8"
env["QBM_NO_UPDATE"] = "1"  # 测试不联网检查版本
# 指针隔离：测试里的 Settings.save() 会写全局安装指针，
# 不隔离会把预览版指向临时测试根（曾导致"扫码刷新无二维码"）。
ptr_dir = Path(tempfile.mkdtemp(prefix="qbm_test_ptr_"))
env["QBM_POINTER_DIR"] = str(ptr_dir)

failed = False
for script in ("test_core.py", "test_agent_profile.py", "test_plugin_market.py",
               "test_tool_packs.py", "test_cleanup.py",
               "test_liqinghan_plugin.py", "test_chat_archive.py",
               "test_persona_workshop.py", "test_knowledge_base.py",
               "test_ui_smoke.py", "test_press_scale.py"):
    path = root / "tests" / script
    print("== run", script)
    r = subprocess.run([sys.executable, str(path)], cwd=root, env=env)
    if r.returncode != 0:
        failed = True
        print("FAILED:", script)
try:
    ptr_dir.rmdir()  # 测试指针目录应为空（内容在子进程的临时环境里）
except OSError:
    pass
sys.exit(1 if failed else 0)
