import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QVBoxLayout,
    QWidget,
)

from ..core.settings import Settings
from ..core import autostart as autostart_mod
from .workers import DeployWorker

def default_root() -> str:
    r"""首次运行向导的默认部署目录。

    打包版优先「客户端所在目录\机器人」——和安装版一致，装在一起好找；
    目录不可写（例如装在 Program Files）时退回 %LOCALAPPDATA%\AstroSwarm。
    """
    appdata_root = str(Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "AstroSwarm")
    if not getattr(sys, "frozen", False):
        return appdata_root
    try:
        exe_dir = Path(sys.executable).resolve().parent
        probe = exe_dir / ".qbm_write_probe"
        probe.write_text("x", encoding="utf-8")
        try:
            probe.unlink()
        except OSError:
            pass
    except Exception:  # noqa: BLE001
        return appdata_root
    return str(exe_dir / "机器人")
ASSET_BG = Path(__file__).resolve().parent.parent / "assets" / "wizard_bg.jpg"

_PANEL_QSS = """
#wizardPanel {
    background: rgba(8, 12, 22, 196);
    border: 1px solid rgba(255, 255, 255, 0.10);
    border-radius: 14px;
}
#wizardPanel QLabel { color: #E9EEF8; }
#wizardPanel QLabel#wizardTitle { color: #7FB0FF; }
#wizardPanel QCheckBox { color: #D6DCE8; }
#wizardPanel QLineEdit { color: #F2F5FA; background: rgba(0, 0, 0, 0.35); }
"""


