"""QQ 机器人页：NoneBot / QQ 通道面板（官方或第三方 OneBot）+ 服务任务反馈。"""
import os

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QCheckBox, QFileDialog, QFrame, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from ...core import ai_config
from ...core import bot as bot_mod
from ...core import dsh as dsh_mod
from ...tasks.workers import (DshControlTask, InstallDshTask, RestartBotTask,
                              StartStopTask)
from .. import theme as theme_mod
from ..icon_font import make_icon
from ..theme import TEXT_3
from ..widgets import GlassPanel, StatusBadge
from .channel_panels import QQChannelPanel
from .common import PageContext, TaskPanel, make_row


def _make_warning_box(text: str) -> QFrame:
    """红框警告条：警告线性图标 + 换行文本，颜色随 UI 主题（玻璃深色 / 瑞士浅色）。"""
    swiss = theme_mod.UI_STYLE == "swiss"
    fg = "#B00020" if swiss else "#FCA5A5"
    border = "#E30613" if swiss else "rgba(248,113,113,0.45)"
    bg = "rgba(230,6,19,0.06)" if swiss else "rgba(248,113,113,0.08)"
    box = QFrame()
    box.setObjectName("warningBox")
    box.setStyleSheet(
        f"QFrame#warningBox {{ background: {bg}; border: 1px solid {border}; border-radius: 8px; }}"
    )
    row = QHBoxLayout(box)
    row.setContentsMargins(10, 8, 10, 8)
    row.setSpacing(8)
    icon_btn = QPushButton()
    icon_btn.setIcon(make_icon("warning-circle", fg, 16))
    icon_btn.setIconSize(QSize(16, 16))
    icon_btn.setFixedSize(18, 18)
    icon_btn.setFlat(True)
    icon_btn.setFocusPolicy(Qt.NoFocus)
    icon_btn.setAttribute(Qt.WA_TransparentForMouseEvents, True)
    icon_btn.setStyleSheet(
        "QPushButton { background: transparent; border: none; }")
    row.addWidget(icon_btn, 0, Qt.AlignTop)
    label = QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet(
        f"background: transparent; border: none; color: {fg}; font-size: 12px;")
    row.addWidget(label, 1)
    return box


class _Fold(QWidget):
    """折叠区：一行 ghost 按钮 + 默认收起的内容。

    按钮太多的页面（QQ 页最多时一排 6 个 dsh 按钮）用它把次要动作收起来，
    首屏只留主流程；展开状态记在自己身上，不被父页面刷新重置。
    """

    def __init__(self, closed_text: str, open_text: str, content: QWidget, parent=None):
        super().__init__(parent)
        self._closed = closed_text
        self._open = open_text
        self._content = content
        self._expanded = False
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)
        self.btn = QPushButton(closed_text)
        self.btn.setObjectName("ghost")
        self.btn.clicked.connect(self.toggle)
        # 左对齐的窄条，不要拉成一条占满整行的空框（看起来像输入框）
        v.addWidget(self.btn, 0, Qt.AlignLeft)
        content.setVisible(False)
        v.addWidget(content)

    def toggle(self):
        self.set_expanded(not self._expanded)

    def set_expanded(self, expanded: bool):
        self._expanded = bool(expanded)
        self._content.setVisible(self._expanded)
        self.btn.setText(self._open if self._expanded else self._closed)


