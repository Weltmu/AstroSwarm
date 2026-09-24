# -*- coding: utf-8 -*-
"""星群账号独立窗口：邮箱登录/退出/认领本机，默认定位屏幕左上角。

与设置页解耦：窗口内自行完成 登录 → 认领本机 → 写授权 的全流程，
任何状态变化通过 account_changed 信号通知主程序刷新。
"""
import threading

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout,
)

from ...core import account
from ...core import license as lic_mod
from ..theme import TEXT_3
from .common import Worker


class AccountWindow(QDialog):
    account_changed = Signal()

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle("星群账号")
        self.setModal(False)
        self.setMinimumWidth(380)
        self._build_ui()
        self._refresh_status()
        self._move_top_left()

    # ------------------------------------------------------------ 定位
    def _move_top_left(self):
        geo = QGuiApplication.primaryScreen().availableGeometry()
        self.move(geo.left() + 12, geo.top() + 12)

    # ------------------------------------------------------------ UI
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(10)
        title = QLabel("星群账号")
        title.setObjectName("sectionTitle")
        root.addWidget(title)
        tip = QLabel(
            "邮箱登录即授权，无需激活码；登录后自动认领本机并同步授权状态。\n"
            "一个账号同一时间只允许一台设备登录，新设备登录会踢掉旧设备。")
        tip.setWordWrap(True)
        tip.setStyleSheet(f"color: {TEXT_3}; font-size: 12px;")
        root.addWidget(tip)
        self.acct_email = QLineEdit()
        self.acct_email.setPlaceholderText("网站注册邮箱")
        self.acct_password = QLineEdit()
        self.acct_password.setPlaceholderText("密码")
        self.acct_password.setEchoMode(QLineEdit.Password)
        self.acct_password.returnPressed.connect(self._on_account_button)
        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(self.acct_email, 1)
        row.addWidget(self.acct_password, 1)
        root.addLayout(row)
        self.acct_status = QLabel("未登录")
        self.acct_status.setWordWrap(True)
        self.acct_status.setStyleSheet(f"color: {TEXT_3}; font-size: 12px;")
        root.addWidget(self.acct_status)
        btns = QHBoxLayout()
        btns.setSpacing(6)
        self.btn_account = QPushButton("登录并同步")
        self.btn_account.setObjectName("primary")
        self.btn_account.setMinimumHeight(32)
        self.btn_account.clicked.connect(self._on_account_button)
        btns.addWidget(self.btn_account)
        btns.addStretch(1)
        root.addLayout(btns)

    # ------------------------------------------------------------ 状态
    def _refresh_status(self):
        acc = account.load_account()
        self.btn_account.setText("退出账号" if acc else "登录并同步")
        self.acct_status.setText(f"已登录：{acc.get('email')}" if acc else "未登录")

    def _on_account_button(self):
        if account.load_account():
            self._logout_account()
        else:
            self._login_account()

    # ------------------------------------------------------------ 登录
    def _login_account(self):
        email = self.acct_email.text().strip()
        pwd = self.acct_password.text()
        if not email or not pwd:
            self.acct_status.setText("请填写邮箱和密码")
            return
        self.acct_status.setText("登录中...")
        worker = Worker(self)
        worker.finished.connect(self._on_account_login)
        threading.Thread(
            target=lambda: worker.run(lambda: account.login(email, pwd)),
            daemon=True,
        ).start()

    def _on_account_login(self, res):
        if res.get("ok"):
            self.acct_status.setText(
                f"已登录：{res.get('email')}（{self._plan_tag(res.get('plan'))}）")
            self.btn_account.setText("退出账号")
            self._claim_device()
            return
        detail = res.get("detail") or res.get("reason") or "登录失败"
        if isinstance(detail, list):
            detail = "邮箱或密码格式不正确"
        self.acct_status.setText("登录失败：" + str(detail))

    # ------------------------------------------------------------ 认领本机
    def _claim_device(self):
        acc = account.load_account()
        if not acc:
            self.acct_status.setText("登录状态丢失，请重新登录")
            return
        mid = lic_mod.machine_code()
        self.acct_status.setText("正在认领本机并同步授权...")
        worker = Worker(self)
        worker.finished.connect(self._on_claim_device)
        threading.Thread(
            target=lambda: worker.run(lambda: account.claim_device(acc["token"], mid)),
            daemon=True,
        ).start()

    def _on_claim_device(self, res):
        if res.get("ok"):
            key = res.get("license") or ""
            if key:
                act = lic_mod.activate(key)
                if not act.get("ok"):
                    self.acct_status.setText("授权生效失败：" + str(act.get("reason")))
                    return
            plan = res.get("plan")
            lic_mod.save_plan(plan, res.get("plan_expires_at") or 0,
                              res.get("owned_plugins"),
                              sig=res.get("entitlement_sig") or "",
                              machine_id=res.get("entitlement_machine") or lic_mod.machine_code())
            txt = f"已登录并绑定本机（{self._plan_tag(plan)}）"
            if res.get("kicked_machine"):
                txt += "，旧设备已下线"
            self.acct_status.setText(txt)
            self.account_changed.emit()
            # claim 的响应里不一定带权益签名，而「有没有签名」决定付费能力是否生效，
            # 所以认领后再按权威接口同步一次（拿不到就保持现状，不覆盖）。
            self._sync_entitlement_from_me()
            return
        detail = res.get("detail") or res.get("reason") or "认领失败"
        if isinstance(detail, list):
            detail = "认领信息有误"
        self.acct_status.setText("认领失败：" + str(detail))

    def _sync_entitlement_from_me(self):
        """认领后补一次权益同步：以 /api/account/me 为准补上签名。"""
        acc = account.load_account()
        if not acc:
            return
        worker = Worker(self)
        worker.finished.connect(self._on_me_refreshed)
        threading.Thread(
            target=lambda: worker.run(lambda: account.me(acc["token"])),
            daemon=True,
        ).start()

    def _on_me_refreshed(self, res):
        if not isinstance(res, dict) or not res.get("ok"):
            return
        sig = str(res.get("entitlement_sig") or "")
        if not sig:
            # 服务器没下发签名：保持认领时写下的那份，绝不把已有签名覆盖成空
            return
        plan = str(res.get("plan") or "none")
        lic_mod.save_plan(plan, res.get("plan_expires_at") or 0,
                          res.get("owned_plugins"), sig=sig,
                          machine_id=res.get("entitlement_machine")
                          or lic_mod.machine_code())
        self.acct_status.setText(
            f"已登录并绑定本机（{self._plan_tag(plan)}）· 权益已同步")
        self.account_changed.emit()

    @staticmethod
    def _plan_tag(plan) -> str:
        """档位说明：全解锁 / 会员（微信通道） / 试用 / 免费，不再只写「付费版」。"""
        from ...core import plans as plans_mod

        name = str(plan or "").lower()
        if plans_mod.allows_all(name):
            return "永久档 · 已解锁全部能力包"
        if name in plans_mod.MEMBER_PLANS:
            return "会员档 · 微信通道已解锁"
        if name == "trial":
            return "试用 · 仅 QQ"
        return "免费版 · 仅 QQ"

    # ------------------------------------------------------------ 退出
    def _logout_account(self):
        account.clear_account()
        self._refresh_status()
        self.account_changed.emit()
