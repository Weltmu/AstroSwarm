# -*- coding: utf-8 -*-
"""消息中心：跨平台会话列表（QQ / 微信 / 飞书 / 纸飞机）。

与控制台的无头端页面同源、同字段：会话标题用 platform + scene + room 拼出
「QQ 群 123456 / QQ 好友 123456 / 微信 好友 xxx」。以前只显示 platform + room，
同一个人的多个会话看起来长得一样，分不清是群还是私聊。
"""
import time

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QVBoxLayout, QWidget,
)

from ...core import message_store
from ..theme import TEXT_3
from ..widgets import EmptyState, GlassPanel
from .common import PageContext


class MessageCenterPage(QWidget):
    def __init__(self, ctx: PageContext):
        super().__init__()
        self.ctx = ctx
        self._build_ui()
        self.refresh()
        self._timer = QTimer(self)
        self._timer.setInterval(3000)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(14)

        title = QLabel("消息中心")
        title.setObjectName("pageTitle")
        sub = QLabel("跨平台会话时间线：QQ 群/私聊 与 微信 ClawBot 统一查看")
        sub.setObjectName("pageSub")
        outer.addWidget(title)
        outer.addWidget(sub)

        bar = QHBoxLayout()
        lbl = QLabel("平台")
        lbl.setStyleSheet(f"color: {TEXT_3}; font-size: 12px;")
        self.filter_combo = QComboBox()
        self.filter_combo.addItem("全部", "")
        for key, label in message_store.PLATFORM_LABELS.items():
            self.filter_combo.addItem(label, key)
        self.filter_combo.currentIndexChanged.connect(self.refresh)
        btn_refresh = QPushButton("刷新")
        btn_refresh.clicked.connect(self.refresh)
        self.stat_label = QLabel("读取中…")
        self.stat_label.setStyleSheet(f"color: {TEXT_3}; font-size: 12px;")
        bar.addWidget(lbl)
        bar.addWidget(self.filter_combo)
        bar.addWidget(btn_refresh)
        bar.addWidget(self.stat_label)
        bar.addStretch(1)
        outer.addLayout(bar)

        glass = GlassPanel(strong=True)
        gv = QVBoxLayout(glass)
        gv.setContentsMargins(12, 10, 12, 12)
        self.list = QListWidget()
        self.list.setStyleSheet(
            "QListWidget{background:rgba(9,12,19,0.45);border:1px solid #2a3a52;"
            "border-radius:8px;color:#dbe4f0;font-size:12px;}"
            "QListWidget::item{padding:7px 10px;border-bottom:1px solid rgba(42,58,82,0.4);}"
        )
        gv.addWidget(self.list)
        outer.addWidget(glass, 1)
        self.empty = EmptyState("暂无会话", "机器人尚未产生对话记录（需启用内置 AI 插件）")
        outer.addWidget(self.empty)

    def refresh(self):
        platform = self.filter_combo.currentData() or ""
        convs = message_store.load_conversations(self.ctx.settings, 300)
        total = len(convs)
        if platform:
            convs = [c for c in convs if c["platform"] == platform]
        self.stat_label.setText(
            f"共 {total} 个会话" if not platform else
            f"共 {total} 个会话（当前筛选：{self.filter_combo.currentText()}，{len(convs)} 个）")
        self.list.clear()
        has = False
        for c in reversed(convs):
            text = self._row_text(c)
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, c)
            item.setToolTip(text)
            self.list.addItem(item)
            has = True
        self.empty.setVisible(not has)
        self.list.setVisible(has)

    # ------------------------------------------------------------ 行文本
    @staticmethod
    def _label(c) -> str:
        """会话标题：机器人侧给了名字就用名字，否则拼「QQ 群 123456」这种可区分标题。"""
        given = str(c.get("title") or c.get("name") or "").strip()
        if given:
            return given
        plat = message_store.PLATFORM_LABELS.get(
            c.get("platform"), str(c.get("platform") or "未知平台"))
        room = str(c.get("room") or c.get("key") or "").strip()
        if not room:
            return f"{plat} 会话"
        scene = message_store.SCENE_LABELS.get(str(c.get("scene") or ""), "会话")
        return f"{plat} {scene} {room}"

    @staticmethod
    def _meta(c) -> str:
        parts = []
        if str(c.get("title") or c.get("name") or "").strip():
            # 名字里已经带了平台就不用再重复一遍
            parts.append(message_store.PLATFORM_LABELS.get(
                c.get("platform"), str(c.get("platform") or "")))
        try:
            count = int(c.get("count") or 0)
        except (TypeError, ValueError):
            count = 0
        if count:
            parts.append(f"{count} 条")
        try:
            ts = float(c.get("ts") or 0)
        except (TypeError, ValueError):
            ts = 0.0
        if ts:
            parts.append(time.strftime("%Y-%m-%d %H:%M", time.localtime(ts)))
        return " · ".join(p for p in parts if p)

    def _row_text(self, c) -> str:
        head = f"{self._label(c)} · {self._meta(c)}".rstrip(" ·")
        last = str(c.get("last_text") or c.get("last") or "").strip()
        return f"{head}\n  {last}" if last else head
