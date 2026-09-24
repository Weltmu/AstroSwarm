# -*- coding: utf-8 -*-
"""内置教程查看窗口：LLOneBot 无头模式接入教程（HTML + 截图随程序资源打包）。"""
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QDialog, QTextBrowser, QVBoxLayout

TUTORIAL_DIR = (
    Path(__file__).resolve().parent.parent.parent
    / "assets" / "llbot_tutorial"
)


class TutorialDialog(QDialog):
    """显示内置接入教程；图片通过资源目录相对路径加载。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("接入教程：LLOneBot 无头模式连接星群")
        self.resize(780, 880)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.browser = QTextBrowser(self)
        self.browser.setOpenExternalLinks(True)
        # 教程固定浅色阅读：不跟随深色主题（否则白字/黑底看不清）
        self.browser.setStyleSheet(
            "QTextBrowser { background-color: #ffffff; color: #1f2937; }")
        self.browser.setSearchPaths([str(TUTORIAL_DIR)])
        html = TUTORIAL_DIR / "index.html"
        if html.exists():
            self.browser.setSource(QUrl.fromLocalFile(str(html)))
        else:
            self.browser.setPlainText("教程资源缺失，请重新安装星群客户端。")
        layout.addWidget(self.browser)
