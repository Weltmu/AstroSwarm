# -*- coding: utf-8 -*-
"""飞书页：预留占位。"""
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from ..widgets import EmptyState
from .common import PageContext


class FeishuPage(QWidget):
    def __init__(self, ctx: PageContext):
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        title = QLabel("飞书")
        title.setObjectName("pageTitle")
        outer.addWidget(title)
        outer.addWidget(EmptyState(
            "飞书通道 · 规划中",
            "同一 AI 大脑多平台扩展的下一站；接入时使用 NoneBot 官方社区适配器",
        ))
