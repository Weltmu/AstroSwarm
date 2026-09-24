# -*- coding: utf-8 -*-
"""通道配置面板：QQ（第三方 OneBot）与微信 ClawBot。

为什么单独抽一层：控制台（Linux 无头端）的「接入」页是「每通道一行、展开就地配置」，
桌面端要跟它对齐，就得让同一份配置表单同时出现在「接入」页的内联展开区和通道独立页里。
表单只写一遍，两边行为一致；面板只依赖 PageContext，不依赖宿主页面。

宿主页面负责：把面板放进自己的卡片里，并在 refresh_status() 里转调面板的刷新方法。
"""
import socket
import time
import webbrowser

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication, QComboBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from ...core import ai_config
from ...core import bot as bot_mod
from ...core import license as lic_mod
from ...tasks.workers import RestartBotTask
from ..theme import TEXT_3
from ..widgets import StatusBadge
from .common import PageContext, make_row

try:
    import qrcode
    _QR_OK = True
except Exception:  # noqa: BLE001
    qrcode = None
    _QR_OK = False


def _tip(text: str) -> QLabel:
    """面板里统一的小字提示（颜色跟主题走）。"""
    lbl = QLabel(text)
    lbl.setWordWrap(True)
    lbl.setStyleSheet(f"color: {TEXT_3}; font-size: 12px;")
    return lbl


