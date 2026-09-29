"""日志：统一日志流（任务 + 管理器信号实时流，NoneBot 日志文件尾部跟随）。

页面维护一条带上限的全局日志流水线，按“来源 / 级别”过滤后增量渲染，
不阻塞 UI；清空只清视图，服务文件下次 tick 会继续读取新内容。
"""
import os
import re
import sys
import threading
import time

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton,
    QVBoxLayout, QWidget,
)

from ...core import log_export
from ..theme import MONO_FAMILY, TEXT_3
from ..widgets import GlassPanel
from .common import Worker

LEVELS = ("全部", "INFO", "OK", "WARN", "ERROR")
# 文件来源：磁盘上实际一直在写的 5 份日志（与 core/cleanup._LOG_FILES 对齐）。
# 以前页面只跟随 nonebot.log，manager / deploy / dsh / liqinghan 四份日志在界面上完全看不到。
FILE_SOURCES = (
    ("NoneBot", "nonebot.log"),
    ("管理器", "manager.log"),
    ("部署", "deploy.log"),
    ("星群助手", "dsh.log"),
    ("李清菡", "liqinghan.log"),
)
SOURCES = ("全部", "任务") + tuple(label for label, _ in FILE_SOURCES)
MAX_MASTER = 12000
TAIL_MAX_BYTES = 256 * 1024  # 首次跟随最多读日志尾部 256KB，防止大文件一次性拖死 UI
RENDER_BATCH = 300           # 渲染时分批 append，避免一次几万行阻塞界面


def _infer_level(line: str) -> str:
    low = line.lower()
    if "error" in low or "traceback" in low or "exception" in low or "failed" in low:
        return "ERROR"
    if "warn" in low:
        return "WARN"
    if "success" in low or "ok" in low or "完成" in low:
        return "OK"
    return "INFO"