class DeployWizard(QDialog):
    """首次运行向导：选择安装目录 -> 一键部署。"""

    def __init__(self, parent=None, root=None):
        super().__init__(parent)
        self.settings = None
        self.worker = None
        self.setWindowTitle("AstroSwarm 星群 - 首次安装")
        self.setMinimumSize(760, 580)
        self._bg = QPixmap(str(ASSET_BG)) if ASSET_BG.is_file() else QPixmap()
        self._build_ui()
        # 上次部署未完成时复用原目录，避免客户重新选择路径
        if root:
            self.root_edit.setText(str(root))

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 28, 28, 28)

        panel = QFrame(self)
        panel.setObjectName("wizardPanel")
        panel.setStyleSheet(_PANEL_QSS)
        v = QVBoxLayout(panel)
        v.setContentsMargins(24, 24, 24, 24)
        v.setSpacing(14)

        title = QLabel("欢迎使用 AstroSwarm 星群\n一键部署你的多平台机器人")
        title.setObjectName("wizardTitle")
        title.setStyleSheet("font-size: 22px; font-weight: bold;")
        v.addWidget(title)

        # ---- 页面 1: 选择目录 ----
        self.page_choose = QWidget()
        pv = QVBoxLayout(self.page_choose)

        tip = QLabel(
            "请选择安装目录：\n"
            "Python 运行时、机器人项目（NoneBot）全部安装在这个文件夹里。\n"
            "建议安装在剩余空间大于 4GB 的磁盘。"
        )
        tip.setWordWrap(True)
        pv.addWidget(tip)

        row = QHBoxLayout()
        self.root_edit = QLineEdit(default_root())
        btn_browse = QPushButton("浏览...")
        btn_browse.clicked.connect(self._browse)
        row.addWidget(self.root_edit, 1)
        row.addWidget(btn_browse)
        pv.addLayout(row)

        self.chk_shortcut = QCheckBox("创建桌面快捷方式（推荐）")
        self.chk_shortcut.setChecked(True)
        pv.addWidget(self.chk_shortcut)

        self.chk_auto_start_services = QCheckBox("启动程序时自动启动全部服务")
        self.chk_auto_start_services.setChecked(False)
        pv.addWidget(self.chk_auto_start_services)

        self.chk_autostart = QCheckBox("开机自动启动 AstroSwarm")
        # 安装包（Inno 附加任务）可能已经写过自启动注册表项：以实际状态为准，
        # 否则会出现「安装时勾了、程序里没勾」的矛盾
        self.chk_autostart.setChecked(autostart_mod.is_enabled())
        pv.addWidget(self.chk_autostart)

        proto_tip = QLabel(
            "QQ 机器人通过第三方 OneBot 协议接入：\n"
            "协议端（如 LLOneBot / Lagrange）由你自己下载安装并扫码登录，"
            "AstroSwarm 不内置、不分发任何协议端；使用第三方协议有账号风险，请自备小号。"
        )
        proto_tip.setWordWrap(True)
        proto_tip.setStyleSheet("color: #B9C3D4; font-size: 12px;")
        pv.addWidget(proto_tip)

        eula_row = QHBoxLayout()
        eula_row.setSpacing(8)
        self.chk_eula = QCheckBox(
            "我已阅读并同意《用户协议与免责声明》：第三方协议端由用户自行安装并承担账号风险"
        )
        self.chk_eula.setChecked(False)
        btn_eula = QPushButton("查看协议")
        btn_eula.setFlat(True)
        btn_eula.setStyleSheet("color: #7FB0FF; font-size: 12px;")
        btn_eula.clicked.connect(self._show_eula)
        eula_row.addWidget(self.chk_eula, 1)
        eula_row.addWidget(btn_eula)
        pv.addLayout(eula_row)

        self.btn_next = QPushButton("开始部署")
        self.btn_next.setStyleSheet("padding: 8px; font-size: 14px;")
        self.btn_next.clicked.connect(self._start_deploy)
        pv.addWidget(self.btn_next, 0, Qt.AlignRight)
        v.addWidget(self.page_choose)

        # ---- 页面 2: 部署进度 ----
        self.page_deploy = QWidget()
        v2 = QVBoxLayout(self.page_deploy)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        v2.addWidget(self.progress)
        self.step_label = QLabel("准备中 ...")
        v2.addWidget(self.step_label)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(5000)
        v2.addWidget(self.log_view, 1)
        self.btn_done = QPushButton("完成，进入管理器")
        self.btn_done.setEnabled(False)
        self.btn_done.setStyleSheet("padding: 8px; font-size: 14px;")
        self.btn_done.clicked.connect(self.accept)
        v2.addWidget(self.btn_done, 0, Qt.AlignRight)
        self.page_deploy.hide()
        v.addWidget(self.page_deploy)

        layout.addWidget(panel)

    def paintEvent(self, event):
        """整窗背景：封面式图片 + 压暗，保证面板内文字清晰。"""
        if self._bg.isNull():
            super().paintEvent(event)
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        scaled = self._bg.scaled(
            self.size(),
            Qt.KeepAspectRatioByExpanding,
            Qt.SmoothTransformation,
        )
        x = (self.width() - scaled.width()) // 2
        y = (self.height() - scaled.height()) // 2
        painter.drawPixmap(x, y, scaled)
        painter.fillRect(self.rect(), QColor(6, 10, 20, 150))
        painter.end()

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "选择安装目录", self.root_edit.text())
        if d:
            self.root_edit.setText(d)

    def _start_deploy(self):
        root = self.root_edit.text().strip()
        if not root:
            QMessageBox.warning(self, "提示", "请先选择安装目录")
            return
        if not self.chk_eula.isChecked():
            QMessageBox.warning(self, "提示", "请先阅读并勾选《用户协议与免责声明》")
            return
        try:
            self.settings = Settings.load(root)
            self.settings.ensure_dirs()
        except OSError as e:
            QMessageBox.critical(self, "错误", f"无法使用该目录: {e}")
            return
        self.page_choose.hide()
        self.page_deploy.show()
        self.btn_next.setEnabled(False)
        self.worker = DeployWorker(self.settings)
        self.worker.progress.connect(self._on_progress)
        self.worker.log.connect(self._append_log)
        self.worker.ok.connect(self._on_ok)
        self.worker.fail.connect(self._on_fail)
        self.worker.start()

    def _on_progress(self, done, total, label):
        self.progress.setValue(int(done * 100 / max(total, 1)))
        self.step_label.setText(f"[{done}/{total}] {label}")

    def _append_log(self, line):
        self.log_view.appendPlainText(line)

    def _on_ok(self, result):
        self.progress.setValue(100)
        self.step_label.setText("部署完成！")
        self.btn_done.setEnabled(True)
        self.settings.auto_start_services = self.chk_auto_start_services.isChecked()
        self.settings.auto_launch_on_boot = self.chk_autostart.isChecked()
        try:
            self.settings.save()
        except OSError as e:
            self._append_log("保存启动选项失败: " + str(e))
        # 双向都落一遍：安装包写过自启动项、用户又在向导里取消勾选时要撤掉
        if autostart_mod.set_enabled(self.settings.auto_launch_on_boot):
            self._append_log("已设置开机自启动" if self.settings.auto_launch_on_boot
                             else "未设置开机自启动")
        elif self.settings.auto_launch_on_boot:
            self._append_log("开机自启动设置失败（非 Windows 或权限不足）")
        if self.chk_shortcut.isChecked():
            if self._create_shortcut():
                self._append_log("已创建桌面快捷方式")
            else:
                self._append_log("桌面快捷方式创建失败（开发模式或权限不足）")
        else:
            self._append_log("未创建桌面快捷方式")
        self._append_log("---- 部署结果 ----")
        for k, v in result.items():
            self._append_log(f"{k}: {v}")
        self._append_log(
            "接下来：进入管理器 -> QQ 页填写协议端地址并保存，然后点击「启动全部」。"
        )
        QMessageBox.information(
            self, "部署完成",
            "部署完成！\n\n接下来：\n1. 在「QQ 页」填写你的 OneBot 协议端地址并保存\n"
            "2. 保存后点击「启动全部」\n3. 在微信页扫码连接 ClawBot（可选）",
        )

    def _show_eula(self):
        path = Path(__file__).resolve().parent.parent / "assets" / "agreements" / "user_eula.txt"
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            text = "协议文件缺失，请联系客服获取《用户协议与免责声明》。"
        box = QMessageBox(self)
        box.setWindowTitle("用户协议与免责声明")
        box.setText(text)
        box.setStandardButtons(QMessageBox.Ok)
        box.exec()

    def _on_fail(self, msg):
        self.step_label.setText("部署失败")
        self._append_log("!! " + msg)
        QMessageBox.critical(self, "部署失败", msg)
        self.btn_next.setEnabled(True)

    def _create_shortcut(self) -> bool:
        """部署完成后按勾选创建桌面快捷方式（打包版才创建，开发模式跳过）。"""
        if not getattr(sys, "frozen", False):
            return False
        target = sys.executable
        workdir = str(self.settings.root)
        esc_target = target.replace("'", "''")
        esc_workdir = workdir.replace("'", "''")
        ps = (
            "$d=[Environment]::GetFolderPath('Desktop');"
            "$s=(New-Object -ComObject WScript.Shell).CreateShortcut("
            "$d+'\\AstroSwarm 星群.lnk');"
            f"$s.TargetPath='{esc_target}';"
            f"$s.WorkingDirectory='{esc_workdir}';"
            f"$s.IconLocation='{esc_target},0';"
            "$s.Description='AstroSwarm 星群';"
            "$s.Save()"
        )
        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps],
                capture_output=True, timeout=15,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return True
        except Exception:  # noqa: BLE001
            return False