class QQChannelPanel(QWidget):
    """第三方 OneBot 通道配置（反向 WS / 正向 WS + 保存）。

    官方凭证那两个字段留在 QQ 页自己手里（官方通道已下线、面板默认隐藏），
    保存时由宿主的 extra_save 回调顺手写回去，面板不碰。
    """

    def __init__(self, ctx: PageContext, on_saved=None, extra_save=None, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self._on_saved = on_saved
        self._extra_save = extra_save
        self._build_ui()
        self.load_credentials()

    # ------------------------------------------------------------ UI
    def _build_ui(self):
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)

        v.addWidget(_tip(
            "协议端需你自己安装（例如 LLOneBot、Lagrange.OneBot、NapCat）并扫码登录，"
            "AstroSwarm 不提供、不下载任何协议端；使用第三方协议存在账号风险，请自备小号。"))

        self.combo_onebot_mode = QComboBox()
        self.combo_onebot_mode.addItem("反向 WS（推荐）：协议端来连星群", "reverse")
        self.combo_onebot_mode.addItem("正向 WS：星群去连协议端", "forward")
        self.combo_onebot_mode.currentIndexChanged.connect(self._on_onebot_mode_changed)
        v.addLayout(make_row("连接方式", self.combo_onebot_mode))

        # 反向 WS 面板：把地址复制到协议端即可
        self.panel_reverse = QWidget()
        rv = QVBoxLayout(self.panel_reverse)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(8)
        rv.addWidget(_tip(
            "把下面的地址复制到协议端的「反向 WebSocket / WebSocket 服务端」配置里，"
            "保存后协议端会主动连回星群（本机/局域网直连，无需端口转发）。\n"
            "NapCat：网络配置 → 新建 WebSocket 服务端；"
            "LLOneBot：网络配置 → 反向 WebSocket 客户端。\n"
            "协议端在另一台设备时：监听地址填 0.0.0.0，"
            "并把下面地址里的 127.0.0.1 换成这台电脑的局域网 IP。"))
        self.edit_onebot_listen_host = QLineEdit()
        self.edit_onebot_listen_host.setPlaceholderText("127.0.0.1")
        self.edit_onebot_listen_host.setMinimumWidth(180)
        self.edit_onebot_listen_host.textChanged.connect(self._refresh_reverse_url)
        self.edit_reverse_port = QLineEdit()
        self.edit_reverse_port.setReadOnly(True)
        self.edit_reverse_port.setMinimumWidth(120)
        rv.addLayout(make_row("监听地址", self.edit_onebot_listen_host))
        rv.addLayout(make_row("监听端口", self.edit_reverse_port))
        url_row = QHBoxLayout()
        url_row.setSpacing(8)
        self.edit_reverse_url = QLineEdit()
        self.edit_reverse_url.setReadOnly(True)
        self.edit_reverse_url.setMinimumWidth(300)
        self.btn_copy_reverse_url = QPushButton("复制地址")
        self.btn_copy_reverse_url.setObjectName("primary")
        self.btn_copy_reverse_url.setMinimumHeight(30)
        self.btn_copy_reverse_url.clicked.connect(self._copy_reverse_url)
        url_row.addWidget(self.edit_reverse_url, 1)
        url_row.addWidget(self.btn_copy_reverse_url)
        rv.addLayout(url_row)
        v.addWidget(self.panel_reverse)

        # 正向 WS 面板：星群作为客户端去连协议端
        self.panel_forward = QWidget()
        fv = QVBoxLayout(self.panel_forward)
        fv.setContentsMargins(0, 0, 0, 0)
        fv.setSpacing(8)
        fv.addWidget(_tip("连接本机/局域网里已运行的 OneBot V11 协议端（正向 WS）。"))
        self.edit_onebot_host = QLineEdit()
        self.edit_onebot_host.setPlaceholderText("127.0.0.1")
        self.edit_onebot_host.setMinimumWidth(180)
        self.edit_onebot_port = QLineEdit()
        self.edit_onebot_port.setPlaceholderText("3001")
        self.edit_onebot_port.setMinimumWidth(120)
        self.edit_onebot_path = QLineEdit()
        self.edit_onebot_path.setPlaceholderText("/onebot/v11/ws")
        self.edit_onebot_path.setMinimumWidth(180)
        self.edit_onebot_token = QLineEdit()
        self.edit_onebot_token.setPlaceholderText("留空 = 无访问令牌")
        self.edit_onebot_token.setEchoMode(QLineEdit.Password)
        self.edit_onebot_token.setMinimumWidth(180)
        fv.addLayout(make_row("地址", self.edit_onebot_host))
        fv.addLayout(make_row("端口", self.edit_onebot_port))
        fv.addLayout(make_row("WS 路径", self.edit_onebot_path))
        detect_row = QHBoxLayout()
        self.btn_detect_onebot = QPushButton("检测协议端")
        self.btn_detect_onebot.setObjectName("ghost")
        self.btn_detect_onebot.setMinimumHeight(30)
        self.btn_detect_onebot.clicked.connect(self._detect_onebot)
        detect_row.addWidget(self.btn_detect_onebot)
        detect_row.addStretch(1)
        fv.addLayout(detect_row)
        v.addWidget(self.panel_forward)

        v.addLayout(make_row("访问令牌", self.edit_onebot_token))

        save_row = QHBoxLayout()
        self.btn_save_creds = QPushButton("保存通道配置")
        self.btn_save_creds.setObjectName("primary")
        self.btn_save_creds.clicked.connect(self._save_creds)
        save_row.addWidget(self.btn_save_creds)
        save_row.addStretch(1)
        v.addLayout(save_row)

    # ------------------------------------------------------------ 数据
    def load_credentials(self):
        """把 settings 里的 OneBot 字段灌进表单（宿主页与接入页共用）。"""
        s = self.ctx.settings
        self.edit_onebot_host.setText(s.qq_onebot_host)
        self.edit_onebot_port.setText(str(s.qq_onebot_port))
        self.edit_onebot_path.setText(s.qq_onebot_path)
        self.edit_onebot_token.setText(s.qq_onebot_token)
        mode_idx = self.combo_onebot_mode.findData(s.qq_onebot_mode)
        self.combo_onebot_mode.setCurrentIndex(mode_idx if mode_idx >= 0 else 0)
        self.edit_onebot_listen_host.setText(s.qq_onebot_listen_host)
        self._on_onebot_mode_changed()

    def _on_onebot_mode_changed(self):
        mode = str(self.combo_onebot_mode.currentData() or "reverse")
        self.panel_reverse.setVisible(mode == "reverse")
        self.panel_forward.setVisible(mode == "forward")
        self._refresh_reverse_url()

    def _refresh_reverse_url(self):
        host = self.edit_onebot_listen_host.text().strip() or "127.0.0.1"
        if host in ("0.0.0.0", "::", "[::]"):
            host = "127.0.0.1"
        port = int(getattr(self.ctx.settings, "nonebot_port", 0) or 12111)
        self.edit_reverse_port.setText(str(port))
        self.edit_reverse_url.setText(f"ws://{host}:{port}/onebot/v11/ws")

    def _copy_reverse_url(self):
        url = self.edit_reverse_url.text().strip()
        if not url:
            return
        QApplication.clipboard().setText(url)
        self.ctx.show_toast("反向 WS 地址已复制，去协议端粘贴即可")

    def _detect_onebot(self):
        host = self.edit_onebot_host.text().strip() or "127.0.0.1"
        if host not in ("127.0.0.1", "localhost", "::1"):
            self.ctx.show_toast("只自动检测本机地址；远程地址请手动填写")
            return
        ports = [3001, 3002, 3003, 8080, 8081, 8082, 6099, 16530, 23333]
        self.btn_detect_onebot.setEnabled(False)
        self.btn_detect_onebot.setText("检测中...")
        try:
            found = None
            for port in ports:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(0.35)
                try:
                    if sock.connect_ex((host, port)) == 0:
                        found = port
                        break
                finally:
                    sock.close()
            if found:
                self.edit_onebot_port.setText(str(found))
                self.ctx.show_toast(
                    f"检测到 {host}:{found} 端口开放（可能为 OneBot 协议端），请确认后保存")
            else:
                self.ctx.show_toast(
                    "未在常见端口检测到协议端；请确认协议端已启动并开启了正向 WS，或手动填写")
        finally:
            self.btn_detect_onebot.setEnabled(True)
            self.btn_detect_onebot.setText("检测协议端")

    def _save_creds(self):
        s = self.ctx.settings
        s.qq_onebot_host = self.edit_onebot_host.text().strip() or "127.0.0.1"
        s.qq_onebot_path = self.edit_onebot_path.text().strip() or "/onebot/v11/ws"
        s.qq_onebot_token = self.edit_onebot_token.text().strip()
        s.qq_onebot_mode = str(self.combo_onebot_mode.currentData() or "reverse")
        s.qq_onebot_listen_host = self.edit_onebot_listen_host.text().strip() or "127.0.0.1"
        try:
            s.qq_onebot_port = int(self.edit_onebot_port.text().strip() or "3001")
            if s.qq_onebot_port <= 0 or s.qq_onebot_port > 65535:
                raise ValueError
        except ValueError:
            self.ctx.show_toast("端口必须是 1~65535 的整数")
            return
        if self._extra_save is not None:
            self._extra_save()
        try:
            s.save()
        except OSError as e:
            self.ctx.show_toast("保存通道配置失败: " + str(e))
            return
        # 自动同步 .env 与适配器配置：重启机器人即可生效，无需手动改文件
        try:
            bot_mod.write_env(s)
            bot_mod.sync_qq_adapters(s)
        except Exception as e:  # noqa: BLE001
            self.ctx.show_toast("配置已保存，但自动写入 .env 失败: " + str(e))
            return
        self.ctx.show_toast("通道配置已保存并写入 .env，重启机器人后生效")
        if self._on_saved is not None:
            self._on_saved()


