"""页面公共设施：上下文、任务面板、依赖确认弹窗。"""
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QHBoxLayout, QLabel, QListWidget,
    QPushButton, QVBoxLayout,
)

from ..theme import TEXT_2, TEXT_3
from ..widgets import GlassPanel, StatusBadge, TaskProgressBar


class PageContext:
    """页面需要的全部外部能力，避免页面直接依赖 MainWindow。"""

    def __init__(self, settings, manager, tasks, callbacks=None):
        self.settings = settings
        self.manager = manager
        self.tasks = tasks
        callbacks = callbacks or {}
        self.open_logs = callbacks.get("open_logs") or (lambda: None)
        self.open_webui = callbacks.get("open_webui") or (lambda: None)
        self.show_toast = callbacks.get("show_toast") or (lambda *a, **k: None)
        self.switch_page = callbacks.get("switch_page") or (lambda *a: None)
        self.open_account = callbacks.get("open_account") or (lambda: None)
        self.apply_appearance = callbacks.get("apply_appearance") or (lambda: None)
        self.set_beginner_mode = callbacks.get("set_beginner_mode") or (lambda *a, **k: None)
        self.bg_status = callbacks.get("bg_status") or (lambda: None)


class Worker(QObject):
    """后台线程桥：把耗时函数放到线程跑，结果经信号回到主线程。"""

    finished = Signal(object)

    def run(self, fn):
        try:
            result = fn()
        except Exception as e:  # noqa: BLE001
            result = {"error": str(e)}
        self.finished.emit(result)


class TaskPanel(GlassPanel):
    """一个任务的实时展示面板：名称/状态/阶段/进度/日志/操作。

    bind(task_id) 后自动订阅 TaskManager 信号并渲染。
    """
    action_requested = Signal(str, str)   # ("cancel"|"retry"|"logs", task_id)

    def __init__(self, tasks, parent=None):
        super().__init__(parent, strong=True)
        self.tasks = tasks
        self.task_id = None
        self._bound = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(8)

        head = QHBoxLayout()
        self.name_label = QLabel("—")
        self.name_label.setStyleSheet(f"color: {TEXT_2}; font-size: 14px; font-weight: 600;")
        head.addWidget(self.name_label, 1)
        self.badge = StatusBadge("待执行", "pending")
        head.addWidget(self.badge)
        lay.addLayout(head)

        self.stage_label = QLabel("")
        self.stage_label.setStyleSheet(f"color: {TEXT_3}; font-size: 12px;")
        lay.addWidget(self.stage_label)

        self.progress = TaskProgressBar()
        lay.addWidget(self.progress)

        self.log_preview = QLabel("")
        self.log_preview.setWordWrap(True)
        self.log_preview.setStyleSheet(
            "color: #9FB0C8; font-size: 12px; background: rgba(9,12,19,0.5);"
            "border-radius: 6px; padding: 6px 8px;")
        lay.addWidget(self.log_preview)

        btns = QHBoxLayout()
        btns.addStretch(1)
        self.btn_logs = QPushButton("查看日志")
        self.btn_logs.setObjectName("ghost")
        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.setObjectName("ghost")
        self.btn_retry = QPushButton("重试")
        self.btn_retry.setObjectName("primary")
        self.btn_logs.clicked.connect(lambda: self.action_requested.emit("logs", self.task_id or ""))
        self.btn_cancel.clicked.connect(lambda: self.action_requested.emit("cancel", self.task_id or ""))
        self.btn_retry.clicked.connect(lambda: self.action_requested.emit("retry", self.task_id or ""))
        btns.addWidget(self.btn_logs)
        btns.addWidget(self.btn_cancel)
        btns.addWidget(self.btn_retry)
        lay.addLayout(btns)

        self._state = None
        self._connect_tasks()

    def _connect_tasks(self):
        t = self.tasks
        t.started.connect(self._on_started)
        t.stage_changed.connect(self._on_stage)
        t.progress_changed.connect(self._on_progress)
        t.log.connect(self._on_log)
        t.status_changed.connect(self._on_status)
        t.error.connect(self._on_error)
        t.finished.connect(self._on_finished)

    def bind(self, task_id):
        self.task_id = task_id
        state = self.tasks.get(task_id)
        self._state = state
        if state is not None:
            self._render_state(state)
        else:
            # 任务已结束（状态已移除）：清空面板并停掉忙碌动画
            self.clear()

    def clear(self):
        self.task_id = None
        self._state = None
        self.name_label.setText("—")
        self.badge.set_status("pending", "待执行")
        self.stage_label.setText("")
        self.progress.set_smooth(0)
        self.log_preview.setText("")

    def _on_started(self, tid, name):
        if tid == self.task_id:
            self.name_label.setText(name)
            self.badge.set_status("running", "执行中")

    def _on_stage(self, tid, stage, current, total, message):
        if tid != self.task_id:
            return
        parts = [stage]
        if total and total > 0:
            parts.append(f"{current} / {total}")
        if message:
            parts.append("· " + message)
        self.stage_label.setText("  ".join(parts))

    def _on_progress(self, tid, pct):
        if tid == self.task_id:
            self.progress.set_smooth(pct)

    def _on_log(self, tid, level, msg):
        if tid != self.task_id:
            return
        lines = self.log_preview.text().splitlines()
        lines.append(msg)
        if len(lines) > 3:
            lines = lines[-3:]
        self.log_preview.setText("\n".join(lines))

    def _on_status(self, tid, status):
        if tid != self.task_id:
            return
        if status == "running":
            self.badge.set_status("running", "执行中")
        elif status == "pending":
            self.badge.set_status("pending", "排队中")

    def _on_error(self, tid, stage, msg):
        if tid != self.task_id:
            return
        self.badge.set_status("failed", "失败")
        self.log_preview.setText("✕ " + msg)

    def _on_finished(self, tid, status, result):
        if tid != self.task_id:
            return
        self._state = self.tasks.get(tid)
        self._render_state(self._state)

    def _render_state(self, state):
        if state is None:
            self.clear()
            return
        self.name_label.setText(state.task_name)
        if state.status.value == "running":
            self.badge.set_status("running", "执行中")
        elif state.status.value == "success":
            self.badge.set_status("success", "已完成")
        elif state.status.value == "failed":
            self.badge.set_status("failed", "失败")
        elif state.status.value == "cancelled":
            self.badge.set_status("pending", "已取消")
        else:
            self.badge.set_status("pending", "排队中")
        if state.current_stage:
            parts = [state.current_stage]
            if state.total and state.total > 0:
                parts.append(f"{state.current} / {state.total}")
            if state.message:
                parts.append("· " + state.message)
            self.stage_label.setText("  ".join(parts))
        if state.progress >= 0:
            self.progress.set_smooth(state.progress)
        else:
            self.progress.set_smooth(-1)
        if state.error:
            self.log_preview.setText("✕ " + state.error)
        elif state.logs:
            self.log_preview.setText("\n".join(m for _, _, m in state.logs[-3:]))
        running = state.status.value in ("running", "pending")
        self.btn_cancel.setVisible(running)
        self.btn_retry.setVisible(not running and state.retryable and state.status.value == "failed")
        self.btn_logs.setVisible(True)


