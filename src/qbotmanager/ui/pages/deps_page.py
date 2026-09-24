"""依赖管理：全量扫描插件依赖 -> 实时反馈缺失清单 -> 一键安装缺失依赖。"""
import os

from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QListWidget, QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from ...tasks.workers import CheckDepsTask, InstallPluginTask
from ..theme import TEXT_3
from ..widgets import GlassPanel
from .common import PageContext, TaskPanel

DEPS_TASK_NAMES = ("检查插件依赖", "安装依赖")


class DepsPage(QWidget):
    def __init__(self, ctx: PageContext):
        super().__init__()
        self.ctx = ctx
        self._task_tid = None
        self._missing = []
        self._last_summary = "尚未扫描"
        self._build_ui()
        self._connect_tasks()

    # ------------------------------------------------------------ UI
    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(14)

        title = QLabel("依赖管理")
        title.setObjectName("pageTitle")
        sub = QLabel("扫描 src/plugins 下所有插件声明的依赖，检测缺失并一键安装（清华镜像，失败自动切官方源）")
        sub.setObjectName("pageSub")
        outer.addWidget(title)
        outer.addWidget(sub)

        # ---- 扫描区 ----
        scan = GlassPanel()
        sv = QVBoxLayout(scan)
        sv.setContentsMargins(18, 14, 18, 16)
        self.summary = QLabel("尚未扫描")
        self.summary.setObjectName("value")
        sv.addWidget(self.summary)
        hint = QLabel("扫描过程在后台任务中执行，页面不会卡顿；发现缺失依赖后会显示在下方清单中。")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {TEXT_3}; font-size: 12px;")
        sv.addWidget(hint)
        row = QHBoxLayout()
        self.btn_scan = QPushButton("开始全量扫描")
        self.btn_scan.setObjectName("primary")
        self.btn_scan.clicked.connect(self._scan)
        btn_open = QPushButton("打开插件目录")
        btn_open.clicked.connect(lambda: os.startfile(str(self.ctx.settings.plugins_dir)))
        row.addWidget(self.btn_scan)
        row.addWidget(btn_open)
        row.addStretch(1)
        sv.addLayout(row)
        outer.addWidget(scan)

        # ---- 缺失清单 ----
        missing_panel = GlassPanel(strong=True)
        mv = QVBoxLayout(missing_panel)
        mv.setContentsMargins(18, 14, 18, 16)
        ml = QLabel("缺失依赖")
        ml.setObjectName("sectionTitle")
        mv.addWidget(ml)
        self.missing_list = QListWidget()
        mv.addWidget(self.missing_list, 1)
        mrow = QHBoxLayout()
        self.btn_install = QPushButton("安装缺失依赖")
        self.btn_install.setObjectName("primary")
        self.btn_install.setEnabled(False)
        self.btn_install.clicked.connect(self._install_missing)
        mrow.addWidget(self.btn_install)
        mrow.addStretch(1)
        mv.addLayout(mrow)
        outer.addWidget(missing_panel, 1)

        # ---- 任务面板 ----
        task_glass = GlassPanel()
        tv = QVBoxLayout(task_glass)
        tv.setContentsMargins(16, 12, 16, 14)
        tl = QLabel("依赖任务")
        tl.setObjectName("sectionTitle")
        tv.addWidget(tl)
        self.task_panel = TaskPanel(self.ctx.tasks)
        self.task_panel.setVisible(False)
        self.task_panel.action_requested.connect(self._on_task_action)
        tv.addWidget(self.task_panel)
        outer.addWidget(task_glass)

    def _connect_tasks(self):
        t = self.ctx.tasks
        t.started.connect(self._on_task_started)
        t.finished.connect(self._on_task_finished)

    # ------------------------------------------------------------ 任务
    def _on_task_started(self, tid, name):
        if name in DEPS_TASK_NAMES:
            self._task_tid = tid
            self.task_panel.bind(tid)
            self.task_panel.setVisible(True)

    def _on_task_finished(self, tid, status, result):
        if tid != self._task_tid:
            return
        self.task_panel.bind(tid)
        st = self.ctx.tasks.get(tid)
        name = st.task_name if st else ""
        if status == "success" and name == "检查插件依赖":
            self._missing = list(result.get("missing") or [])
            checked = result.get("checked") or 0
            self._last_summary = f"上次扫描：共检查 {checked} 项依赖，缺失 {len(self._missing)} 项"
            self.summary.setText(self._last_summary)
            self._render_missing()
        elif status == "success" and name == "安装依赖":
            self.summary.setText(self._last_summary + "；缺失依赖已安装，建议重新扫描验证")
            self.ctx.show_toast("依赖安装完成，建议重新扫描验证")
        elif status == "failed":
            self.ctx.show_toast("任务失败，可在任务面板查看错误详情")

    def _on_task_action(self, action, task_id):
        if action == "cancel":
            self.ctx.tasks.cancel(task_id)
        elif action == "retry":
            new_id = self.ctx.tasks.retry(task_id)
            if new_id:
                self.task_panel.bind(new_id)
        elif action == "logs":
            self.ctx.open_logs()

    # ------------------------------------------------------------ 操作
    def _scan(self):
        if self.ctx.tasks.has_active("install"):
            QMessageBox.information(self, "提示", "已有安装/扫描任务正在执行，请稍候")
            return
        self._missing = []
        self.summary.setText("正在后台扫描插件依赖 ...")
        self._render_missing()
        self.ctx.tasks.submit(
            "检查插件依赖", "install", CheckDepsTask,
            payload={"mode": "all"}, retryable=True, settings=self.ctx.settings,
        )

    def _install_missing(self):
        if not self._missing:
            QMessageBox.information(self, "提示", "当前没有缺失依赖")
            return
        if self.ctx.tasks.has_active("install"):
            QMessageBox.information(self, "提示", "已有安装/扫描任务正在执行，请稍候")
            return
        self.ctx.tasks.submit(
            "安装依赖", "install", InstallPluginTask,
            payload={"kind": "deps", "target": list(self._missing)},
            retryable=True, settings=self.ctx.settings,
        )

    def _render_missing(self):
        self.missing_list.clear()
        for d in self._missing:
            self.missing_list.addItem(d)
        self.btn_install.setEnabled(bool(self._missing))