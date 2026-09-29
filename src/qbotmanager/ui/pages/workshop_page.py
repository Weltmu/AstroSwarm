# -*- coding: utf-8 -*-
"""插件工坊页：用大白话给机器人加功能。

四步（对齐方案设计 2026-09-27）：
1. 说需求 → 2. 看方案 → 3. 自动生成 + 检查 + 沙箱试跑 → 4. 一键安装。
生成用的模型跟「AI 大脑」完全分开，且只允许强模型（DeepSeek/ChatGPT/Claude/…）；
生成的插件只能跑在沙箱里，动作（发消息/记忆/联网）都由主程序校验后执行。
"""
import threading

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...core import workshop
from ...core.workshop import config as ws_config
from ..theme import TEXT_2, TEXT_3
from ..widgets import GlassPanel
from .common import PageContext, Worker

EXAMPLES = (
    "每天早上 8 点把北京的天气发到群里",
    "群里谁签到就记一次，能查每个人有多少金币",
    "有人发链接的时候，自动抓标题发出来",
    "做一个成语接龙小游戏，记录每个人的得分",
)


class UploadDialog(QDialog):
    """上传插件到官网：选插件 / 填作者名 / 每次都要邮箱验证码。"""

    def __init__(self, settings, installed, current_pid="", parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("上传插件到官网审核")
        self.setMinimumWidth(520)
        self._seconds = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        form = QFormLayout(self)

        tip = QLabel(
            "上传的插件先进入人工审核，通过后才会出现在官网插件市场和所有用户的工坊里。\n"
            "每次上传都要过一次邮箱验证码（防止被恶意刷），插件会带上你的作者名和账号邮箱。")
        tip.setWordWrap(True)
        tip.setStyleSheet(f"color: {TEXT_3}; font-size: 12px;")
        form.addRow(tip)

        self.combo_plugin = QComboBox()
        for row in installed or []:
            self.combo_plugin.addItem(f"{row['name']}（{row['id']}）", row["id"])
        if current_pid:
            idx = self.combo_plugin.findData(current_pid)
            if idx >= 0:
                self.combo_plugin.setCurrentIndex(idx)
        form.addRow("上传哪个插件", self.combo_plugin)

        self.edit_from_file = QLineEdit()
        self.edit_from_file.setPlaceholderText("留空就上传上面选中的插件；也可以选一个 zip 文件传")
        btn_file = QPushButton("选 zip…")
        btn_file.clicked.connect(self._pick_file)
        row_file = QHBoxLayout()
        row_file.addWidget(self.edit_from_file, 1)
        row_file.addWidget(btn_file)
        form.addRow("或者选文件", row_file)

        self.edit_author = QLineEdit(workshop.default_author())
        self.edit_author.setMaxLength(32)
        self.edit_author.setPlaceholderText("别人在插件市场里看到的作者名")
        form.addRow("作者名", self.edit_author)

        self.edit_note = QLineEdit()
        self.edit_note.setPlaceholderText("给站长留句话（可留空）")
        form.addRow("说明", self.edit_note)

        self.label_email = QLabel(
            "账号邮箱：" + workshop.mask_email(workshop.account_email()))
        self.label_email.setStyleSheet(f"color: {TEXT_3}; font-size: 12px;")
        form.addRow(self.label_email)

        self.edit_code = QLineEdit()
        self.edit_code.setPlaceholderText("6 位数字")
        self.edit_code.setMaxLength(6)
        self.btn_send = QPushButton("发送验证码")
        self.btn_send.clicked.connect(self._send_code)
        row_code = QHBoxLayout()
        row_code.addWidget(self.edit_code, 1)
        row_code.addWidget(self.btn_send)
        form.addRow("邮箱验证码", row_code)

        self.hint = QLabel("点「发送验证码」→ 去邮箱拿 6 位码 → 填上 → 确认上传。")
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet(f"color: {TEXT_3}; font-size: 12px;")
        form.addRow(self.hint)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Ok).setText("确认上传")
        self.buttons.button(QDialogButtonBox.Cancel).setText("取消")
        self.buttons.accepted.connect(self._confirm)
        self.buttons.rejected.connect(self.reject)
        form.addRow(self.buttons)

        if not workshop.account_email():
            self.hint.setText("还没登录星群账号：先去「设置 → 星群账号」登录，再回来上传。")
            self.btn_send.setEnabled(False)
            self.buttons.button(QDialogButtonBox.Ok).setEnabled(False)

    def _pick_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "选一个插件 zip", "", "插件包 (*.zip)")
        if path:
            self.edit_from_file.setText(path)

    def _tick(self):
        self._seconds -= 1
        if self._seconds <= 0:
            self._timer.stop()
            self.btn_send.setEnabled(True)
            self.btn_send.setText("重新发送")
            return
        self.btn_send.setText(f"{self._seconds} 秒后可重发")

    def _send_code(self):
        self.btn_send.setEnabled(False)
        self.btn_send.setText("正在发送…")
        self.hint.setText("正在发验证码…")
        try:
            res = workshop.request_upload_code(self.settings)
        except Exception as exc:  # noqa: BLE001
            self.btn_send.setEnabled(True)
            self.btn_send.setText("发送验证码")
            self.hint.setText("发送失败：" + str(exc))
            return
        self._seconds = 60
        self._timer.start(1000)
        self.hint.setText(
            f"验证码已发到 {workshop.mask_email(res.get('email') or '')}"
            f"（{(res.get('expires_in') or 300) // 60} 分钟内有效）。去邮箱看一眼。")

    def _confirm(self):
        code = self.edit_code.text().strip()
        if not code:
            self.hint.setText("先把邮箱收到的 6 位验证码填上（没收到就点「发送验证码」）。")
            return
        if not self.edit_from_file.text().strip() and not self.combo_plugin.count():
            self.hint.setText("先选一个要上传的插件。")
            return
        self.accept()

    def values(self) -> dict:
        return {
            "pid": self.combo_plugin.currentData() or "",
            "zip_path": self.edit_from_file.text().strip(),
            "note": self.edit_note.text().strip(),
            "username": self.edit_author.text().strip(),
            "code": self.edit_code.text().strip(),
        }


