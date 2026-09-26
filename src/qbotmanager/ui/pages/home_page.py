# -*- coding: utf-8 -*-
"""首页：总览仪表盘 —— 各平台服务状态 + 今日数据 + 最近消息预览 + 快速操作。"""
import os
import time
import webbrowser

from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QVBoxLayout, QWidget,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor

from ...core import message_store
from ...tasks.workers import StartStopTask
from ..theme import TEXT_3
from ..widgets import EmptyState, GlassPanel, StatusBadge
from .common import PageContext, TaskPanel, make_row


class HomePage(QWidget):
    def __init__(self, ctx: PageContext):
        super().__init__()
        self.ctx = ctx
        self._service_tid = None
        self._bot_running = False
        self._build_ui()
        self._connect_tasks()
        self.refresh_status()

    # ------------------------------------------------------------ UI
    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(16)

        title_row = QHBoxLayout()
        left = QVBoxLayout()
        title = QLabel("首页")
        title.setObjectName("pageTitle")
        sub = QLabel("各平台服务状态总览，一键进入管理")
        sub.setObjectName("pageSub")
        left.addWidget(title)
        left.addWidget(sub)
        title_row.addLayout(left)
        title_row.addStretch(1)
        self.global_badge = StatusBadge("服务状态", "unknown")
        self.last_update = QLabel("—")
        self.last_update.setStyleSheet(f"color: {TEXT_3}; font-size: 12px;")
        title_row.addWidget(self.last_update)
        title_row.addWidget(self.global_badge)
        outer.addLayout(title_row)

        # ---- 平台状态卡片（QQ / 微信 / 飞书 / 纸飞机） ----
        cards = QHBoxLayout()
        cards.setSpacing(16)
        self._cards_layout = cards
        self._build_qq_card(cards)
        self._build_wechat_card(cards)
        self._build_feishu_card(cards)
        self._build_telegram_card(cards)
        outer.addLayout(cards)

        # ---- 今日数据 + 最近消息 ----
        mid = QHBoxLayout()
        mid.setSpacing(16)

        stats = GlassPanel()
        stv = QVBoxLayout(stats)
        stv.setContentsMargins(16, 14, 16, 16)
        sl = QLabel("今日数据")
        sl.setObjectName("sectionTitle")
        stv.addWidget(sl)
        self.stat_labels = {}
        for key, label in (
            ("messages", "消息总数"),
            ("ai_calls", "AI 调用"),
            ("mcp", "MCP 服务器"),
            ("memory", "记忆条数"),
            ("identity", "身份绑定"),
        ):
            val = QLabel("—")
            val.setStyleSheet(f"color: {TEXT_3}; font-size: 12px;")
            self.stat_labels[key] = val
            stv.addLayout(make_row(label, val))
        stv.addStretch(1)
        mid.addWidget(stats, 3)

        recent = GlassPanel(strong=True)
        rv = QVBoxLayout(recent)
        rv.setContentsMargins(16, 14, 16, 16)
        rl = QLabel("最近消息")
        rl.setObjectName("sectionTitle")
        rv.addWidget(rl)
        self.recent_list = QListWidget()
        self.recent_list.setObjectName("recentList")
        self.recent_list.setFrameShape(QFrame.NoFrame)
        self.recent_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.recent_list.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.recent_list.setWordWrap(True)
        self.recent_list.setFocusPolicy(Qt.NoFocus)
        self.recent_list.setSelectionMode(QListWidget.NoSelection)
        self.recent_list.setStyleSheet(
            "QListWidget#recentList { background: transparent; border: none; }"
            "QListWidget#recentList::item { color: #9FB0C8; font-size: 12px;"
            " padding: 6px 4px; border-bottom: 1px solid rgba(255,255,255,0.05); }"
            "QListWidget#recentList::item:hover { background: rgba(255,255,255,0.04); }"
        )
        rv.addWidget(self.recent_list, 1)
        btn_center = QPushButton("打开消息中心")
        btn_center.clicked.connect(lambda: self.ctx.switch_page("消息中心"))
        rv.addWidget(btn_center)
        mid.addWidget(recent, 7)
        outer.addLayout(mid, 1)

        # ---- 主操作 + 高级（运维动作默认收起） + 当前任务 ----
        bottom = QHBoxLayout()
        bottom.setSpacing(16)
        quick = GlassPanel()
        qv = QVBoxLayout(quick)
        qv.setContentsMargins(16, 14, 16, 16)
        qv.setSpacing(8)
        ql = QLabel("机器人")
        ql.setObjectName("sectionTitle")
        qv.addWidget(ql)
        # 一屏只留一个主操作：运行中就变成「停止全部」，两个按钮不再同屏抢注意力
        self.btn_toggle = QPushButton("启动全部")
        self.btn_toggle.setObjectName("primary")
        self.btn_toggle.clicked.connect(self._on_toggle_clicked)
        qv.addWidget(self.btn_toggle)
        self.btn_advanced = QPushButton("高级…")
        self.btn_advanced.setObjectName("ghost")
        self.btn_advanced.clicked.connect(self._toggle_advanced)
        qv.addWidget(self.btn_advanced)

        self.advanced_box = QFrame()
        ab = QVBoxLayout(self.advanced_box)
        ab.setContentsMargins(0, 0, 0, 0)
        ab.setSpacing(8)
        self.btn_restart = QPushButton("重启机器人")
        self.btn_restart.clicked.connect(self._restart_bot)
        self.btn_env = QPushButton("打开 .env")
        self.btn_env.clicked.connect(self._open_env)
        ab.addWidget(self.btn_restart)
        ab.addWidget(self.btn_env)
        self.advanced_box.setVisible(False)
        qv.addWidget(self.advanced_box)
        qv.addStretch(1)
        bottom.addWidget(quick, 4)

        task_glass = GlassPanel(strong=True)
        tv = QVBoxLayout(task_glass)
        tv.setContentsMargins(16, 14, 16, 16)
        tl = QLabel("当前任务")
        tl.setObjectName("sectionTitle")
        tv.addWidget(tl)
        self.task_panel = TaskPanel(self.ctx.tasks)
        self.task_panel.setVisible(False)
        self.task_panel.action_requested.connect(self._on_task_action)
        tv.addWidget(self.task_panel)
        self.task_empty = EmptyState(
            "当前没有正在执行的任务",
            "点击「启动全部」开始，或在插件/依赖页发起安装任务",
        )
        tv.addWidget(self.task_empty, 1)
        bottom.addWidget(task_glass, 6)
        outer.addLayout(bottom)
        self.set_beginner(bool(self.ctx.settings.beginner_mode))

    def set_beginner(self, on: bool):
        """小白模式：首页只保留 QQ / 微信两张状态卡，隐藏飞书与纸飞机。"""
        on = bool(on)
        layout = getattr(self, "_cards_layout", None)
        if layout is None:
            return
        for i in (2, 3):
            item = layout.itemAt(i)
            w = item.widget() if item is not None else None
            if w is not None:
                w.setVisible(not on)

    def _card(self, parent_layout, name):
        card = GlassPanel()
        v = QVBoxLayout(card)
        v.setContentsMargins(16, 14, 16, 16)
        v.setSpacing(8)
        badge = StatusBadge(name, "unknown")
        v.addWidget(badge)
        parent_layout.addWidget(card, 1)
        return card, v, badge

    def _build_qq_card(self, cards):
        card, v, self.qq_badge = self._card(cards, "QQ 机器人")
        self.qq_info = QLabel("—")
        self.qq_info.setWordWrap(True)
        self.qq_info.setStyleSheet(f"color: {TEXT_3}; font-size: 12px;")
        v.addWidget(self.qq_info)
        row = QHBoxLayout()
        btn = QPushButton("去管理")
        btn.clicked.connect(lambda: self.ctx.switch_page("接入"))
        row.addWidget(btn)
        row.addStretch(1)
        v.addLayout(row)
        v.addStretch(1)

    def _build_wechat_card(self, cards):
        card, v, self.wx_badge = self._card(cards, "微信 ClawBot")
        self.wx_info = QLabel("—")
        self.wx_info.setWordWrap(True)
        self.wx_info.setStyleSheet(f"color: {TEXT_3}; font-size: 12px;")
        v.addWidget(self.wx_info)
        row = QHBoxLayout()
        btn = QPushButton("去管理")
        btn.clicked.connect(lambda: self.ctx.switch_page("接入"))
        row.addWidget(btn)
        self.wx_pay_btn = QPushButton("开通微信通道")
        self.wx_pay_btn.setObjectName("ghost")
        self.wx_pay_btn.clicked.connect(self._open_pay)
        row.addWidget(self.wx_pay_btn)
        row.addStretch(1)
        v.addLayout(row)
        v.addStretch(1)

    def _open_pay(self):
        from ...core import license as lic_mod
        webbrowser.open(lic_mod.PAY_URL)

    def _build_feishu_card(self, cards):
        card, v, self.feishu_badge = self._card(cards, "飞书")
        self.feishu_badge.set_status("stopped", "飞书 · 未接入")
        tip = QLabel("规划中")
        tip.setStyleSheet(f"color: {TEXT_3}; font-size: 12px;")
        v.addWidget(tip)
        v.addStretch(1)

    def _build_telegram_card(self, cards):
        card, v, self.telegram_badge = self._card(cards, "纸飞机")
        self.telegram_badge.set_status("stopped", "纸飞机 · 未接入")
        tip = QLabel("规划中")
        tip.setStyleSheet(f"color: {TEXT_3}; font-size: 12px;")
        v.addWidget(tip)
        v.addStretch(1)

    # ------------------------------------------------------------ 任务
    def _connect_tasks(self):
        t = self.ctx.tasks
        t.started.connect(self._on_service_started)
        t.finished.connect(self._on_service_finished)

    def _on_service_started(self, tid, name):
        if name in ("启动服务", "停止服务"):
            self._service_tid = tid
            self.task_panel.bind(tid)
            self.task_panel.setVisible(True)
            self.task_empty.setVisible(False)

    def _on_service_finished(self, tid, status, result):
        if tid == self._service_tid:
            self.task_panel.bind(tid)
        self.refresh_status()

    def _on_task_action(self, action, task_id):
        if action == "cancel":
            self.ctx.tasks.cancel(task_id)
        elif action == "retry":
            self.task_panel.bind(self.ctx.tasks.retry(task_id) or "")
        elif action == "logs":
            self.ctx.open_logs()

    def _start_stop(self, start: bool):
        self.ctx.tasks.submit(
            "启动服务" if start else "停止服务", "service", StartStopTask,
            payload={"start": start}, retryable=True, manager=self.ctx.manager,
        )

    def _on_toggle_clicked(self):
        """主操作：未运行→启动全部；运行中→先二次确认再停止全部。"""
        if self._bot_running:
            if not self._confirm("停止机器人",
                                 "停止后 QQ / 微信都会离线，正在进行的对话会中断。\n\n确定停止吗？"):
                return
        self._start_stop(not self._bot_running)

    def _toggle_advanced(self):
        show = not self.advanced_box.isVisible()
        self.advanced_box.setVisible(show)
        self.btn_advanced.setText("收起高级" if show else "高级…")

    def _restart_bot(self):
        from ...tasks.workers import RestartBotTask

        if not self._confirm("重启机器人", "重启期间机器人会短暂离线。确定继续吗？"):
            return
        self.ctx.tasks.submit(
            "重启 NoneBot", "service", RestartBotTask,
            retryable=True, manager=self.ctx.manager,
            payload={"reset_wechat": False},
        )

    def _open_env(self):
        path = str(self.ctx.settings.bot_env_file)
        try:
            if hasattr(os, "startfile"):        # Windows
                os.startfile(path)              # noqa: S606
        except OSError:
            pass

    def _confirm(self, title: str, text: str) -> bool:
        from PySide6.QtWidgets import QMessageBox

        ret = QMessageBox.question(self, title, text,
                                   QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        return ret == QMessageBox.Yes

    # ------------------------------------------------------------ 状态
    def refresh_status(self):
        s = self.ctx.settings
        m = self.ctx.manager
        bot_on = m.bot_running()
        qq_on = m.qq_running() or m.dsh_running()
        qq_st = m.qq_login_state()
        qq = str(qq_st.get("account") or "未配置")
        self.qq_badge.set_status("running" if qq_on else "stopped",
                                 "QQ · " + ("运行中" if qq_on else "已停止"))
        self.qq_info.setText(f"AppID {qq}\nNoneBot {'运行' if bot_on else '停止'} / "
                             + ("dsh 群聊 AI 运行中"
                                if m.dsh_running()
                                else f"官方通道 {qq_st.get('reason') or '未知'}"))

        from ...core import license as lic_mod

        gate = lic_mod.feature_gate()
        if not gate.get("member", True):
            reason = gate.get("reason") or "QQ 通道可用；微信通道未开通"
            self.wx_badge.set_status("stopped", "微信 · 未开通")
            self.wx_info.setText(reason + "\n在账号中心开通后即可扫码登录")
            self.wx_pay_btn.show()
            wx = {"logged_in": False}
        else:
            self.wx_pay_btn.hide()
            wx = m.wechat_status()
            if not wx["installed"]:
                self.wx_badge.set_status("unknown", "微信 · 未安装适配器")
            elif wx.get("connected"):
                self.wx_badge.set_status("connected", "微信 · 已连接")
            elif wx["logged_in"]:
                self.wx_badge.set_status("warning", "微信 · 未连接")
            else:
                self.wx_badge.set_status("stopped", "微信 · 未登录")
            self.wx_info.setText(str(wx["bot_id"] or "未登录") + "\nClawBot 私聊个人助手")

        any_on = bot_on or qq_on or wx.get("logged_in")
        self.global_badge.set_status("running" if any_on else "stopped",
                                     "服务" + ("运行中" if any_on else "已停止"))
        self.last_update.setText("更新于 " + time.strftime("%H:%M:%S"))
        # 主操作随状态翻转：运行中就是「停止全部」
        self._bot_running = bool(bot_on)
        self.btn_toggle.setText("停止全部" if bot_on else "启动全部")

        summary = message_store.brain_summary(s)
        self.stat_labels["messages"].setText(str(message_store.load_message_count(s)))
        self.stat_labels["ai_calls"].setText("—")
        self.stat_labels["mcp"].setText(str(summary["mcp_servers"]))
        self.stat_labels["memory"].setText(str(summary["memory_global"] + summary["memory_users"]))
        self.stat_labels["identity"].setText(str(summary["identity_binds"]))

        convs = message_store.load_conversations(s, 8)
        self.recent_list.clear()
        if not convs:
            item = QListWidgetItem("暂无消息记录")
            item.setForeground(QColor(127, 127, 127))
            self.recent_list.addItem(item)
        else:
            for c in reversed(convs[-6:]):
                label = message_store.PLATFORM_LABELS.get(c["platform"], c["platform"])
                scene = "群" if c["scene"] == "group" else "私聊"
                text = f"{label}{scene} {c['room']}：{c['last']}"
                item = QListWidgetItem(text)
                item.setToolTip(c["last"])
                self.recent_list.addItem(item)