class RunPage(QWidget):
    def __init__(self, ctx: PageContext):
        super().__init__()
        self.ctx = ctx
        self._service_tid = None
        self._tutorial_dialog = None
        self._build_ui()
        self.load_credentials()
        self._connect_tasks()
        self.refresh_status()

    def _build_ui(self):
        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        content = QWidget()
        outer = QVBoxLayout(content)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(14)

        title = QLabel("QQ 机器人")
        title.setObjectName("pageTitle")
        sub = QLabel("QQ 通道：官方机器人（q.qq.com 凭证）或第三方 OneBot 协议，两种都能接")
        sub.setObjectName("pageSub")
        outer.addWidget(title)
        outer.addWidget(sub)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.btn_start = QPushButton("启动全部")
        self.btn_start.setObjectName("primary")
        self.btn_start.clicked.connect(lambda: self._start_stop(True))
        self.btn_stop = QPushButton("停止全部")
        self.btn_stop.setObjectName("danger")
        self.btn_stop.clicked.connect(lambda: self._start_stop(False))
        self.btn_restart = QPushButton("重启 NoneBot")
        self.btn_restart.setObjectName("ghost")
        self.btn_restart.clicked.connect(self._restart_bot)
        for b in (self.btn_start, self.btn_stop, self.btn_restart):
            actions.addWidget(b)
        actions.addStretch(1)
        outer.addLayout(actions)

        util = QHBoxLayout()
        util.setContentsMargins(0, 0, 0, 0)
        util.setSpacing(8)
        btn_env = QPushButton("打开 .env")
        btn_env.setObjectName("ghost")
        btn_env.setMinimumHeight(30)
        btn_env.clicked.connect(lambda: os.startfile(str(self.ctx.settings.bot_env_file)))
        util.addWidget(btn_env)
        self.btn_tutorial = QPushButton("接入教程（LLOneBot）")
        self.btn_tutorial.setObjectName("ghost")
        self.btn_tutorial.setMinimumHeight(30)
        self.btn_tutorial.clicked.connect(self._open_tutorial)
        util.addWidget(self.btn_tutorial)
        util.addStretch(1)
        # 这两个是偶尔才用的：收进「更多」折叠区，别跟启动/停止抢位置
        util_box = QWidget()
        util_box.setLayout(util)
        self.page_fold = _Fold("更多：配置文件 / 接入教程　▾",
                               "更多：配置文件 / 接入教程　▴", util_box)
        outer.addWidget(self.page_fold)

        panels = QHBoxLayout()
        panels.setSpacing(14)

        # NoneBot 面板
        nb = GlassPanel()
        nv = QVBoxLayout(nb)
        nv.setContentsMargins(18, 14, 18, 16)
        self.bot_badge = StatusBadge("NoneBot", "unknown")
        nv.addWidget(self.bot_badge)
        self.bot_port = QLabel("—")
        self.bot_py = QLabel("—")
        self.bot_pid = QLabel("—")
        for lbl in (self.bot_port, self.bot_py, self.bot_pid):
            lbl.setStyleSheet(f"color: {TEXT_3}; font-size: 12px;")
        nv.addLayout(make_row("端口", self.bot_port))
        nv.addLayout(make_row("Python", self.bot_py))
        nv.addLayout(make_row("运行记录", self.bot_pid))
        nv.addStretch(1)
        panels.addWidget(nb, 1)

        # QQ 官方通道面板
        qq = GlassPanel()
        qv = QVBoxLayout(qq)
        qv.setContentsMargins(18, 14, 18, 16)
        self.qq_badge = StatusBadge("QQ 通道", "unknown")
        qv.addWidget(self.qq_badge)
        self.qq_appid = QLabel("—")
        self.qq_mode = QLabel("—")
        self.qq_state = QLabel("—")
        for lbl in (self.qq_appid, self.qq_mode, self.qq_state):
            lbl.setStyleSheet(f"color: {TEXT_3}; font-size: 12px;")
        self.qq_appid_label = QLabel("AppID")
        self.qq_appid_label.setStyleSheet(f"color: {TEXT_3}; font-size: 12px;")
        row_appid = QHBoxLayout()
        row_appid.addWidget(self.qq_appid_label)
        row_appid.addStretch(1)
        row_appid.addWidget(self.qq_appid)
        qv.addLayout(row_appid)
        qv.addLayout(make_row("通道", self.qq_mode))
        qv.addLayout(make_row("状态", self.qq_state))
        # 小字提示跟着「接入方式」走：官方讲凭证，第三方讲协议端自备（见 _sync_channel_tip）
        self.qq_tip = QLabel("")
        self.qq_tip.setWordWrap(True)
        self.qq_tip.setStyleSheet(f"color: {TEXT_3}; font-size: 12px;")
        qv.addWidget(self.qq_tip)
        qv.addStretch(1)
        panels.addWidget(qq, 1)
        outer.addLayout(panels)

        # QQ 通道配置（官方 / 第三方 OneBot）：表单本体在 channel_panels.QQChannelPanel，
        # 「接入」页的内联展开区用的是同一份，改一处两端一致。
        cred = GlassPanel()
        cv = QVBoxLayout(cred)
        cv.setContentsMargins(18, 14, 18, 16)
        cl = QLabel("QQ 通道配置")
        cl.setObjectName("sectionTitle")
        cv.addWidget(cl)

        self.qq_panel = QQChannelPanel(
            self.ctx,
            on_saved=self._on_channel_saved,
            on_channel_changed=self._on_channel_changed,
        )
        cv.addWidget(self.qq_panel)
        # 兼容旧引用：页面自己（refresh_status）和测试用的是这些名字
        for _attr in (
            "combo_channel", "panel_official", "panel_onebot",
            "edit_official_appid", "edit_official_token", "edit_official_secret",
            "chk_official_sandbox",
            "combo_onebot_mode", "panel_reverse", "panel_forward",
            "edit_onebot_host", "edit_onebot_port", "edit_onebot_path",
            "edit_onebot_token", "edit_onebot_listen_host",
            "edit_reverse_port", "edit_reverse_url",
            "btn_copy_reverse_url", "btn_detect_onebot", "btn_save_creds",
        ):
            setattr(self, _attr, getattr(self.qq_panel, _attr))
        self._refresh_reverse_url = self.qq_panel._refresh_reverse_url
        self._copy_reverse_url = self.qq_panel._copy_reverse_url
        self._detect_onebot = self.qq_panel._detect_onebot
        self._on_onebot_mode_changed = self.qq_panel._on_onebot_mode_changed
        outer.addWidget(cred)

        # dsh（DeepSeek Harness）QQ 群聊 AI 通道
        self.dsh_glass = GlassPanel()
        dsh_glass = self.dsh_glass
        dv = QVBoxLayout(dsh_glass)
        dv.setContentsMargins(18, 14, 18, 16)
        dl = QLabel("QQ 群聊 AI（dsh 官方通道）")
        dl.setObjectName("sectionTitle")
        dv.addWidget(dl)
        dtip = QLabel(
            "官方 DeepSeek Harness 通道：支持 QQ 私聊 + 群聊 AI。"
            "纯官方凭证（AppID/AppSecret），自动复用上方凭证与 AI 大脑模型，无需扫码。"
            "启用后 QQ 消息由 dsh 处理，NoneBot 专注微信等平台。"
        )
        dtip.setWordWrap(True)
        dtip.setStyleSheet(f"color: {TEXT_3}; font-size: 12px;")
        dv.addWidget(dtip)
        dv.addWidget(_make_warning_box(
            "平台限制：QQ 开放平台暂不支持 AIGC 机器人进入社群场景以及上架后全量对所有用户使用。"
            "与 dsh 官宣“支持群聊”并存，目前合理理解为沙箱/审核路径可用、全量上架场景仍受限；"
            "请勿对外承诺“群聊 AI 全量开放”，待真机验证或腾讯明确答复后再宣传。"
        ))
        self.dsh_badge = StatusBadge("dsh", "stopped")
        dv.addWidget(self.dsh_badge)
        self.dsh_node_lbl = QLabel("—")
        self.dsh_state_lbl = QLabel("—")
        self.dsh_model_lbl = QLabel("—")
        for lbl in (self.dsh_node_lbl, self.dsh_state_lbl, self.dsh_model_lbl):
            lbl.setStyleSheet(f"color: {TEXT_3}; font-size: 12px;")
        dv.addLayout(make_row("Node.js", self.dsh_node_lbl))
        dv.addLayout(make_row("状态", self.dsh_state_lbl))
        dv.addLayout(make_row("模型", self.dsh_model_lbl))
        # 勾选即生效：改动自动保存，页面上不再多一个「保存 dsh 设置」按钮
        self._dsh_loading = True
        self.chk_dsh_enable = QCheckBox("启用 dsh 通道（改动自动保存）")
        self.chk_dsh_enable.toggled.connect(self._on_dsh_setting_changed)
        dv.addWidget(self.chk_dsh_enable)
        self.chk_mention = QCheckBox("群聊必须 @ 机器人才触发（默认开启）")
        self.chk_mention.toggled.connect(self._on_dsh_setting_changed)
        dv.addWidget(self.chk_mention)

        # 主流程只留一行按钮，文案跟着状态变：装 → 启动 → 停止
        dctl_row = QHBoxLayout()
        dctl_row.setSpacing(8)
        self._dsh_reinstall = False
        self.btn_dsh_install = QPushButton("重装 dsh")
        self.btn_dsh_install.setObjectName("ghost")
        self.btn_dsh_install.clicked.connect(self._install_dsh)
        self.btn_dsh_toggle = QPushButton("启动 dsh")
        self.btn_dsh_toggle.setObjectName("primary")
        self.btn_dsh_toggle.clicked.connect(self._toggle_dsh)
        self.btn_dsh_stop = QPushButton("停止 dsh")
        self.btn_dsh_stop.setObjectName("ghost")
        self.btn_dsh_stop.clicked.connect(self._stop_dsh)
        for b in (self.btn_dsh_install, self.btn_dsh_toggle, self.btn_dsh_stop):
            dctl_row.addWidget(b)
        dctl_row.addStretch(1)
        dv.addLayout(dctl_row)
        self._dsh_install_tid = ""

        # 次要项（模型覆盖 / Node.js / 日志）收进折叠区，默认不占版面
        dsh_adv = QWidget()
        av = QVBoxLayout(dsh_adv)
        av.setContentsMargins(0, 0, 0, 0)
        av.setSpacing(8)
        self.edit_dsh_model = QLineEdit()
        self.edit_dsh_model.setPlaceholderText("留空 = 跟随 AI 大脑模型")
        self.edit_dsh_model.setMinimumWidth(220)
        self.edit_dsh_key = QLineEdit()
        self.edit_dsh_key.setPlaceholderText("留空 = 跟随 AI 大脑 API Key")
        self.edit_dsh_key.setEchoMode(QLineEdit.Password)
        self.edit_dsh_key.setMinimumWidth(220)
        for w in (self.edit_dsh_model, self.edit_dsh_key):
            w.editingFinished.connect(self._on_dsh_setting_changed)
        av.addLayout(make_row("模型覆盖", self.edit_dsh_model))
        av.addLayout(make_row("API Key 覆盖", self.edit_dsh_key))
        arow = QHBoxLayout()
        arow.setSpacing(8)
        self.btn_dsh_pick_node = QPushButton("选择 node.exe")
        self.btn_dsh_pick_node.setObjectName("ghost")
        self.btn_dsh_pick_node.clicked.connect(self._pick_node)
        self.btn_dsh_log = QPushButton("打开 dsh 日志")
        self.btn_dsh_log.setObjectName("ghost")
        self.btn_dsh_log.clicked.connect(self._open_dsh_log)
        for b in (self.btn_dsh_pick_node, self.btn_dsh_log):
            arow.addWidget(b)
        arow.addStretch(1)
        av.addLayout(arow)
        adv_hint = QLabel("这一栏改动会自动保存；dsh 已在运行时点「重装 / 重启」才会生效。")
        adv_hint.setWordWrap(True)
        adv_hint.setStyleSheet(f"color: {TEXT_3}; font-size: 12px;")
        av.addWidget(adv_hint)
        self.dsh_fold = _Fold("高级选项：模型 / Node.js / 日志　▾",
                              "高级选项：模型 / Node.js / 日志　▴", dsh_adv)
        dv.addWidget(self.dsh_fold)
        outer.addWidget(dsh_glass)
        self._sync_dsh_visibility()

        task_glass = GlassPanel(strong=True)
        tv = QVBoxLayout(task_glass)
        tv.setContentsMargins(16, 12, 16, 14)
        tl = QLabel("服务任务")
        tl.setObjectName("sectionTitle")
        tv.addWidget(tl)
        self.task_panel = TaskPanel(self.ctx.tasks)
        self.task_panel.setVisible(False)
        self.task_panel.action_requested.connect(self._on_task_action)
        tv.addWidget(self.task_panel)
        outer.addWidget(task_glass)
        outer.addStretch(1)
        self.scroll.setWidget(content)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self.scroll)

    def _connect_tasks(self):
        t = self.ctx.tasks
        t.started.connect(self._on_service_started)
        t.finished.connect(self._on_service_finished)

    def _on_service_started(self, tid, name):
        if name in ("启动服务", "停止服务", "重启 NoneBot", "安装 dsh 通道", "重装 dsh 通道",
                    "启动 dsh", "停止 dsh", "重启 dsh"):
            self._service_tid = tid
            self.task_panel.bind(tid)
            self.task_panel.setVisible(True)

    def _on_service_finished(self, tid, status, result):
        if tid == self._service_tid:
            self.task_panel.bind(tid)
        if tid and tid == getattr(self, "_dsh_install_tid", ""):
            self._dsh_install_tid = ""
            if status == "success":
                self._after_dsh_install()
        self.refresh_status()

    def _after_dsh_install(self):
        """装完 dsh 就地接着走：勾上启用、写好配置，条件够就直接拉起来。

        以前这里只留一句「重启全部服务后生效」，界面上根本没有那个按钮，
        用户看到的就是 dsh 永远停在「已安装 · 未运行」。
        """
        s = self.ctx.settings
        if not dsh_mod.is_installed(s):
            return
        if not self.chk_dsh_enable.isChecked():
            self.chk_dsh_enable.setChecked(True)
            self._save_dsh(quiet=True)
        if self.ctx.manager.dsh_running():
            return
        if not (s.qq_official_appid and s.qq_official_secret):
            self.ctx.show_toast(
                "dsh 装好了：先在上面填 QQ 官方机器人的 AppID / AppSecret，再点「启动 dsh」")
            return
        ai = ai_config.current_config(s) or {}
        if not ((s.dsh_api_key or "").strip() or (ai.get("api_key") or "")):
            self.ctx.show_toast(
                "dsh 装好了：先去「AI 大脑」填模型 API Key，再点「启动 dsh」")
            return
        self.ctx.show_toast("dsh 装好了，正在自动启动 ...")
        self._start_dsh()

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

    def _restart_bot(self):
        self.ctx.tasks.submit(
            "重启 NoneBot", "service", RestartBotTask,
            retryable=True, manager=self.ctx.manager,
        )

    def _install_dsh(self):
        self._dsh_install_tid = self.ctx.tasks.submit(
            ("重装 dsh 通道" if self._dsh_reinstall else "安装 dsh 通道"),
            "service", InstallDshTask,
            payload={"reinstall": self._dsh_reinstall},
            settings=self.ctx.settings, manager=self.ctx.manager, retryable=True,
        )

    def _start_dsh(self):
        """只启动 dsh 通道；没装就自动装、没勾「启用」就顺手勾上。

        用户视角只有一件事：让 QQ 群聊 AI 跑起来。所以这里不弹「先去装」，
        而是直接走安装任务，装完由 _after_dsh_install 接着自动启动。
        """
        if str(getattr(self.ctx.settings, "qq_channel", "") or "").lower() == "onebot":
            self.ctx.show_toast(
                "当前是第三方 OneBot 通道：dsh 只支持 QQ 官方，先切回官方再启动")
            return
        if not self.chk_dsh_enable.isChecked():
            self.chk_dsh_enable.setChecked(True)
            self._save_dsh(quiet=True)
        if not dsh_mod.is_installed(self.ctx.settings):
            self.ctx.show_toast("dsh 还没装：正在自动安装，装好后会自动启动 ...", 3200)
            self._install_dsh()
            return
        self.ctx.tasks.submit(
            "启动 dsh", "service", DshControlTask,
            payload={"action": "start"}, settings=self.ctx.settings,
            manager=self.ctx.manager, retryable=True,
        )

    def _on_dsh_setting_changed(self, *_args):
        """勾选框 / 输入框一改就存盘（省掉「保存 dsh 设置」按钮）。"""
        if getattr(self, "_dsh_loading", False):
            return
        self._save_dsh(quiet=True)

    def _toggle_dsh(self):
        """运行中就重启，没运行就启动；只动 dsh，不碰 NoneBot。"""
        if self.ctx.manager.dsh_running():
            self.ctx.tasks.submit(
                "重启 dsh", "service", DshControlTask,
                payload={"action": "restart"}, settings=self.ctx.settings,
                manager=self.ctx.manager, retryable=True,
            )
        else:
            self._start_dsh()

    def _stop_dsh(self):
        if not self.ctx.manager.dsh_running():
            self.ctx.show_toast("dsh 当前没有在运行")
            return
        self.ctx.tasks.submit(
            "停止 dsh", "service", DshControlTask,
            payload={"action": "stop"}, settings=self.ctx.settings,
            manager=self.ctx.manager, retryable=True,
        )

    def _pick_node(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 node.exe", "", "node.exe (node.exe)")
        if not path:
            return
        self.ctx.settings.dsh_node_exe = path
        try:
            self.ctx.settings.save()
        except OSError as e:
            self.ctx.show_toast("保存 Node.js 路径失败: " + str(e))
            return
        self.ctx.show_toast("已指定 Node.js：" + path)
        self.refresh_status()

    def _open_dsh_log(self):
        try:
            import os
            os.startfile(str(dsh_mod.dsh_log(self.ctx.settings)))
        except OSError as e:
            self.ctx.show_toast("无法打开 dsh 日志: " + str(e))

    def _open_tutorial(self):
        """打开内置的 LLOneBot 接入教程（带免责声明）。"""
        if getattr(self, "_tutorial_dialog", None) is None:
            from .tutorial_dialog import TutorialDialog
            self._tutorial_dialog = TutorialDialog(self)
        self._tutorial_dialog.show()
        self._tutorial_dialog.raise_()
        self._tutorial_dialog.activateWindow()

    def _save_dsh(self, quiet=False):
        s = self.ctx.settings
        s.dsh_enabled = self.chk_dsh_enable.isChecked()
        s.dsh_require_mention = self.chk_mention.isChecked()
        s.dsh_model = self.edit_dsh_model.text().strip()
        s.dsh_api_key = self.edit_dsh_key.text().strip()
        if s.dsh_enabled and str(getattr(s, "qq_channel", "") or "").lower() == "onebot":
            self.ctx.show_toast(
                "当前是第三方 OneBot 通道：dsh 只支持 QQ 官方，先切回「QQ 官方机器人」")
            s.dsh_enabled = False
            self.chk_dsh_enable.setChecked(False)
            return
        if s.dsh_enabled and not (
            s.qq_official_appid and s.qq_official_secret
        ):
            self.ctx.show_toast("dsh 仅支持 QQ 官方通道：请先选择「QQ 官方机器人」并填写凭证")
            s.dsh_enabled = False
            self.chk_dsh_enable.setChecked(False)
            return
        try:
            s.save()
        except OSError as e:
            self.ctx.show_toast("保存 dsh 设置失败: " + str(e))
            return
        wrote = dsh_mod.write_config(s, log=lambda line: None)
        if quiet:
            self.refresh_status()
            return
        if s.dsh_enabled and not dsh_mod.is_installed(s):
            self.ctx.show_toast("dsh 设置已保存，但 dsh 尚未安装：点「安装并启动 dsh」会自动装好")
        elif s.dsh_enabled and not wrote:
            self.ctx.show_toast("dsh 设置已保存，但写入 dsh 配置失败：点「安装并启动 dsh」重装一次")
        elif s.dsh_enabled and not self.ctx.manager.dsh_running():
            self.ctx.show_toast("dsh 设置已保存，点「启动 dsh」立即生效（不用重启其它服务）")
        else:
            self.ctx.show_toast("dsh 设置已保存" + ("（正在运行，点「重启 dsh」生效）" if s.dsh_enabled else ""))
        self.refresh_status()

    def load_credentials(self):
        s = self.ctx.settings
        # 灌数据期间勾选框会发 toggled：先关上自动保存，别把「回显」当成「用户改的」
        self._dsh_loading = True
        try:
            self.chk_dsh_enable.setChecked(s.dsh_enabled)
            self.chk_mention.setChecked(s.dsh_require_mention)
            self.edit_dsh_model.setText(s.dsh_model)
            self.edit_dsh_key.setText(s.dsh_api_key)
        finally:
            self._dsh_loading = False
        self.qq_panel.load_credentials()
        self._sync_dsh_visibility()

    def _on_channel_changed(self, channel=""):
        """接入方式切换回调（来自共用面板）：dsh 卡片显隐 + 状态卡小字跟着通道走。"""
        self._sync_dsh_visibility(channel)
        self._sync_channel_tip(channel)

    def _on_channel_saved(self):
        """通道存盘后：dsh 可能被自动关掉（切第三方），勾选状态要跟着走。"""
        self.chk_dsh_enable.setChecked(bool(self.ctx.settings.dsh_enabled))
        self.refresh_status()

    def _sync_dsh_visibility(self, channel=""):
        """dsh 卡片只在官方通道下有意义；已经启用过的保持可见，别把关闭入口藏掉。"""
        glass = getattr(self, "dsh_glass", None)
        if glass is None:
            return
        s = self.ctx.settings
        ch = str(channel or getattr(s, "qq_channel", "") or "official")
        glass.setVisible(ch == "official" or bool(s.dsh_enabled))

    def _sync_channel_tip(self, channel=""):
        """状态卡的小字提示跟通道走：官方讲凭证与沙箱，第三方讲协议端自备。"""
        s = self.ctx.settings
        ch = str(channel or getattr(s, "qq_channel", "") or "official")
        if ch == "official":
            self.qq_tip.setText(
                "官方通道不用扫码：在 q.qq.com 建好机器人，填下面的 AppID / Token / AppSecret，"
                "重启后 NoneBot 自己连上去；先拿沙箱环境联调，正式上线要过平台审核。")
        else:
            self.qq_tip.setText(
                "协议端由你自行安装并扫码登录（例如 LLOneBot / Lagrange），"
                "AstroSwarm 只负责连接，不内置、不分发任何协议端；使用第三方协议有账号风险，请自备小号。")

    def _save_creds(self):
        """兼容入口：真正的保存逻辑在共用面板里（含 .env 同步与重启提示）。"""
        self.qq_panel._save_creds()

    def refresh_status(self):
        s = self.ctx.settings
        m = self.ctx.manager
        bot_on = m.bot_running()
        qq_on = m.qq_running()
        self.bot_badge.set_status("running" if bot_on else "stopped",
                                  "NoneBot · " + ("运行中" if bot_on else "已停止"))
        self.bot_port.setText(str(s.nonebot_port))
        self.bot_py.setText(str(s.python_exe))
        self.bot_pid.setText("已记录 PID" if bot_on else "—")

        st = m.qq_login_state()
        is_onebot = s.qq_channel == "onebot"
        reverse = is_onebot and str(
            getattr(s, "qq_onebot_mode", "") or "reverse"
        ).lower() == "reverse"
        self.qq_badge.set_status("running" if qq_on else "stopped",
                                 ("QQ OneBot · " if is_onebot else "QQ 官方 · ")
                                 + ("运行中" if qq_on else "已停止"))
        self.qq_appid.setText(str(st.get("account") or "未配置"))
        self.qq_appid_label.setText(
            "反向地址" if reverse else ("地址/端口" if is_onebot else "AppID")
        )
        self.qq_mode.setText(
            ("第三方 OneBot（反向 WS）" if reverse else "第三方 OneBot（正向 WS）")
            if is_onebot else "QQ 官方机器人"
        )
        self.qq_state.setText(str(st.get("reason") or "未知"))
        self._refresh_reverse_url()
        self._sync_dsh_visibility()
        self._sync_channel_tip()

        dst = m.dsh_status()
        self.dsh_badge.set_status(
            "running" if dst["running"] else ("stopped" if dst["installed"] else "unknown"),
            "dsh · " + (("已连接" if dst["connected"] else "运行中") if dst["running"] else ("未安装" if not dst["installed"] else "已停止")),
        )
        node_hint = dst["node"] or "未检测到（安装时自动下载便携版）"
        self.dsh_node_lbl.setText(node_hint)
        self.dsh_state_lbl.setText(dst["reason"])
        self.dsh_model_lbl.setText(s.dsh_model or "跟随 AI 大脑")
        toggle = getattr(self, "btn_dsh_toggle", None)
        installed = bool(dst["installed"])
        running = bool(dst["running"])
        if toggle is not None:
            # 一个按钮走完全流程：没装 = 安装并启动；装了 = 启动 / 重启
            toggle.setText("重启 dsh" if running
                           else ("启动 dsh" if installed else "安装并启动 dsh"))
            toggle.setEnabled(True)
        stop_btn = getattr(self, "btn_dsh_stop", None)
        if stop_btn is not None:
            stop_btn.setEnabled(running)
        # dsh 已完整安装时：按钮变灰为“重装 dsh”（点击先卸载再重装）
        healthy = installed
        self._dsh_reinstall = healthy
        self.btn_dsh_install.setText("重装 dsh" if healthy else "安装/修复 dsh")
        self.btn_dsh_install.setObjectName("ghost" if healthy else "primary")
        btn_style = self.btn_dsh_install.style()
        btn_style.unpolish(self.btn_dsh_install)
        btn_style.polish(self.btn_dsh_install)
        self.btn_dsh_install.update()
        self.btn_dsh_install.setEnabled(True)
        # 没装时主按钮已经写着「安装并启动 dsh」，旁边不再重复一个安装按钮
        self.btn_dsh_install.setVisible(healthy)
        self.chk_dsh_enable.setEnabled(True)