class ModelDialog(QDialog):
    """工坊生成模型配置（跟 AI 大脑的模型分开）。"""

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("插件工坊 · 生成模型")
        self.setMinimumWidth(460)
        cfg = ws_config.resolved(settings)
        form = QFormLayout(self)
        tip = QLabel(
            "工坊必须用有编码能力的强模型（" + ws_config.AGENT_CAPABLE_HINT + "），"
            "不然生成的插件容易不能用。这里的配置和「AI 大脑」互不影响。")
        tip.setWordWrap(True)
        tip.setStyleSheet(f"color: {TEXT_3}; font-size: 12px;")
        form.addRow(tip)
        self.combo = QComboBox()
        for item in ws_config.WORKSHOP_PROVIDERS:
            self.combo.addItem(item["name"], item["key"])
        idx = self.combo.findData(cfg.get("provider") or "deepseek")
        self.combo.setCurrentIndex(max(0, idx))
        self.combo.currentIndexChanged.connect(self._on_provider)
        self.edit_key = QLineEdit(cfg.get("api_key") or "")
        self.edit_key.setEchoMode(QLineEdit.Password)
        self.edit_model = QLineEdit(cfg.get("model") or "")
        self.edit_url = QLineEdit(cfg.get("api_url") or "")
        form.addRow("服务商", self.combo)
        form.addRow("API Key", self.edit_key)
        form.addRow("模型名", self.edit_model)
        form.addRow("接口地址", self.edit_url)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self._on_provider()

    def _on_provider(self):
        defaults = ws_config.provider_defaults(self.combo.currentData())
        if defaults:
            self.edit_url.setText(defaults["url"])
            self.edit_model.setText(defaults["model"])

    def _save(self):
        try:
            ws_config.save(self.settings, {
                "provider": self.combo.currentData(),
                "api_key": self.edit_key.text().strip(),
                "model": self.edit_model.text().strip(),
                "api_url": self.edit_url.text().strip(),
            })
        except ValueError as exc:
            tip = QLabel(str(exc))
            tip.setWordWrap(True)
            tip.setStyleSheet(f"color: {TEXT_3}; font-size: 12px;")
            self.layout().addRow(tip)
            return
        self.accept()


