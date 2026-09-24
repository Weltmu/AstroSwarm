# -*- coding: utf-8 -*-
"""接入：所有聊天通道放在一页里（通道名 + 状态 + 就地展开配置）。

设计规范要点（与控制台 AccessPage 对齐）：
- 一个通道一行，行里直接给关键信息；点「配置 ›」就地展开这条通道的完整设置，不用跳页；
- 展开区用 `channel_panels` 的共用面板 —— QQ/微信 独立页用的是同一份，改一处两端一致；
- 状态必须带文字（「QQ · 未连接」），不靠颜色；
- 未开放的通道直接写「规划中」并禁用按钮，不做成灰色可点的假按钮。
"""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from ...core import license as lic_mod
from ..theme import TEXT_3
from ..widgets import GlassPanel, StatusBadge
from .channel_panels import QQChannelPanel, WeChatChannelPanel
from .common import PageContext


class AccessPage(QWidget):
    """接入总览：QQ / 微信 / 飞书 / 纸飞机；QQ、微信可就地展开配置。"""

    def __init__(self, ctx: PageContext):
        super().__init__()
        self.ctx = ctx
        self._rows = {}     # key -> (状态徽标, 展开按钮)
        self._bodies = {}   # key -> 展开区容器
        self._panels = {}   # key -> 共用配置面板
        self._links = {}    # key -> 「打开完整页」按钮
        self._blocks = {}   # key -> 整行容器（用于收起后让布局立刻重算）
        self._open = ""
        self._collapsed_h = 0   # 全部收起时滚动内容需要的高度（基线，窗口变宽变窄时重算）
        self._build_ui()
        self.refresh_status()

    # ------------------------------------------------------------ UI
    def _build_ui(self):
        # 展开配置后内容会明显变长：页面必须能滚，否则 Qt 会压缩文字（历史反复踩过）
        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        content = QWidget()
        outer = QVBoxLayout(content)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(16)

        title = QLabel("接入")
        title.setObjectName("pageTitle")
        sub = QLabel("想让机器人在哪几个平台说话，就来这里；点每行的「配置」就地展开这条通道的设置")
        sub.setObjectName("pageSub")
        outer.addWidget(title)
        outer.addWidget(sub)

        panel = GlassPanel(strong=True)
        pv = QVBoxLayout(panel)
        pv.setContentsMargins(16, 14, 16, 16)
        pv.setSpacing(8)

        pv.addWidget(self._make_channel_block(
            "qq", "QQ 机器人",
            "第三方 OneBot 协议（协议端如 NapCat / LLOneBot 需你自己装）", "QQ"))
        pv.addWidget(self._make_channel_block(
            "wechat", "微信 ClawBot",
            "腾讯官方 iLink 通道，扫码登录（会员档）", "微信"))
        for key, name, desc in (
            ("feishu", "飞书", "适配器还没做"),
            ("telegram", "纸飞机", "适配器还没做"),
        ):
            pv.addLayout(self._make_closed_row(key, name, desc))

        outer.addWidget(panel)

        tip = QLabel("提示：一个通道配好之后，机器人会用同一个 AI 大脑、同一份记忆和人设说话。"
                     "协议端（NapCat 等）要自己安装并登录，星群不内置。")
        tip.setWordWrap(True)
        tip.setStyleSheet(f"color: {TEXT_3}; font-size: 12px;")
        outer.addWidget(tip)
        outer.addStretch(1)
        self.scroll.setWidget(content)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self.scroll)
        self._sync_content_height()
        self._open = ""

    def _sync_content_height(self):
        """让滚动内容按「收起基线 + 展开区实际高度」撑开。

        坑：这会话里的小字提示都是自动换行的 QLabel，在 QVBoxLayout 里一旦空间不够，
        Qt 会优先把它们的行数砍掉（height-for-width 的负弹性），表现就是「展开后被压成一行」；
        QScrollArea 只按最小高度决定要不要滚，所以必须显式把最小高度顶起来。

        为什么不用「直接量当前 sizeHint」：刚把展开区 setVisible(False) 之后，Qt 还没重跑布局，
        sizeHint 仍是展开时的高度（收起后会留一大片空白）。所以收起时的基线单独量、平时不重算，
        展开时按展开区自身的 sizeHint 加上去。
        """
        content = self.scroll.widget()
        if content is None:
            return
        if not self._open:
            if not self._collapsed_h:
                self._measure_collapsed_height()
            content.setMinimumHeight(self._collapsed_h)
            return
        base = self._collapsed_h or 640
        body = self._bodies.get(self._open)
        extra = (body.sizeHint().height() + 8) if body is not None else 0
        content.setMinimumHeight(base + extra)

    def _measure_collapsed_height(self):
        """量「全部收起」时的内容高度：只能在没有展开区时量（否则会量到展开后的高度）。"""
        content = self.scroll.widget()
        lay = content.layout()
        if lay is not None:
            lay.invalidate()
            lay.activate()
        self._collapsed_h = content.sizeHint().height()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # 宽度变了，收起基线要重算；展开中不重算（用旧基线近似，收起时再校准）
        if not self._open:
            self._collapsed_h = 0
        self._sync_content_height()

    def _make_channel_block(self, key, name, desc, page):
        """一行通道 + 可展开的配置区（默认收起）。"""
        block = QWidget()
        bv = QVBoxLayout(block)
        bv.setContentsMargins(0, 0, 0, 0)
        bv.setSpacing(6)

        head = QHBoxLayout()
        head.setSpacing(16)
        head.addLayout(self._make_title_col(name, desc))
        badge = StatusBadge(key, "unknown")
        head.addWidget(badge)
        btn = QPushButton("配置 ›")
        btn.setObjectName("ghost")
        btn.setMinimumWidth(96)
        btn.clicked.connect(lambda _=False, k=key: self._toggle(k))
        head.addWidget(btn)
        bv.addLayout(head)

        body = QWidget()
        body.setVisible(False)
        # 高度也钉成 0：只 setVisible(False) 的话，父布局的 sizeHint 缓存还是展开时的高度，
        # 收起后会在行与行之间留一大片空白（Qt 要等下一轮布局事件才重算）。
        body.setFixedHeight(0)
        bvv = QVBoxLayout(body)
        bvv.setContentsMargins(0, 6, 0, 4)
        bvv.setSpacing(8)
        if key == "qq":
            channel_panel = QQChannelPanel(self.ctx, on_saved=self.refresh_status)
        else:
            channel_panel = WeChatChannelPanel(self.ctx, show_badge=False)
        bvv.addWidget(channel_panel)

        link = QPushButton(f"打开完整「{page}」页 ›")
        link.setObjectName("ghost")
        link.setMinimumHeight(30)
        link.clicked.connect(lambda _=False, p=page: self.ctx.switch_page(p))
        link_row = QHBoxLayout()
        link_row.addWidget(link)
        link_row.addStretch(1)
        bvv.addLayout(link_row)
        bv.addWidget(body)

        self._rows[key] = (badge, btn)
        self._bodies[key] = body
        self._panels[key] = channel_panel
        self._links[key] = link
        self._blocks[key] = block
        return block

    def _make_closed_row(self, key, name, desc):
        """规划中的通道：一行说明 + 禁用的「规划中」，不做成灰的可点按钮。"""
        row = QHBoxLayout()
        row.setSpacing(16)
        row.addLayout(self._make_title_col(name, desc))
        badge = StatusBadge(key, "unknown")
        row.addWidget(badge)
        btn = QPushButton("规划中")
        btn.setObjectName("ghost")
        btn.setMinimumWidth(96)
        btn.setEnabled(False)
        row.addWidget(btn)
        self._rows[key] = (badge, btn)
        return row

    def _make_title_col(self, name, desc):
        col = QVBoxLayout()
        col.setSpacing(2)
        name_lbl = QLabel(name)
        name_lbl.setStyleSheet("font-size: 14px;")
        desc_lbl = QLabel(desc)
        desc_lbl.setWordWrap(True)
        desc_lbl.setStyleSheet(f"color: {TEXT_3}; font-size: 12px;")
        col.addWidget(name_lbl)
        col.addWidget(desc_lbl)
        return col

    def _toggle(self, key: str):
        """展开/收起某条通道；一次只展开一条，避免整页突然拉很长。"""
        self._open = "" if self._open == key else key
        for k, body in self._bodies.items():
            opening_this = k == self._open
            body.setVisible(opening_this)
            body.setFixedHeight(body.sizeHint().height() if opening_this else 0)
            block = self._blocks.get(k)
            if block is not None:
                block.updateGeometry()
            self._rows[k][1].setText("收起" if k == self._open else "配置 ›")
        if self._open:
            self._refresh_panel(self._open)
        self._sync_content_height()
        # 再延后一帧兜一次：极端情况下（窗口尺寸刚变过）第一遍量出来的高度会偏小
        QTimer.singleShot(0, self._sync_content_height)

    def _refresh_panel(self, key: str):
        panel = self._panels.get(key)
        if panel is None:
            return
        try:
            if key == "qq":
                panel.load_credentials()
            else:
                panel.refresh_status()
        except Exception as e:  # noqa: BLE001 —— 管理器没就绪时不要炸页面
            self.ctx.show_toast("通道状态刷新失败：" + str(e))

    # ------------------------------------------------------------ 状态
    def refresh_status(self):
        """按真实运行状态刷新每行徽标（与首页同一套判定）。"""
        m = self.ctx.manager
        try:
            bot_on = m.bot_running()
            qq_on = m.qq_running() or m.dsh_running()
            qq_st = m.qq_login_state()
        except Exception:  # noqa: BLE001 —— 管理器还没就绪时不要炸页面
            bot_on = qq_on = False
            qq_st = {}
        qq_badge = self._rows["qq"][0]
        if qq_on:
            qq_badge.set_status("running", "QQ · 运行中")
        elif bot_on:
            qq_badge.set_status("warning", "QQ · 机器人已启动但通道未连上")
        else:
            qq_badge.set_status("stopped", "QQ · 已停止")

        wx_badge = self._rows["wechat"][0]
        try:
            gate = lic_mod.feature_gate()
            member = bool(gate.get("member", False))
        except Exception:  # noqa: BLE001
            member = False
        if not member:
            wx_badge.set_status("stopped", "微信 · 需会员档解锁")
        else:
            try:
                wx = m.wechat_status()
            except Exception:  # noqa: BLE001
                wx = {}
            if not wx.get("installed"):
                wx_badge.set_status("unknown", "微信 · 未安装适配器")
            elif wx.get("connected"):
                wx_badge.set_status("connected", "微信 · 已连接")
            elif wx.get("logged_in"):
                wx_badge.set_status("warning", "微信 · 已登录未连接")
            else:
                wx_badge.set_status("stopped", "微信 · 未登录")

        self._rows["feishu"][0].set_status("stopped", "飞书 · 规划中")
        self._rows["telegram"][0].set_status("stopped", "纸飞机 · 规划中")

        # 展开中的通道跟着刷新（QQ 刷地址、微信刷二维码与按钮可用性）
        if self._open:
            self._refresh_panel(self._open)
