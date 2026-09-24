# -*- coding: utf-8 -*-
"""纸飞机（Telegram）页：预留占位。"""
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from ..widgets import EmptyState
from .common import PageContext


class TelegramPage(QWidget):
    def __init__(self, ctx: PageContext):
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        title = QLabel("纸飞机")
        title.setObjectName("pageTitle")
        outer.addWidget(title)
        outer.addWidget(EmptyState(
            "纸飞机（Telegram）通道 · 规划中",
            "同一 AI 大脑多平台扩展的下一站；接入时使用 NoneBot 官方社区适配器",
        ))