class WorkshopPage(QWidget):
    def __init__(self, ctx: PageContext):
        super().__init__()
        self.ctx = ctx
        self.plan = None
        self.built = None
        self._build_ui()
        self.refresh_status()
        self._refresh_installed()
        self.set_beginner(bool(getattr(ctx.settings, "beginner_mode", False)))

    # ---------- UI ----------
    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(12)

        title = QLabel("插件工坊")
        title.setObjectName("pageTitle")
        sub = QLabel("用大白话给机器人加功能：AI 写插件 → 自动检查 → 沙箱试跑 → 一键安装")
        sub.setObjectName("pageSub")
        outer.addWidget(title)
        outer.addWidget(sub)

        self.panel = GlassPanel(self, strong=True)
        box = QVBoxLayout(self.panel)
        box.setContentsMargins(18, 14, 18, 14)
        box.setSpacing(10)
        self.status_label = QLabel("…")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet(f"color: {TEXT_2}; font-size: 13px;")
        row = QHBoxLayout()
        row.addWidget(self.status_label, 1)
        self.btn_model = QPushButton("配置生成模型")
        self.btn_model.setObjectName("ghost")
        self.btn_model.clicked.connect(self._edit_model)
        row.addWidget(self.btn_model)
        box.addLayout(row)

        box.addWidget(QLabel("你想要什么功能？直接说就行："))
        self.need_edit = QPlainTextEdit()
        self.need_edit.setPlaceholderText("例如：群里谁签到就记一次，能查每个人有多少金币")
        self.need_edit.setFixedHeight(84)
        box.addWidget(self.need_edit)
        ex_row = QHBoxLayout()
        ex_label = QLabel("例子：")
        ex_label.setStyleSheet(f"color: {TEXT_3}; font-size: 12px;")
        ex_row.addWidget(ex_label)
        for text in EXAMPLES:
            btn = QPushButton(text[:14] + "…")
            btn.setObjectName("ghost")
            btn.setToolTip(text)
            btn.clicked.connect(lambda _=False, t=text: self.need_edit.setPlainText(t))
            ex_row.addWidget(btn)
        ex_row.addStretch(1)
        box.addLayout(ex_row)

        act_row = QHBoxLayout()
        self.btn_plan = QPushButton("让 AI 出方案")
        self.btn_plan.setObjectName("primary")
        self.btn_plan.clicked.connect(self._make_plan)
        self.btn_build = QPushButton("生成插件（自动检查 + 试跑）")
        self.btn_build.setObjectName("primary")
        self.btn_build.setEnabled(False)
        self.btn_build.clicked.connect(self._generate)
        self.btn_install = QPushButton("安装到机器人")
        self.btn_install.setObjectName("primary")
        self.btn_install.setEnabled(False)
        self.btn_install.clicked.connect(self._install)
        self.btn_restart = QPushButton("重启机器人生效")
        self.btn_restart.setObjectName("ghost")
        self.btn_restart.setEnabled(False)
        self.btn_restart.clicked.connect(self._restart_bot)
        for btn in (self.btn_plan, self.btn_build, self.btn_install, self.btn_restart):
            act_row.addWidget(btn)
        act_row.addStretch(1)
        box.addLayout(act_row)
        outer.addWidget(self.panel)

        self.plan_panel = GlassPanel(self)
        plan_box = QVBoxLayout(self.plan_panel)
        plan_box.setContentsMargins(18, 12, 18, 12)
        plan_title = QLabel("方案")
        plan_title.setStyleSheet(f"color: {TEXT_2}; font-size: 13px; font-weight: 600;")
        plan_box.addWidget(plan_title)
        self.plan_text = QLabel("点「让 AI 出方案」，它会先用大白话告诉你要做什么、用哪些通道。")
        self.plan_text.setWordWrap(True)
        self.plan_text.setStyleSheet(f"color: {TEXT_2}; font-size: 13px;")
        plan_box.addWidget(self.plan_text)
        outer.addWidget(self.plan_panel)

        self.log_panel = GlassPanel(self)
        log_box = QVBoxLayout(self.log_panel)
        log_box.setContentsMargins(18, 12, 18, 12)
        log_box.addWidget(QLabel("过程"))
        self.log_text = QPlainTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFixedHeight(120)
        log_box.addWidget(self.log_text)
        outer.addWidget(self.log_panel)

        self.result_panel = GlassPanel(self)
        res_box = QVBoxLayout(self.result_panel)
        res_box.setContentsMargins(18, 12, 18, 12)
        res_box.addWidget(QLabel("结果"))
        self.result_text = QLabel("还没有生成插件。")
        self.result_text.setWordWrap(True)
        self.result_text.setStyleSheet(f"color: {TEXT_2}; font-size: 13px;")
        res_box.addWidget(self.result_text)
        outer.addWidget(self.result_panel)

        self.installed_panel = GlassPanel(self)
        ins_box = QVBoxLayout(self.installed_panel)
        ins_box.setContentsMargins(18, 12, 18, 12)
        head = QHBoxLayout()
        head.addWidget(QLabel("已装的插件（含 AI 生成的）"))
        head.addStretch(1)
        btn_refresh = QPushButton("刷新")
        btn_refresh.setObjectName("ghost")
        btn_refresh.clicked.connect(self._refresh_installed)
        head.addWidget(btn_refresh)
        ins_box.addLayout(head)
        self.installed_list = QListWidget()
        self.installed_list.setFixedHeight(120)
        self.installed_list.currentItemChanged.connect(lambda *_: self._refresh_error_hint())
        ins_box.addWidget(self.installed_list)
        row2 = QHBoxLayout()
        self.btn_uninstall = QPushButton("卸载选中的插件")
        self.btn_uninstall.setObjectName("ghost")
        self.btn_uninstall.clicked.connect(self._uninstall)
        self.btn_rollback = QPushButton("换回上一版")
        self.btn_rollback.setObjectName("ghost")
        self.btn_rollback.clicked.connect(self._rollback)
        row2.addStretch(1)
        row2.addWidget(self.btn_rollback)
        row2.addWidget(self.btn_uninstall)
        ins_box.addLayout(row2)
        self.error_hint = QLabel("")
        self.error_hint.setWordWrap(True)
        self.error_hint.setStyleSheet(f"color: {TEXT_3}; font-size: 12px;")
        ins_box.addWidget(self.error_hint)
        row3 = QHBoxLayout()
        self.btn_fix = QPushButton("让 AI 修一版")
        self.btn_fix.setObjectName("primary")
        self.btn_fix.setEnabled(False)
        self.btn_fix.setToolTip("插件在群里跑挂过？选它，让 AI 按真实报错改一版")
        self.btn_fix.clicked.connect(self._fix_from_errors)
        row3.addWidget(self.btn_fix)
        row3.addStretch(1)
        self.btn_export = QPushButton("导出 zip")
        self.btn_export.setObjectName("ghost")
        self.btn_export.clicked.connect(self._export_zip)
        self.btn_import = QPushButton("导入插件包…")
        self.btn_import.setObjectName("ghost")
        self.btn_import.clicked.connect(self._import_zip)
        self.btn_upload = QPushButton("上传到官网审核")
        self.btn_upload.setObjectName("ghost")
        self.btn_upload.setToolTip("传给站长审核，通过后进插件市场，所有用户都能装")
        self.btn_upload.clicked.connect(self._upload)
        for btn in (self.btn_export, self.btn_import, self.btn_upload):
            row3.addWidget(btn)
        ins_box.addLayout(row3)
        outer.addWidget(self.installed_panel)
        outer.addStretch(1)

    def set_beginner(self, on: bool):
        """小白模式隐藏"已装/回滚"这类进阶操作。"""
        self.installed_panel.setVisible(not on)

    # ---------- 状态 ----------
    def refresh_status(self):
        st = workshop.status(self.ctx.settings)
        self.status_label.setText(("✅ " if st["ready"] else "⚠️ ") + st["why"])

    def _edit_model(self):
        dlg = ModelDialog(self.ctx.settings, self)
        dlg.exec()
        self.refresh_status()

    def _log(self, text):
        self.log_text.appendPlainText(str(text))

    def _busy(self, busy: bool):
        self.btn_plan.setEnabled(not busy)
        self.btn_build.setEnabled(not busy and self.plan is not None)
        self.btn_install.setEnabled(not busy and bool(self.built))
        for btn in (self.btn_export, self.btn_import, self.btn_upload):
            btn.setEnabled(not busy)
        if busy:
            self.btn_fix.setEnabled(False)
        else:
            self._refresh_error_hint()

    @staticmethod
    def _safe(fn):
        def run():
            try:
                return fn()
            except workshop.generator.WorkshopError as exc:
                return {"error": exc.plain, "detail": exc.detail}
            except Exception as exc:  # noqa: BLE001
                return {"error": f"出错了：{exc}"}
        return run

    def _run_bg(self, fn, on_done):
        worker = Worker(self)
        worker.finished.connect(on_done)
        threading.Thread(target=lambda: worker.run(self._safe(fn)), daemon=True).start()

    # ---------- 三步 ----------
    def _make_plan(self):
        need = self.need_edit.toPlainText().strip()
        if not need:
            self.ctx.show_toast("先说说你想要什么功能")
            return
        self._busy(True)
        self._log("正在让 AI 出方案…")

        def job():
            return workshop.generator.make_plan(
                self.ctx.settings, need, workshop.active_channels(self.ctx.settings))

        self._run_bg(job, self._on_plan)

    def _on_plan(self, res):
        self._busy(False)
        if not isinstance(res, dict) or res.get("error"):
            self.plan_text.setText("方案生成失败：" + str((res or {}).get("error")))
            self._log("失败：" + str((res or {}).get("error")))
            return
        self.plan = res
        steps = "；".join(str(s) for s in (res.get("steps") or []))
        tools = "、".join(str(t.get("name")) for t in (res.get("tools") or [])
                         if isinstance(t, dict))
        self.plan_text.setText(
            f"做什么：{res.get('what') or res.get('name')}\n"
            f"工具：{tools or '（待定）'}\n"
            f"能用在：{res.get('channel_note') or '（待定）'}\n"
            f"权限：{'、'.join(res.get('permissions') or []) or '不需要额外权限'}\n"
            f"步骤：{steps or '（待定）'}")
        self._log("方案好了，点「生成插件」开始写代码。")
        self.btn_build.setEnabled(True)

    def _generate(self):
        if not self.plan:
            return
        need = self.need_edit.toPlainText().strip()
        self._busy(True)

        def job():
            return workshop.build(
                self.ctx.settings, need, plan=self.plan,
                channels=workshop.active_channels(self.ctx.settings),
                on_log=self._log_threadsafe)
        self._run_bg(job, self._on_built)

    def _log_threadsafe(self, text):
        # 后台线程里只往缓冲里写，回主线程再渲染
        if not hasattr(self, "_pending_logs"):
            self._pending_logs = []
        self._pending_logs.append(str(text))

    def _on_built(self, res):
        self._busy(False)
        for line in getattr(self, "_pending_logs", []):
            self._log(line)
        self._pending_logs = []
        if not isinstance(res, dict) or res.get("error"):
            self.result_text.setText("生成失败：" + str((res or {}).get("error")))
            return
        self.built = res if res.get("ok") else None
        report = res.get("report") or {}
        errors = [i for i in (res.get("issues") or []) if i.get("level") == "error"]
        warns = [i for i in (res.get("issues") or []) if i.get("level") == "warn"]
        lines = []
        if res.get("ok"):
            lines.append(f"✅ 「{report.get('name') or res['plan'].get('name')}」做好了，检查全部通过。")
            if report.get("used_in"):
                lines.append("能用在：" + "、".join(report["used_in"]))
            for note in report.get("notes") or []:
                lines.append("· " + note)
            for item in warns:
                lines.append("· 提醒：" + str(item.get("plain")))
            lines.append("点「安装到机器人」，装完重启一下机器人就生效。")
            self.btn_install.setEnabled(True)
        else:
            lines.append("❌ 自动检查没通过（已经让 AI 改过 "
                         f"{res.get('attempts', 0)} 次），这次先不装：")
            for item in errors[:6]:
                lines.append("· " + str(item.get("plain")))
            lines.append("可以改一下需求描述，或者换个更强的模型再试。")
        self.result_text.setText("\n".join(lines))
        self._log("完成。" if res.get("ok") else "有问题，见结果区。")

    def _install(self):
        if not self.built:
            return
        self._busy(True)

        def job():
            return workshop.install(self.ctx.settings, self.built)
        self._run_bg(job, self._on_installed)

    def _on_installed(self, res):
        self._busy(False)
        if not isinstance(res, dict) or res.get("error"):
            self.result_text.setText("安装失败：" + str((res or {}).get("error")))
            return
        # 换上新版本 = 之前记下的报错算处理过了（没修好还会再记一条新的）
        try:
            workshop.repair.mark_fixed(self.ctx.settings, str(res.get("id") or ""))
        except Exception:  # noqa: BLE001
            pass
        self.btn_restart.setEnabled(True)
        self._log(f"已安装：{res.get('id')}")
        self._refresh_installed()
        self.ctx.show_toast("装好了，点「重启机器人生效」")
        self.result_text.setText(
            self.result_text.text() + "\n\n✅ 已安装。重启机器人后就能用了。")

    # ---------- 已装列表 ----------
    def _selected_pid(self):
        item = self.installed_list.currentItem()
        return item.data(0x0100) if item is not None else ""

    def _refresh_installed(self):
        self.installed_list.clear()
        for row in workshop.generated(self.ctx.settings):
            mark = "AI 生成" if row.get("ai_generated") else "官方/手动"
            label = (f"{row['name']}（{row['id']}）· {mark}"
                     f" · 通道 {'/'.join(row.get('adapters') or []) or '不限'}"
                     f" · 工具 {', '.join(row.get('tools') or []) or '-'}")
            item = self.installed_list.addItem(label)
            entry = self.installed_list.item(self.installed_list.count() - 1)
            entry.setData(0x0100, row["id"])
        self._refresh_error_hint()

    # ---------- 分享 / 投稿 / 自修复 ----------
    def _refresh_error_hint(self, *_):
        try:
            rows = workshop.runtime_errors(self.ctx.settings)
        except Exception:  # noqa: BLE001
            rows = []
        self._error_rows = {str(r.get("id")): r for r in rows}
        pid = self._selected_pid()
        row = self._error_rows.get(str(pid)) if pid else None
        if row:
            self.error_hint.setText(
                f"⚠️ 「{row.get('name')}」跑出过 {row.get('count')} 次错："
                f"{str(row.get('error') or '')[:160]}")
            self.btn_fix.setEnabled(True)
            return
        if rows:
            names = "、".join(str(r.get("name")) for r in rows[:3])
            self.error_hint.setText(
                f"有 {len(rows)} 个插件跑出过错（{names}）：选中它，点「让 AI 修一版」。")
        else:
            self.error_hint.setText(
                "插件在群里跑挂了会自动记下来；选中它就能让 AI 按真实报错改一版。")
        self.btn_fix.setEnabled(False)

    def _pick_pid(self) -> str:
        pid = self._selected_pid()
        if not pid:
            self.ctx.show_toast("先在列表里选一个插件")
        return pid

    def _flush_logs(self):
        for line in getattr(self, "_pending_logs", []):
            self._log(line)
        self._pending_logs = []

    def _export_zip(self):
        pid = self._pick_pid()
        if not pid:
            return
        try:
            res = workshop.export_zip(self.ctx.settings, pid)
        except Exception as exc:  # noqa: BLE001
            self.ctx.show_toast(f"导出失败：{exc}")
            return
        self._log(f"已导出：{res.get('path')}")
        self.result_text.setText(
            f"已导出「{res.get('name')}」（{res.get('files')} 个文件）到：\n{res.get('path')}\n"
            "发给别人后，对方在工坊里点「导入插件包」就能装。")
        self.ctx.show_toast("导出好了")

    def _import_zip(self):
        path, _ = QFileDialog.getOpenFileName(self, "选一个插件 zip", "", "插件包 (*.zip)")
        if not path:
            return
        self._busy(True)
        self._log("正在检查并导入插件包…")

        def job():
            return workshop.import_zip(self.ctx.settings, path,
                                       on_log=self._log_threadsafe)
        self._run_bg(job, self._on_imported)

    def _on_imported(self, res):
        self._busy(False)
        self._flush_logs()
        if not isinstance(res, dict) or res.get("error"):
            self.result_text.setText(
                "这个插件包没装上：" + str((res or {}).get("error")))
            return
        self.btn_restart.setEnabled(True)
        self._refresh_installed()
        self.result_text.setText(
            f"✅ 插件包「{res.get('name')}」装好了。点「重启机器人生效」。")
        self.ctx.show_toast("导入完成")

    def _upload(self):
        rows = workshop.generated(self.ctx.settings)
        dlg = UploadDialog(self.ctx.settings, rows, current_pid=self._selected_pid(), parent=self)
        if dlg.exec() != QDialog.Accepted:
            return
        vals = dlg.values()
        if not vals["pid"] and not vals["zip_path"]:
            self.ctx.show_toast("先选一个要上传的插件")
            return
        self._busy(True)
        self._log("正在校验邮箱验证码并上传到官网…")

        def job():
            if vals["zip_path"]:
                return workshop.upload_file(
                    self.ctx.settings, vals["zip_path"], note=vals["note"],
                    code=vals["code"], username=vals["username"],
                    on_log=self._log_threadsafe)
            return workshop.upload(
                self.ctx.settings, vals["pid"], note=vals["note"],
                code=vals["code"], username=vals["username"],
                on_log=self._log_threadsafe)
        self._run_bg(job, self._on_uploaded)

    def _on_uploaded(self, res):
        self._busy(False)
        self._flush_logs()
        if not isinstance(res, dict) or res.get("error"):
            self.result_text.setText(
                "上传失败：" + str((res or {}).get("error") or res)
                + "\n（验证码错了 / 过期了就重新点「上传」发一条新的；"
                  "同一条验证码只能用一次。）")
            return
        self.result_text.setText(
            f"✅ 已交给站长审核（编号 #{res.get('id')}，作者：{res.get('username') or '未填'}）。\n"
            "审核通过后，这个插件会出现在官网插件市场，所有用户都能一键装；"
            "被驳回会写原因，改完可以再传。")
        self.ctx.show_toast("已提交，等站长审核")

    def _fix_from_errors(self):
        pid = self._pick_pid()
        if not pid:
            return
        self._busy(True)
        self._log("让 AI 按真实报错改一版…")

        def job():
            return workshop.fix_from_errors(self.ctx.settings, pid,
                                            on_log=self._log_threadsafe)
        self._run_bg(job, self._on_fixed)

    def _on_fixed(self, res):
        self._busy(False)
        self._flush_logs()
        if not isinstance(res, dict) or res.get("error"):
            self.result_text.setText("修复失败：" + str((res or {}).get("error")))
            return
        self.built = res if res.get("ok") else None
        errors = [i for i in (res.get("issues") or []) if i.get("level") == "error"]
        if res.get("ok"):
            self.result_text.setText(
                "✅ AI 按真实报错改好了一版，检查全过。\n"
                "点「安装到机器人」换上（旧版本留在历史里，不满意可以「换回上一版」）。")
            self._log("改好了，等安装。")
        else:
            lines = ["❌ 改完还是没过检查（可以改一下需求描述，或换个更强的模型）："]
            for item in errors[:6]:
                lines.append("· " + str(item.get("plain")))
            self.result_text.setText("\n".join(lines))
        self.btn_install.setEnabled(bool(self.built))

    def _uninstall(self):
        pid = self._selected_pid()
        if not pid:
            self.ctx.show_toast("先在列表里选一个插件")
            return
        try:
            workshop.uninstall(self.ctx.settings, pid)
            self.ctx.show_toast("已卸载（旧版本留在工坊历史里，可以换回来）")
        except Exception as exc:  # noqa: BLE001
            self.ctx.show_toast(f"卸载失败：{exc}")
        self._refresh_installed()

    def _rollback(self):
        pid = self._selected_pid()
        if not pid:
            self.ctx.show_toast("先在列表里选一个插件")
            return
        try:
            workshop.rollback(self.ctx.settings, pid)
            self.ctx.show_toast("已换回上一版，重启机器人后生效")
        except Exception as exc:  # noqa: BLE001
            self.ctx.show_toast(f"换回失败：{exc}")
        self._refresh_installed()

    def _restart_bot(self):
        from ...tasks.workers import RestartBotTask

        if self.ctx.tasks.has_active("service"):
            self.ctx.show_toast("已有服务任务在跑，稍等一下")
            return
        self.ctx.tasks.submit("重启 NoneBot", "service", RestartBotTask,
                              retryable=True, manager=self.ctx.manager)
