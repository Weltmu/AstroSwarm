# -*- coding: utf-8 -*-
"""微信页：ClawBot 通道状态、扫码登录、最近会话。"""
import time
import webbrowser

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QLabel, QPushButton, QVBoxLayout, QWidget,
)

from ...core import message_store
from ..theme import TEXT_3
from ..widgets import GlassPanel
from .channel_panels import WeChatChannelPanel
from .common import PageContext


class WechatPage(QWidget):
    def __init__(self, ctx: PageContext):
        super().__init__()
        self.ctx = ctx
        self._qr_url_cache = ""
        self._qr_shown_at = 0.0
        self._qr_auto_at = 0.0
        self._build_ui()
        self.refresh_status()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(14)

        title = QLabel("微信")
        title.setObjectName("pageTitle")
        sub = QLabel("微信 ClawBot 通道：个人私聊 AI 助手（扫码后微信出现 ClawBot 会话）")
        sub.setObjectName("pageSub")
        outer.addWidget(title)
        outer.addWidget(sub)

        self.gate_lock = QLabel("")
        self.gate_lock.setWordWrap(True)
        self.gate_lock.setStyleSheet(
            "color: #F59E0B; font-size: 12px; background: rgba(245,158,11,0.10);"
            "border-radius: 6px; padding: 6px 8px;")
        self.gate_lock.hide()
        outer.addWidget(self.gate_lock)
        self.btn_pay = QPushButton("开通微信通道")
        self.btn_pay.setObjectName("ghost")
        self.btn_pay.clicked.connect(self._open_pay)
        self.btn_pay.hide()
        outer.addWidget(self.btn_pay)

        card = GlassPanel()
        cv = QVBoxLayout(card)
        cv.setContentsMargins(18, 14, 18, 16)
        cv.setSpacing(8)
        # 登录卡本体在 channel_panels.WeChatChannelPanel：接入页的内联展开区用的是同一份代码
        self.wx_panel = WeChatChannelPanel(self.ctx)
        cv.addWidget(self.wx_panel)
        outer.addWidget(card)
        # 兼容旧引用：页面自己与测试用这些名字
        self.badge = self.wx_panel.badge
        self.login_hint = self.wx_panel.login_hint
        self.bot_id = self.wx_panel.bot_id
        self.login_time = self.wx_panel.login_time
        self.qr_box = self.wx_panel.qr_box
        self.ai_warn = self.wx_panel.ai_warn
        self.btn_reset = self.wx_panel.btn_reset
        self.btn_qr_refresh = self.wx_panel.btn_qr_refresh
        self.btn_qr = self.wx_panel.btn_qr
        self.btn_verify_code = self.wx_panel.btn_verify_code
        self.btn_restart = self.wx_panel.btn_restart

        recent = GlassPanel()
        rv = QVBoxLayout(recent)
        rv.setContentsMargins(18, 12, 18, 14)
        rl = QLabel("最近微信会话")
        rl.setObjectName("sectionTitle")
        rv.addWidget(rl)
        self.recent_label = QLabel("—")
        self.recent_label.setWordWrap(True)
        self.recent_label.setStyleSheet(f"color: {TEXT_3}; font-size: 12px;")
        rv.addWidget(self.recent_label)
        btn_center = QPushButton("打开消息中心")
        btn_center.clicked.connect(lambda: self.ctx.switch_page("消息中心"))
        rv.addWidget(btn_center)
        rv.addStretch(1)
        outer.addWidget(recent, 1)

    def _open_pay(self):
        from ...core import license as lic_mod
        webbrowser.open(lic_mod.PAY_URL)

    def refresh_status(self):
        from ...core import license as lic_mod

        gate = lic_mod.feature_gate()
        locked = not gate.get("member", True)
        if locked:
            reason = gate.get("reason") or "QQ 通道可用；微信通道未开通"
            self.gate_lock.setText(
                reason + "。开通后即可扫码登录；适配器源码随仓库开源（Apache-2.0），"
                "你也可以自己接入，只是不含官方支持。")
            self.gate_lock.show()
            self.btn_pay.show()
        else:
            self.gate_lock.hide()
            self.btn_pay.hide()
        # 登录卡（状态徽标 / 二维码 / 按钮可用性）在共用面板里，接入页用的是同一份
        self.wx_panel.refresh_status()

        convs = [c for c in message_store.load_conversations(self.ctx.settings, 50)
                 if c["platform"] == "wechat"]
        if not convs:
            self.recent_label.setText("暂无微信会话")
        else:
            lines = []
            for c in convs[-6:]:
                scene = "私聊" if c["scene"] == "private" else "群聊"
                lines.append(f"[{scene}] {c['room']} · {c['count']} 条 · {c['last']}")
            self.recent_label.setText("\n".join(lines))