class DepsConfirmDialog(QDialog):
    """依赖安装确认：安装依赖并解压 / 跳过依赖仅解压 / 取消。"""

    def __init__(self, deps, parent=None):
        super().__init__(parent)
        self.setWindowTitle("检测到插件依赖")
        self.setModal(True)
        self.resize(520, 360)
        lay = QVBoxLayout(self)
        tip = QLabel("插件声明了以下依赖，是否一并安装？\n安装默认使用清华镜像，失败会自动切换官方源重试。")
        tip.setWordWrap(True)
        lay.addWidget(tip)
        box = QListWidget()
        for d in deps:
            box.addItem(d)
        lay.addWidget(box, 1)
        self.never_check = QCheckBox("以后安装 zip 插件不再询问（不推荐）")
        lay.addWidget(self.never_check)
        btns = QHBoxLayout()
        install_btn = QPushButton("安装依赖并解压（推荐）")
        install_btn.setObjectName("primary")
        install_btn.clicked.connect(self.accept)
        skip_btn = QPushButton("跳过依赖，仅解压插件")
        skip_btn.clicked.connect(self.reject)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(lambda: self.done(2))
        btns.addWidget(install_btn)
        btns.addWidget(skip_btn)
        btns.addWidget(cancel_btn)
        lay.addLayout(btns)

    def decision(self):
        r = self.exec()
        if r == QDialog.Accepted:
            return "install", self.never_check.isChecked()
        if r == QDialog.Rejected:
            return "skip", self.never_check.isChecked()
        return "cancel", False


def make_row(label_text, value_widget):
    row = QHBoxLayout()
    lbl = QLabel(label_text)
    lbl.setStyleSheet(f"color: {TEXT_3}; font-size: 12px;")
    row.addWidget(lbl)
    row.addStretch(1)
    row.addWidget(value_widget)
    return row