class WeChatChannelPanel(QWidget):
    """微信 ClawBot 登录卡：状态、二维码、扫码 / 配对码 / 重启。

    会员档判断放在面板里：独立页和接入页各有一个实例，谁都不需要知道对方存在。
    """

    def __init__(self, ctx: PageContext, show_badge=True, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self._show_badge = show_badge
        self._qr_url_cache = ""
        self._qr_shown_at = 0.0
        self._qr_auto_at = 0.0
        self._build_ui()
        self.refresh_status()

    # ------------------------------------------------------------ UI
    def _build_ui(self):
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)

        self.badge = StatusBadge("微信 ClawBot", "unknown")
        # 内联进「接入」页时外层那行已经有状态徽标了，这里不再重复一遍
        self.badge.setVisible(self._show_badge)
        v.addWidget(self.badge)
        self.login_hint = QLabel("")
        self.login_hint.setWordWrap(True)
        self.login_hint.setStyleSheet(f"color: {TEXT_3}; font-size: 12px;")
        self.login_hint.hide()
        v.addWidget(self.login_hint)
        self.bot_id = QLabel("—")
        self.login_time = QLabel("—")
        for lbl in (self.bot_id, self.login_time):
            lbl.setStyleSheet(f"color: {TEXT_3}; font-size: 12px;")
        v.addLayout(make_row("Bot ID", self.bot_id))
        v.addLayout(make_row("登录时间", self.login_time))

        # 二维码显示区
        self.qr_box = QLabel("暂无二维码\n点「重新扫码登录」后这里会自动显示")
        self.qr_box.setFixedSize(200, 200)
        self.qr_box.setAlignment(Qt.AlignCenter)
        self.qr_box.setStyleSheet(
            "background: #FFFFFF; color: #64748B; border-radius: 8px; font-size: 12px;")
        self.qr_box.setWordWrap(True)
        v.addWidget(self.qr_box, 0, Qt.AlignHCenter)

        v.addWidget(_tip(
            "说明：ClawBot 是私密个人助手通道，不支持群聊；其他用户无法添加你的 ClawBot。"))

        btns = QHBoxLayout()
        self.btn_reset = QPushButton("重新扫码登录")
        self.btn_reset.clicked.connect(self._reset_login)
        self.btn_qr_refresh = QPushButton("刷新二维码")
        self.btn_qr_refresh.setToolTip("立即获取一个新的微信扫码二维码（未登录时有效）")
        self.btn_qr_refresh.clicked.connect(self._refresh_qr)
        self.btn_qr = QPushButton("打开扫码链接")
        self.btn_qr.clicked.connect(self._open_qr)
        self.btn_verify_code = QPushButton("输入配对码")
        self.btn_verify_code.setToolTip("扫码后手机微信显示数字配对码时，点这里输入")
        self.btn_verify_code.clicked.connect(self._submit_verify_code)
        self.btn_restart = QPushButton("重启 NoneBot")
        self.btn_restart.clicked.connect(lambda: self._restart_bot())
        for b in (self.btn_reset, self.btn_qr_refresh, self.btn_qr,
                  self.btn_verify_code, self.btn_restart):
            btns.addWidget(b)
        btns.addStretch(1)
        v.addLayout(btns)

        self.ai_warn = QLabel("")
        self.ai_warn.setWordWrap(True)
        self.ai_warn.setStyleSheet(
            "color: #F59E0B; font-size: 12px; background: rgba(245,158,11,0.10);"
            "border-radius: 6px; padding: 6px 8px;")
        self.ai_warn.hide()
        v.addWidget(self.ai_warn)

    # ------------------------------------------------------------ 状态
    def _is_member(self) -> bool:
        try:
            return bool(lic_mod.feature_gate().get("member", False))
        except Exception:  # noqa: BLE001
            return False

    def set_buttons_enabled(self, enabled: bool):
        for b in (self.btn_reset, self.btn_qr_refresh, self.btn_qr,
                  self.btn_verify_code, self.btn_restart):
            b.setEnabled(enabled)

    def refresh_status(self):
        member = self._is_member()
        self.set_buttons_enabled(member)
        if not member:
            self.badge.set_status("stopped", "微信 ClawBot · 需会员档解锁")
            self.login_hint.hide()
            self.qr_box.setPixmap(QPixmap())
            self.qr_box.setText("免费版仅 QQ\n解锁后可扫码登录微信 ClawBot")
            self.ai_warn.hide()
            return

        try:
            wx = self.ctx.manager.wechat_status()
        except Exception as e:  # noqa: BLE001
            self.badge.set_status("warning", "微信 ClawBot · 状态读不到")
            self.login_hint.setText("状态读取失败：" + str(e))
            self.login_hint.show()
            return

        if not wx["installed"]:
            self.badge.set_status("unknown", "微信 ClawBot · 未安装适配器")
        elif wx["logged_in"]:
            if wx.get("connected"):
                self.badge.set_status("connected", "微信 ClawBot · 已连接")
            else:
                self.badge.set_status("warning", "微信 ClawBot · 已登录但未连接")
        else:
            self.badge.set_status("stopped", "微信 ClawBot · 未登录")
        self._update_login_hint(wx)
        self.bot_id.setText(str(wx["bot_id"] or "—"))
        t = wx["login_time"]
        self.login_time.setText(
            time.strftime("%Y-%m-%d %H:%M", time.localtime(t)) if t else "—")

        now = time.time()
        # 已登录：清空二维码区；按真实连接状态显示
        if wx["logged_in"]:
            self._qr_url_cache = ""
            self.qr_box.setPixmap(QPixmap())
            if wx.get("connected"):
                self.qr_box.setText("已连接 ✓\n微信里直接和 ClawBot 聊天")
            else:
                self.qr_box.setText("已登录但未连接\n" + (wx.get("reason") or "请检查机器人运行状态"))
        else:
            url = self.ctx.manager.wechat_qr_url()
            if url and url != self._qr_url_cache:
                self._qr_url_cache = url
                self._qr_shown_at = now
                pm = self._make_qr_pixmap(url)
                if pm is not None and not pm.isNull():
                    self.qr_box.setPixmap(pm)
                    self.qr_box.setToolTip(url)
                else:
                    self.qr_box.setPixmap(QPixmap())
                    self.qr_box.setText("二维码生成失败\n请点「打开扫码链接」")
            elif url:
                # URL 长时间未变（微信未扫码/未确认）：自动刷新
                if now - self._qr_shown_at > 120 and now - self._qr_auto_at > 180:
                    self._auto_refresh_qr()
            else:
                self._qr_url_cache = ""
                self.qr_box.setPixmap(QPixmap())
                self.qr_box.setText("暂无二维码\n点「重新扫码登录」后这里会自动显示")

        # AI 未配置提示
        cfg = ai_config.current_config(self.ctx.settings)
        if getattr(self.ctx.settings, "ai_enabled", True) and not (
                cfg.get("api_key") and cfg.get("api_url") and cfg.get("model")):
            self.ai_warn.setText("⚠️ AI 接口未配置：机器人能收到消息但不会自动回复，"
                                 "请到「AI 大脑」选择服务商并填入 API 密钥")
            self.ai_warn.show()
        else:
            self.ai_warn.hide()

    def _update_login_hint(self, wx: dict):
        status = str(wx.get("login_status") or "")
        if wx.get("logged_in"):
            if wx.get("connected"):
                self.login_hint.hide()
            else:
                self.login_hint.setText("⚠️ " + (wx.get("reason") or "连接中断"))
                self.login_hint.show()
            return
        texts = {
            "scaned": "已扫码 ✓ 请在微信里继续操作（确认连接；如显示配对码，点「输入配对码」提交）",
            "need_verifycode": "手机微信显示了数字配对码 → 点「输入配对码」提交后自动继续",
            "binded_redirect": "这个微信号已绑定过 ClawBot，无法重复绑定；请换微信号扫码，"
                               "或在微信 ClawBot 里先解绑",
            "verify_code_blocked": "配对码错误次数过多，二维码即将刷新，请稍后重新扫码",
            "expired": "二维码已过期，点「刷新二维码」重新获取",
            "timeout": "等待扫码超时，点「刷新二维码」重新获取",
            "redirect": "扫码通道已切换节点，继续等待微信确认…",
        }
        if status in texts:
            self.login_hint.setText(texts[status])
            self.login_hint.show()
        else:
            self.login_hint.hide()

    # ------------------------------------------------------------ 操作
    def _reset_login(self):
        if not self._is_member():
            return
        ret = QMessageBox.question(
            self, "微信重新扫码",
            "将清除微信 ClawBot 登录状态并重启 NoneBot，重启后点「打开扫码链接」扫码。\n\n确定继续吗？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if ret != QMessageBox.Yes:
            return
        self._qr_url_cache = ""
        self.qr_box.setPixmap(QPixmap())
        self.qr_box.setText("正在获取新二维码…")
        self._restart_bot(reset_wechat=True)

    def _refresh_qr(self):
        """手动刷新二维码：清除登录状态并重启 NoneBot，让适配器生成新二维码。"""
        if not self._is_member():
            return
        if self.ctx.manager.wechat_status().get("logged_in"):
            QMessageBox.information(self, "提示", "微信已登录，无需刷新二维码")
            return
        self._qr_url_cache = ""
        self.qr_box.setPixmap(QPixmap())
        self.qr_box.setText("正在获取新二维码…")
        self._restart_bot(reset_wechat=True)

    def _auto_refresh_qr(self):
        """二维码展示超过 120 秒未更新且未登录时，自动刷新一次（180 秒冷却）。"""
        self._qr_auto_at = time.time()
        self.qr_box.setPixmap(QPixmap())
        self.qr_box.setText("二维码可能已过期\n正在自动刷新…")
        self._qr_url_cache = ""
        self._restart_bot(reset_wechat=True)

    def _open_qr(self):
        url = self.ctx.manager.wechat_qr_url()
        if not url:
            QMessageBox.information(
                self, "提示",
                "暂未找到扫码链接。请先重启 NoneBot，等日志出现二维码后再试。")
            return
        webbrowser.open(url)

    def _submit_verify_code(self):
        code, ok = QInputDialog.getText(
            self, "输入配对码",
            "手机微信扫码后若显示数字配对码，请把数字填到这里（例如 123456）：")
        if not ok:
            return
        code = (code or "").strip()
        if not code:
            self.ctx.show_toast("配对码不能为空")
            return
        if self.ctx.manager.submit_wechat_verify_code(code):
            self.ctx.show_toast("配对码已提交，等待微信确认…")
        else:
            self.ctx.show_toast("配对码写入失败，请检查安装目录权限")

    def _make_qr_pixmap(self, url: str):
        """用 qrcode 库生成二维码 QPixmap；库缺失或失败返回 None。"""
        if qrcode is None:
            return None
        try:
            img = qrcode.make(url, box_size=6, border=2)
            img = img.convert("RGBA")
            data = img.tobytes("raw", "RGBA")
            qimg = QImage(data, img.width, img.height, QImage.Format_RGBA8888)
            pm = QPixmap.fromImage(qimg)
            return pm.scaled(188, 188, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        except Exception:  # noqa: BLE001
            return None

    def _restart_bot(self, reset_wechat=False):
        self.ctx.tasks.submit(
            "重启 NoneBot", "service", RestartBotTask,
            retryable=True, manager=self.ctx.manager,
            payload={"reset_wechat": reset_wechat},
        )
