# -*- coding: utf-8 -*-
"""给宣传片截真实客户端界面（离屏渲染，不弹窗）。"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["QBM_NO_UPDATE"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from qbotmanager.core.manager import Manager
from qbotmanager.core.settings import Settings
from qbotmanager.tasks.task_manager import TaskManager
from qbotmanager.ui.main_window import MainWindow

OUT = Path(r"D:\ai\AstroSwarm-宣传视频\assets\ui")
OUT.mkdir(parents=True, exist_ok=True)

PAGES = [
    ("首页", "home"),
    ("插件工坊", "workshop"),
    ("AI 大脑", "brain"),
    ("插件", "plugins"),
    ("QQ", "qq"),
    ("消息中心", "console"),
]

app = QApplication(sys.argv)
tmp = Path(tempfile.mkdtemp(prefix="qbm_shots_"))
s = Settings(tmp)
s.ensure_dirs()
s.bg_video_enabled = False
s.bg_image_enabled = False
# 演示用：给「插件工坊」写一份配置，截图里就不会出现"还没配置模型"的警告条
import json
_ws = Path(s.root) / "workshop"
_ws.mkdir(parents=True, exist_ok=True)
(_ws / "config.json").write_text(json.dumps({"provider": "deepseek", "api_url": "https://api.deepseek.com", "api_key": "sk-demo-0000000000", "model": "deepseek-chat"}, ensure_ascii=False), encoding="utf-8")
tasks = TaskManager()
win = MainWindow(s, tasks)
win.resize(1600, 1000)
win.show()

state = {"i": 0}


def step():
    i = state["i"]
    if i >= len(PAGES):
        app.quit()
        return
    name, slug = PAGES[i]
    try:
        win.switch_page(name)
    except Exception as exc:  # noqa: BLE001
        print("switch failed:", name, exc)
    for _ in range(8):
        app.processEvents()
    path = OUT / (slug + ".png")
    ok = win.grab().save(str(path))
    print("saved", slug, ok, win.width(), "x", win.height())
    state["i"] = i + 1
    QTimer.singleShot(150, step)


QTimer.singleShot(600, step)
app.exec()
print("SHOTS_DONE")