# -*- coding: utf-8 -*-
"""UI 冒烟：无头渲染验证按钮可见、窗口缩放逻辑、布局自适应（不弹窗）。"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["QBM_NO_UPDATE"] = "1"

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtCore import QPoint, QTimer
from PySide6.QtWidgets import QApplication, QPushButton, QScrollArea, QVBoxLayout, QWidget

from qbotmanager.core.manager import Manager
from qbotmanager.core.settings import Settings
from qbotmanager.tasks.task_manager import TaskManager
from qbotmanager.ui.main_window import MainWindow
from qbotmanager.ui.pages.common import PageContext


def main():
    app = QApplication(sys.argv)
    tmp = Path(tempfile.mkdtemp(prefix="qbm_ui_smoke_"))
    s = Settings(tmp)
    s.ensure_dirs()
    s.bg_video_enabled = False
    s.bg_image_enabled = False
    tasks = TaskManager()
    win = MainWindow(s, tasks)
    win.show()

    results = []

    def stage1():
        # 设置页按钮可见性（独立页面实例，offscreen 下布局可生效）
        from qbotmanager.ui.pages.settings_page import SettingsPage
        holder = QWidget()
        holder.resize(560, 760)
        lay = QVBoxLayout(holder)
        ctx = PageContext(s, Manager(s), tasks, {
            "open_logs": lambda: None, "open_webui": lambda: None,
            "show_toast": lambda *a, **k: None, "switch_page": lambda *a: None,
            "apply_appearance": lambda: None, "apply_skin": lambda *a, **k: None,
            "bg_status": lambda: None,
        })
        page = SettingsPage(ctx)
        lay.addWidget(page)
        holder.show()
        for _ in range(3):
            app.processEvents()
        texts = ["打开 settings.json", "打开安装目录", "检查更新", "导入旧版本", "卸载 AstroSwarm"]
        found = {}
        for btn in page.findChildren(QPushButton):
            if btn.text() in texts:
                fm = btn.fontMetrics()
                need = fm.horizontalAdvance(btn.text()) + 24
                geo = btn.geometry()
                results.append(
                    f"btn '{btn.text()}' geo=({geo.x()},{geo.y()},{geo.width()}x{geo.height()}) "
                    f"need={need} fit={geo.width() >= need}")
                found[btn.text()] = (geo, need, geo.width() >= need)
        for t in texts:
            ok = t in found and found[t][2]
            if not ok:
                raise AssertionError(f"button not visible: {t} -> {found.get(t)}")
        results.append("all buttons visible & text fits")
        holder.close()
        shot1 = Path(tmp) / "win_default.png"
        win.grab().save(str(shot1))
        results.append(f"screenshot1={shot1}")
        QTimer.singleShot(10, stage2)

    def stage2():
        # AI 大脑页：接口配置面板 + 平台开关可实例化
        from qbotmanager.ui.pages.brain_page import BrainPage
        holder = QWidget()
        holder.resize(720, 820)
        lay = QVBoxLayout(holder)
        ctx = PageContext(s, Manager(s), tasks, {
            "open_logs": lambda: None, "open_webui": lambda: None,
            "show_toast": lambda *a, **k: None, "switch_page": lambda *a: None,
            "apply_appearance": lambda: None, "apply_skin": lambda *a, **k: None,
            "bg_status": lambda: None,
        })
        page = BrainPage(ctx)
        lay.addWidget(page)
        holder.show()
        for _ in range(3):
            app.processEvents()
        checks = {
            "chk_qq": page.chk_qq.isChecked(),
            "chk_wechat": page.chk_wechat.isChecked(),
            "chk_feishu": page.chk_feishu.isChecked(),
            "chk_telegram": page.chk_telegram.isChecked(),
        }
        assert all(checks.values()), checks
        assert page.btn_save.isVisible() and page.ai_url_edit.isVisible()
        scroll = page.findChild(QScrollArea)
        assert scroll is not None and scroll.widget() is not None, "brain scroll area missing"
        results.append("brain page config panel + 4 platform toggles ok")
        holder.close()

        # 边缘手柄存在 + 缩放逻辑
        handles = getattr(win, "_resize_handles", None)
        assert handles and len(handles) == 8, f"handles missing: {handles}"
        for name, h in handles.items():
            assert h.width() > 0 and h.height() > 0, f"handle {name} zero size"
        results.append("8 resize handles ok")

        g = win.geometry()
        gp = QPoint(g.right(), g.center().y())
        win._apply_resize_edge("right", g, gp, QPoint(gp.x() + 100, gp.y()))
        assert win.width() == g.width() + 100, f"right resize failed {win.width()} vs {g.width()+100}"
        results.append(f"resize right ok -> width={win.width()}")

        g = win.geometry()
        gp = QPoint(g.center().x(), g.bottom())
        win._apply_resize_edge("bottom", g, gp, QPoint(gp.x(), gp.y() + 50))
        assert win.height() == g.height() + 50, "bottom resize failed"
        results.append(f"resize bottom ok -> height={win.height()}")

        # 最小尺寸保护
        g = win.geometry()
        gp = QPoint(g.left(), g.top())
        win._apply_resize_edge("topleft", g, gp, QPoint(g.right(), g.bottom()))
        assert win.width() >= MainWindow.MIN_WINDOW_W and win.height() >= MainWindow.MIN_WINDOW_H
        results.append(f"min size ok -> {win.width()}x{win.height()}")

        win.resize(1200, 720)
        for _ in range(3):
            app.processEvents()
        shot2 = Path(tmp) / "win_resized.png"
        win.grab().save(str(shot2))
        results.append(f"screenshot2={shot2}")

        # 设置页滚动：小窗下内容可滚动访问
        page = [w for w in win.pages if w.__class__.__name__ == "SettingsPage"][0]
        scroll = page.findChild(QScrollArea)
        assert scroll is not None, "settings scroll area missing"
        assert scroll.widget() is not None and scroll.viewport() is not None
        results.append(f"settings scroll ok viewport={scroll.viewport().width()}x{scroll.viewport().height()}")
        app.quit()

    QTimer.singleShot(300, stage1)
    app.exec()
    print("\n".join(results))
    print("UI_SMOKE_OK")


if __name__ == "__main__":
    main()