class LogsPage(QWidget):
    def __init__(self, ctx, log_bus):
        super().__init__()
        self.ctx = ctx
        self.log_bus = log_bus
        self._entries = []          # (ts, source, level, msg)
        self._file_offsets = {}     # path -> bytes
        self._src_filter = "全部"
        self._lv_filter = "全部"
        self._build_ui()
        log_bus.entry.connect(self._on_log_entry)
        self.timer = QTimer(self)
        self.timer.setInterval(1500)
        self.timer.timeout.connect(self._tail_files)
        self.timer.start()

    # ------------------------------------------------------------ UI
    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(14)

        title = QLabel("日志")
        title.setObjectName("pageTitle")
        sub = QLabel("任务与管理器日志实时推送；机器人、部署、星群助手、李清菡四类日志跟随文件尾部")
        sub.setObjectName("pageSub")
        outer.addWidget(title)
        outer.addWidget(sub)

        panel = GlassPanel(strong=True)
        pv = QVBoxLayout(panel)
        pv.setContentsMargins(16, 12, 16, 14)

        bar = QHBoxLayout()
        bar.addWidget(self._make_caption("来源"))
        self.src_combo = QComboBox()
        self.src_combo.addItems(SOURCES)
        self.src_combo.currentTextChanged.connect(self._on_filter_changed)
        bar.addWidget(self.src_combo)
        bar.addSpacing(12)
        bar.addWidget(self._make_caption("级别"))
        self.lv_combo = QComboBox()
        self.lv_combo.addItems(LEVELS)
        self.lv_combo.currentTextChanged.connect(self._on_filter_changed)
        bar.addWidget(self.lv_combo)
        bar.addStretch(1)
        self.btn_export = QPushButton("导出日志")
        self.btn_export.setToolTip(
            "按上面的「来源」导出：选具体日志就导出那一份；选「全部」把五份日志尾部拼成一份；"
            "选「任务」导出当前界面里看到的这份流水")
        self.btn_export.clicked.connect(self._export_logs)
        btn_open = QPushButton("打开日志目录")
        btn_open.clicked.connect(self._open_logs_dir)
        btn_clear = QPushButton("清空视图")
        btn_clear.clicked.connect(self._clear_view)
        bar.addWidget(self.btn_export)
        bar.addWidget(btn_open)
        bar.addWidget(btn_clear)
        pv.addLayout(bar)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(8000)
        self.log_view.setStyleSheet(
            f"font-family: {MONO_FAMILY}; font-size: 12px;"
            "background: rgba(8,11,18,0.72); border: 1px solid rgba(255,255,255,0.08);"
            "border-radius: 10px; padding: 10px; color: #C6D0E0;")
        self.log_view.setLineWrapMode(QPlainTextEdit.NoWrap)
        pv.addWidget(self.log_view, 1)
        outer.addWidget(panel, 1)

    @staticmethod
    def _make_caption(text):
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color: {TEXT_3}; font-size: 12px;")
        return lbl

    def _open_logs_dir(self):
        """打开日志目录：Windows 用资源管理器，其余平台退回系统默认方式。"""
        path = str(self.ctx.settings.logs_dir)
        try:
            if hasattr(os, "startfile"):        # Windows
                os.startfile(path)              # noqa: S606
            else:
                import subprocess

                opener = "open" if sys.platform == "darwin" else "xdg-open"
                subprocess.Popen([opener, path])
        except OSError:
            pass

    # ------------------------------------------------------------ 导出
    def _export_source_key(self):
        """当前「来源」对应的日志名；「全部」「任务」不是文件来源时返回空串。"""
        label = self.src_combo.currentText()
        for lab, filename in FILE_SOURCES:
            if lab == label:
                return filename[:-len(".log")]
        return ""

    def _export_logs(self):
        """导出日志（无头端是 /api/logs/download，桌面端存成本地文件）。

        读盘交给 Worker 线程：日志可能有几百兆，在主线程里读会把界面卡住。
        """
        label = self.src_combo.currentText()
        key = self._export_source_key()
        stamp = time.strftime("%Y%m%d-%H%M%S")
        want_all = not key and label != "任务"
        base = "all" if want_all else (key or "tasks")
        default_path = str(self.ctx.settings.logs_dir / log_export.suggested_filename(base, stamp))
        path, _ = QFileDialog.getSaveFileName(
            self, "导出日志", default_path,
            "日志文件 (*.log);;文本文件 (*.txt);;全部文件 (*)")
        if not path:
            return
        if label == "任务":
            # 任务 / 管理器日志是内存流水（没有对应的文件），导出当前视图
            text = self.log_view.toPlainText()
            try:
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(text)
            except OSError as e:
                self.ctx.show_toast("导出失败：" + str(e))
                return
            self.ctx.show_toast(f"已导出当前视图（{len(text.splitlines())} 行）")
            return
        logs_dir = self.ctx.settings.logs_dir
        self.ctx.show_toast("正在导出日志…")
        worker = Worker(self)
        worker.finished.connect(self._on_export_done)
        fn = (lambda: log_export.export_all(logs_dir, path)) if want_all \
            else (lambda: log_export.export(logs_dir, key, path))
        threading.Thread(target=lambda: worker.run(fn), daemon=True).start()

    def _on_export_done(self, res):
        if not isinstance(res, dict) or res.get("error"):
            why = (res or {}).get("error") if isinstance(res, dict) else str(res)
            self.ctx.show_toast("导出失败：" + str(why or "未知错误"))
            return
        size = float(res.get("bytes") or 0) / 1024.0
        self.ctx.show_toast(f"已导出日志（{size:.0f} KB）：{os.path.basename(res.get('path') or '')}")

    # ------------------------------------------------------------ 数据
    def _on_log_entry(self, source, level, msg):
        self._add_entry(source, level, str(msg))

    def _add_entry(self, source, level, msg):
        if not msg.strip():
            return
        self._entries.append((time.time(), source, level, msg))
        if len(self._entries) > MAX_MASTER:
            del self._entries[:2000]
            # 不在这里全量重建：视图由 QPlainTextEdit 的 maxBlockCount 自动截断，
            # 过滤条件变化时再重建。避免大日志下 O(n^2) 反复清空重刷导致 UI 卡死。
        if self._matches(source, level):
            self._append_line(source, level, msg)

    def _matches(self, source, level):
        if self._src_filter != "全部" and source != self._src_filter:
            return False
        if self._lv_filter != "全部" and level != self._lv_filter:
            return False
        return True

    def _append_line(self, source, level, msg):
        ts = time.strftime("%H:%M:%S", time.localtime())
        self.log_view.appendPlainText(f"[{ts}] [{source}][{level}] {msg}")

    def _on_filter_changed(self, _text):
        self._src_filter = self.src_combo.currentText()
        self._lv_filter = self.lv_combo.currentText()
        self._rebuild()

    def _rebuild(self):
        self.log_view.clear()
        lines = []
        for ts, source, level, msg in self._entries:
            if self._matches(source, level):
                stamp = time.strftime("%H:%M:%S", time.localtime(ts))
                lines.append(f"[{stamp}] [{source}][{level}] {msg}")
                if len(lines) >= RENDER_BATCH:
                    self.log_view.appendPlainText("\n".join(lines))
                    lines = []
        if lines:
            self.log_view.appendPlainText("\n".join(lines))
        sb = self.log_view.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _clear_view(self):
        self.log_view.clear()

    # ------------------------------------------------------------ 文件尾部
    def _tail_files(self):
        logs = self.ctx.settings.logs_dir
        for source, name in FILE_SOURCES:
            path = logs / name
            try:
                if not path.exists():
                    continue
                size = path.stat().st_size
                key = str(path)
                offset = self._file_offsets.get(key, 0)
                if size < offset:
                    offset = 0  # 日志被清空/轮转
                if size == offset:
                    continue
                # 首次跟随只读文件尾部，避免一次吞下整份大日志阻塞 UI 线程
                if offset == 0 and size > TAIL_MAX_BYTES:
                    offset = size - TAIL_MAX_BYTES
                with open(path, "rb") as f:
                    f.seek(offset)
                    raw = f.read()
                self._file_offsets[key] = size
            except OSError:
                continue
            text = re.sub(r"\x1b\[[0-9;]*m", "", raw.decode("utf-8", errors="replace"))
            lines = [line.rstrip() for line in text.splitlines() if line.strip()]
            if not lines:
                continue
            # 增量并入全局流水线（带上限裁剪，不做全量重建）
            now = time.time()
            self._entries.extend((now, source, _infer_level(line), line) for line in lines)
            if len(self._entries) > MAX_MASTER:
                del self._entries[:len(self._entries) - MAX_MASTER]
            # 分批渲染符合当前过滤条件的行
            matched = []
            stamp = time.strftime("%H:%M:%S", time.localtime(now))
            for line in lines:
                level = _infer_level(line)
                if self._matches(source, level):
                    matched.append(f"[{stamp}] [{source}][{level}] {line}")
                    if len(matched) >= RENDER_BATCH:
                        self.log_view.appendPlainText("\n".join(matched))
                        matched = []
            if matched:
                self.log_view.appendPlainText("\n".join(matched))
