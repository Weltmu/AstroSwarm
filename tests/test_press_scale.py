# -*- coding: utf-8 -*-
"""按钮按压缩放反馈测试：鼠标按压缩小、松开回弹、键盘空格同样生效。"""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

from qbotmanager.ui import press_scale  # noqa: E402,F401


def _pump(app, duration_ms: int):
    start = time.monotonic()
    while (time.monotonic() - start) < duration_ms / 1000:
        app.processEvents()
        time.sleep(0.01)


def test_press_scale_feedback():
    app = QApplication.instance() or QApplication([])
    btn = QPushButton("测试按钮")
    btn.resize(140, 44)
    btn.show()
    app.processEvents()
    assert getattr(btn, "_press_scale", 1.0) == 1.0

    # 鼠标按下 -> 缩小；绘制路径不崩
    QTest.mousePress(btn, Qt.LeftButton)
    _pump(app, 160)
    assert getattr(btn, "_press_scale", 1.0) <= 0.97
    assert not btn.grab().isNull()

    # 松开 -> 回弹到 1.0
    QTest.mouseRelease(btn, Qt.LeftButton)
    _pump(app, 320)
    assert abs(getattr(btn, "_press_scale", 1.0) - 1.0) < 0.02

    # 键盘空格按下/松开同样触发
    btn.setFocus()
    QTest.keyPress(btn, Qt.Key_Space)
    _pump(app, 160)
    assert getattr(btn, "_press_scale", 1.0) <= 0.97
    QTest.keyRelease(btn, Qt.Key_Space)
    _pump(app, 320)
    assert abs(getattr(btn, "_press_scale", 1.0) - 1.0) < 0.02

    btn.close()
    print("OK press_scale")


if __name__ == "__main__":
    test_press_scale_feedback()
