"""插件管理：官方插件市场 + 本地插件列表与依赖重装。

默认只允许安装官方市场插件（manifest 校验 + SHA256）；第三方 PyPI / zip
安装仅在「设置 → 开发者模式」开启后恢复，并由用户自行承担兼容与合规责任。
"""
import os
import threading
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QFormLayout,
    QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSpinBox,
    QVBoxLayout, QWidget,
)

from ...core import account
from ...core import license as lic_mod
from ...core import nonebot_registry
from ...core import plugin_market
from ...core import tool_packs
from ...core.plugins import (
    detect_dependencies_from_zip,
    list_local_plugins,
    list_store_plugins,
)
from ...tasks.workers import (
    CheckDepsTask, InstallMarketPackTask, InstallMarketPluginTask,
    InstallPluginTask, RestartBotTask,
)
from ..theme import TEXT_3
from ..widgets import GlassPanel
from .common import DepsConfirmDialog, PageContext, TaskPanel, Worker

INSTALL_TASK_NAMES = ("安装插件", "安装市场插件", "安装依赖", "检查插件依赖")

# 「高级（开发者）」折叠区标题（收起 / 展开两态）
_ADVANCED_TITLE = "高级（开发者）　▾"
_ADVANCED_OPEN = "收起高级（开发者）　▴"

_PERM_LABELS = {
    "send_message": "发送消息",
    "group_admin": "群管理（禁言/撤回/全员禁言）",
    "timer": "定时任务",
    "memory": "记忆读写",
    "network": "网络访问",
    "media": "媒体处理（图片/语音）",
}


def _detail_of(res) -> str:
    """账号服务的报错字段名不统一（detail / reason / error），统一取一句话。"""
    if not isinstance(res, dict):
        return "服务器没有返回内容"
    detail = res.get("detail") or res.get("reason") or res.get("error") or "未知错误"
    if isinstance(detail, list):
        return "格式不正确"
    return str(detail)


class PluginsPage(QWidget):
    def __init__(self, ctx: PageContext):
        super().__init__()
        self.ctx = ctx
        self._task_tid = None
        self._market_entries = {}
        self._nb_entries = []
        self._nb_loaded = False
        self._entitlements = lic_mod.entitlements()
        self.setAcceptDrops(True)
        self._build_ui()
        self._connect_tasks()
        self.refresh_lists()
        self._load_market()

    # ------------------------------------------------------------ UI
    @staticmethod
    def _note(text: str) -> QLabel:
        """说明文字：统一 12px 灰色（TEXT_3），不要用正文样式抢注意力。"""
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(f"color: {TEXT_3}; font-size: 12px;")
        return lbl

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        content = QWidget()
        # 间距只用 8/12/16/24：块内 8~16，块之间 24（外围 ≥ 内部 × 1.5）
        outer = QVBoxLayout(content)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(24)

        # ---- 标题 / 副标题 ----
        head = QWidget()
        hv = QVBoxLayout(head)
        hv.setContentsMargins(0, 0, 0, 0)
        hv.setSpacing(8)
        title = QLabel("插件管理")
        title.setObjectName("pageTitle")
        sub = QLabel("插件商店（直连星群服务器）与本地插件管理；"
                     "第三方安装等开发者入口收在页面下方「高级（开发者）」里。")
        sub.setObjectName("pageSub")
        sub.setWordWrap(True)
        hv.addWidget(title)
        hv.addWidget(sub)
        outer.addWidget(head)

        # ---- 插件商店：列表 + 一行操作（本页唯一主按钮「安装」）----
        store = GlassPanel()
        sv = QVBoxLayout(store)
        sv.setContentsMargins(16, 16, 16, 16)
        sv.setSpacing(12)
        sl = QLabel("插件商店")
        sl.setObjectName("sectionTitle")
        sv.addWidget(sl)
        sv.addWidget(self._note(
            "直连星群服务器拉取插件清单；安装前自动校验协议端兼容性与 SHA256。"
            "插件全部免费（随主仓库开源），选中后点「安装」即可。"))
        self.market_list = QListWidget()
        self.market_list.setMinimumHeight(260)
        self.market_list.itemDoubleClicked.connect(lambda _i: self._install_market_plugin())
        sv.addWidget(self.market_list, 1)
        m_row = QHBoxLayout()
        m_row.setSpacing(8)
        m_lbl = self._note("分类")
        self.market_combo = QComboBox()
        self.market_combo.addItem("全部分类", "")
        self.market_combo.currentIndexChanged.connect(self._refresh_market_list)
        self.btn_market_refresh = QPushButton("刷新")
        self.btn_market_refresh.setObjectName("ghost")
        self.btn_market_refresh.clicked.connect(self._load_market)
        self.btn_market_install = QPushButton("安装")
        self.btn_market_install.setObjectName("primary")
        self.btn_market_install.clicked.connect(self._install_market_plugin)
        m_row.addWidget(m_lbl)
        m_row.addWidget(self.market_combo, 1)
        m_row.addWidget(self.btn_market_refresh)
        m_row.addWidget(self.btn_market_install)
        sv.addLayout(m_row)
        self.market_status = self._note("正在加载插件商店...")
        sv.addWidget(self.market_status)

        # ---- 兑换码 / 权益刷新（与无头端控制台「兑换」走同一个账号服务接口）----
        # 兑换码发的是账号档位（时长/永久），插件本身已全部免费，不需要它解锁插件。
        r_row = QHBoxLayout()
        r_row.setSpacing(8)
        self.redeem_edit = QLineEdit()
        self.redeem_edit.setPlaceholderText("兑换码（活动 / 人工发放的码）")
        self.redeem_edit.returnPressed.connect(self._redeem_code)
        self.btn_redeem = QPushButton("兑换")
        self.btn_redeem.setObjectName("ghost")
        self.btn_redeem.clicked.connect(self._redeem_code)
        self.btn_ent_refresh = QPushButton("刷新权益")
        self.btn_ent_refresh.setObjectName("ghost")
        self.btn_ent_refresh.setToolTip(
            "登录 / 兑换之后点这里：去星群账号重新拉一次账号档位。\n"
            "插件已全部免费，装插件不依赖账号权益。")
        self.btn_ent_refresh.clicked.connect(self._refresh_entitlement)
        r_row.addWidget(self.redeem_edit, 1)
        r_row.addWidget(self.btn_redeem)
        r_row.addWidget(self.btn_ent_refresh)
        sv.addLayout(r_row)
        self.ent_status = self._note("")
        sv.addWidget(self.ent_status)
        outer.addWidget(store, 3)

        # ---- 已装能力包：列表 + 详情 / 配置 / 卸载（全是次要按钮）----
        pack = GlassPanel()
        pv = QVBoxLayout(pack)
        pv.setContentsMargins(16, 16, 16, 16)
        pv.setSpacing(12)
        pl = QLabel("已装能力包")
        pl.setObjectName("sectionTitle")
        pv.addWidget(pl)
        pv.addWidget(self._note(
            "全部插件免费。选中后可看详情、改参数；"
            "卸载只影响本机，重启机器人后不再加载。"))
        self.pack_list = QListWidget()
        self.pack_list.setMinimumHeight(120)
        self.pack_list.itemDoubleClicked.connect(lambda _i: self._open_pack_detail())
        pv.addWidget(self.pack_list, 1)
        pack_row = QHBoxLayout()
        pack_row.setSpacing(8)
        self.btn_pack_detail = QPushButton("详情")
        self.btn_pack_detail.setObjectName("ghost")
        self.btn_pack_detail.clicked.connect(self._open_pack_detail)
        self.btn_pack_config = QPushButton("配置")
        self.btn_pack_config.setObjectName("ghost")
        self.btn_pack_config.clicked.connect(self._config_pack)
        self.btn_pack_uninstall = QPushButton("卸载")
        self.btn_pack_uninstall.setObjectName("ghost")
        self.btn_pack_uninstall.clicked.connect(self._uninstall_pack)
        pack_row.addWidget(self.btn_pack_detail)
        pack_row.addWidget(self.btn_pack_config)
        pack_row.addWidget(self.btn_pack_uninstall)
        pack_row.addStretch(1)
        pv.addLayout(pack_row)
        self.pack_status = self._note("正在读取已装能力包...")
        pv.addWidget(self.pack_status)
        outer.addWidget(pack)

        # ---- 高级（开发者）：默认收起，点标题才展开 ----
        outer.addWidget(self._build_advanced_section())

        # ---- 本地插件（列表 + 运维按钮）+ 已安装（pyproject 记录）----
        local = GlassPanel(strong=True)
        lv = QVBoxLayout(local)
        lv.setContentsMargins(16, 16, 16, 16)
        lv.setSpacing(12)
        ll = QLabel("本地插件（src/plugins）")
        ll.setObjectName("sectionTitle")
        lv.addWidget(ll)
        lv.addWidget(self._note(
            "这是插件目录里实际存在的内容。「重装缺失依赖」会先扫描所选插件声明的依赖，"
            "发现缺失后再让你确认安装。"))
        self.local_list = QListWidget()
        self.local_list.setMinimumHeight(160)
        lv.addWidget(self.local_list, 1)
        btns = QHBoxLayout()
        btns.setSpacing(8)
        btn_reinstall = QPushButton("重装缺失依赖")
        btn_reinstall.setObjectName("ghost")
        btn_reinstall.setToolTip("后台扫描所选插件声明的依赖，发现缺失后确认安装（清华镜像，失败自动切官方源）")
        btn_reinstall.clicked.connect(self._reinstall_deps)
        btn_refresh = QPushButton("刷新列表")
        btn_refresh.setObjectName("ghost")
        btn_refresh.clicked.connect(self.refresh_lists)
        btn_open_dir = QPushButton("打开插件目录")
        btn_open_dir.setObjectName("ghost")
        btn_open_dir.clicked.connect(lambda: os.startfile(str(self.ctx.settings.plugins_dir)))
        self.btn_restart = QPushButton("重启 NoneBot 生效")
        self.btn_restart.setObjectName("ghost")
        self.btn_restart.clicked.connect(self._restart_bot)
        btns.addWidget(btn_reinstall)
        btns.addWidget(btn_refresh)
        btns.addWidget(btn_open_dir)
        btns.addStretch(1)
        btns.addWidget(self.btn_restart)
        lv.addLayout(btns)
        lv.addWidget(self._note("已安装（pyproject 记录）"))
        self.store_list = QListWidget()
        self.store_list.setMinimumHeight(120)
        lv.addWidget(self.store_list, 1)
        outer.addWidget(local, 2)

        # ---- 任务面板 ----
        task_glass = GlassPanel()
        tv = QVBoxLayout(task_glass)
        tv.setContentsMargins(16, 16, 16, 16)
        tv.setSpacing(12)
        tl = QLabel("安装任务")
        tl.setObjectName("sectionTitle")
        tv.addWidget(tl)
        self.task_panel = TaskPanel(self.ctx.tasks)
        self.task_panel.setVisible(False)
        self.task_panel.action_requested.connect(self._on_task_action)
        tv.addWidget(self.task_panel)
        outer.addWidget(task_glass)

        self.scroll.setWidget(content)
        root.addWidget(self.scroll)
        self._apply_mode()

    def _build_advanced_section(self) -> GlassPanel:
        """高级（开发者）：第三方 zip / PyPI / NoneBot 在线市场，默认收起。"""
        panel = GlassPanel()
        av = QVBoxLayout(panel)
        av.setContentsMargins(16, 16, 16, 16)
        av.setSpacing(12)
        self._advanced_open = False
        self.btn_advanced = QPushButton(_ADVANCED_TITLE)
        self.btn_advanced.setObjectName("ghost")
        self.btn_advanced.setCheckable(True)
        self.btn_advanced.setCursor(Qt.PointingHandCursor)
        self.btn_advanced.toggled.connect(self._toggle_advanced)
        av.addWidget(self.btn_advanced)

        body = QWidget()
        bv = QVBoxLayout(body)
        bv.setContentsMargins(0, 0, 0, 0)
        bv.setSpacing(24)
        bv.addWidget(self._note(
            "下面这些入口要在「设置 → 开发者模式」开启后才可用；"
            "插件兼容性、安全性与平台协议合规由你自行承担。"))

        # 第三方 zip（开发者模式 + 拖拽）
        zip_block = QWidget()
        zb = QVBoxLayout(zip_block)
        zb.setContentsMargins(0, 0, 0, 0)
        zb.setSpacing(8)
        zh = QLabel("第三方 zip 安装")
        zh.setObjectName("sectionTitle")
        zb.addWidget(zh)
        self.zip_edit = QLineEdit()
        self.zip_edit.setPlaceholderText("插件压缩包路径（开发者模式）")
        z_row = QHBoxLayout()
        z_row.setSpacing(8)
        self.btn_pick = QPushButton("选择 zip ...")
        self.btn_pick.setObjectName("ghost")
        self.btn_pick.clicked.connect(self._pick_zip)
        self.btn_zip = QPushButton("安装")
        self.btn_zip.setObjectName("ghost")
        self.btn_zip.clicked.connect(self._install_zip)
        z_row.addWidget(self.zip_edit, 1)
        z_row.addWidget(self.btn_pick)
        z_row.addWidget(self.btn_zip)
        zb.addLayout(z_row)
        drop_hint = QLabel("⇩ 开发者模式下可把 .zip 拖到本页")
        drop_hint.setAlignment(Qt.AlignCenter)
        drop_hint.setStyleSheet(
            f"color: {TEXT_3}; font-size: 12px; border: 1px dashed rgba(255,255,255,0.18);"
            "border-radius: 8px; padding: 12px;")
        zb.addWidget(drop_hint)
        bv.addWidget(zip_block)

        # PyPI（开发者模式）
        pypi_block = QWidget()
        pb = QVBoxLayout(pypi_block)
        pb.setContentsMargins(0, 0, 0, 0)
        pb.setSpacing(8)
        ph = QLabel("从 PyPI 安装")
        ph.setObjectName("sectionTitle")
        pb.addWidget(ph)
        self.store_edit = QLineEdit()
        self.store_edit.setPlaceholderText("PyPI 包名（开发者模式）")
        p_row = QHBoxLayout()
        p_row.setSpacing(8)
        self.btn_store = QPushButton("安装")
        self.btn_store.setObjectName("ghost")
        self.btn_store.clicked.connect(self._install_store)
        p_row.addWidget(self.store_edit, 1)
        p_row.addWidget(self.btn_store)
        pb.addLayout(p_row)
        pb.addWidget(self._note("不推荐：任意 NoneBot 插件都能装，兼容与合规由用户自负。"))
        bv.addWidget(pypi_block)

        # NoneBot 官方插件市场（在线搜索，仅开发者模式可见）
        nb = QWidget()
        nv = QVBoxLayout(nb)
        nv.setContentsMargins(0, 0, 0, 0)
        nv.setSpacing(12)
        nl = QLabel("NoneBot 在线市场")
        nl.setObjectName("sectionTitle")
        nv.addWidget(nl)
        nv.addWidget(self._note(
            "在线搜索 nonebot 官方社区开源插件（仅开发者模式可用）。"
            "插件未经星群校验，源码与许可由作者负责，安装前请先阅读声明。"))
        nb_row = QHBoxLayout()
        nb_row.setSpacing(8)
        self.nb_search = QLineEdit()
        self.nb_search.setPlaceholderText("搜索插件名 / 包名 / 作者 / 简介 ...")
        self.nb_search.returnPressed.connect(self._request_nonebot_market)
        self.btn_nb_search = QPushButton("搜索")
        self.btn_nb_search.setObjectName("ghost")
        self.btn_nb_search.clicked.connect(self._request_nonebot_market)
        self.btn_nb_refresh = QPushButton("刷新")
        self.btn_nb_refresh.setObjectName("ghost")
        self.btn_nb_refresh.clicked.connect(self._load_nonebot_market)
        nb_row.addWidget(self.nb_search, 1)
        nb_row.addWidget(self.btn_nb_search)
        nb_row.addWidget(self.btn_nb_refresh)
        nv.addLayout(nb_row)
        self.nb_list = QListWidget()
        self.nb_list.setMinimumHeight(160)
        self.nb_list.itemDoubleClicked.connect(
            lambda _i: self._install_nonebot_plugin())
        self.nb_list.currentItemChanged.connect(
            lambda *_: self._update_nonebot_buttons())
        nv.addWidget(self.nb_list)
        self.nb_status = self._note("进入「开发者模式」后可搜索 NoneBot 插件")
        nv.addWidget(self.nb_status)
        nb_bottom = QHBoxLayout()
        nb_bottom.setSpacing(8)
        self.btn_nb_install = QPushButton("安装选中")
        self.btn_nb_install.setObjectName("ghost")
        self.btn_nb_install.setEnabled(False)
        self.btn_nb_install.clicked.connect(self._install_nonebot_plugin)
        nb_bottom.addWidget(self.btn_nb_install)
        nb_bottom.addStretch(1)
        nv.addLayout(nb_bottom)
        self.nb_panel = nb
        bv.addWidget(nb)

        body.setVisible(False)
        av.addWidget(body)
        self._advanced_body = body
        return panel

    def _toggle_advanced(self, expanded=None):
        """展开 / 收起高级区（默认收起；点标题切换）。"""
        show = (not self._advanced_open) if expanded is None else bool(expanded)
        self._advanced_open = show
        self._advanced_body.setVisible(show)
        if self.btn_advanced.isChecked() != show:
            self.btn_advanced.blockSignals(True)
            self.btn_advanced.setChecked(show)
            self.btn_advanced.blockSignals(False)
        self.btn_advanced.setText(_ADVANCED_OPEN if show else _ADVANCED_TITLE)

    def _connect_tasks(self):
        t = self.ctx.tasks
        t.started.connect(self._on_task_started)
        t.finished.connect(self._on_task_finished)

    def showEvent(self, event):
        super().showEvent(event)
        self._apply_mode()
        # 每次进入页面刷新本地账号档位（登录/同步后可能已变化）
        self._entitlements = lic_mod.entitlements()
        self._refresh_market_list()
        # 开发者模式下首次进入页面，自动拉取 NoneBot 官方商店
        if bool(getattr(self.ctx.settings, "developer_mode", False)) and not self._nb_loaded:
            self._load_nonebot_market()

    # ------------------------------------------------------------ 模式
    def _apply_mode(self):
        """按开发者模式启用/禁用第三方安装入口（PyPI / zip）。"""
        dev = bool(getattr(self.ctx.settings, "developer_mode", False))
        for w in (self.store_edit, self.btn_store, self.zip_edit,
                  self.btn_pick, self.btn_zip):
            w.setEnabled(dev)
        self.nb_panel.setVisible(dev)

    # ------------------------------------------------------------ 任务
    def _on_task_started(self, tid, name):
        if name in INSTALL_TASK_NAMES:
            self._task_tid = tid
            self.task_panel.bind(tid)
            self.task_panel.setVisible(True)

    def _on_task_finished(self, tid, status, result):
        if tid != self._task_tid:
            return
        self.task_panel.bind(tid)
        self.refresh_lists()
        st = self.ctx.tasks.get(tid)
        name = st.task_name if st else ""
        if status == "success" and name == "检查插件依赖":
            self._on_check_done(result)
        elif status == "success" and name in ("安装插件", "安装依赖"):
            self.ctx.show_toast("安装完成，点击「重启 NoneBot 生效」")
        elif status == "success" and name == "安装市场插件":
            self.ctx.show_toast("插件安装完成，点击「重启 NoneBot 生效」")

    def _on_check_done(self, result):
        missing = result.get("missing") or []
        if not missing:
            self.ctx.show_toast("该插件依赖完整，无需安装")
            return
        ret = QMessageBox.question(
            self, "安装缺失依赖",
            f"发现 {len(missing)} 个缺失依赖：\n\n" +
            "\n".join("• " + d for d in missing) +
            "\n\n是否现在安装？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes,
        )
        if ret != QMessageBox.Yes:
            return
        self.ctx.tasks.submit(
            "安装依赖", "install", InstallPluginTask,
            payload={"kind": "deps", "target": list(missing)},
            retryable=True, settings=self.ctx.settings,
        )

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
    def _install_store(self):
        name = self.store_edit.text().strip()
        if not name:
            QMessageBox.information(self, "提示", "请输入插件包名")
            return
        if self.ctx.tasks.has_active("install"):
            QMessageBox.information(self, "提示", "已有安装任务正在执行，请稍候")
            return
        self.ctx.tasks.submit(
            "安装插件", "install", InstallPluginTask,
            payload={"kind": "store", "target": name},
            retryable=True, settings=self.ctx.settings,
        )

    def _pick_zip(self):
        f, _ = QFileDialog.getOpenFileName(self, "选择插件 zip", "", "ZIP 文件 (*.zip)")
        if f:
            self.zip_edit.setText(f)

    def _install_zip(self):
        p = self.zip_edit.text().strip()
        if not p:
            QMessageBox.information(self, "提示", "请先选择 zip 文件")
            return
        if self.ctx.tasks.has_active("install"):
            QMessageBox.information(self, "提示", "已有安装任务正在执行，请稍候")
            return
        deps = []
        try:
            deps = detect_dependencies_from_zip(p)
        except Exception as e:  # noqa: BLE001
            self.ctx.show_toast("读取 zip 依赖信息失败: " + str(e))
        if deps:
            decision, _never = DepsConfirmDialog(deps, self).decision()
            if decision == "cancel":
                return
            if decision == "skip":
                deps = []
        self.ctx.tasks.submit(
            "安装插件", "install", InstallPluginTask,
            payload={"kind": "zip", "target": p, "deps": deps},
            retryable=True, settings=self.ctx.settings,
        )

    # ------------------------------------------------------------ 兑换码 / 权益
    @staticmethod
    def _account_token() -> str:
        acc = account.load_account() or {}
        return str(acc.get("token") or "")

    def _redeem_code(self):
        """兑换码：只有星群账号服务知道码是真是假，本机只负责转发（与无头端同一接口）。

        兑换成功后必须再拉一次 /me：兑换接口不回签名，而「有没有签名」决定账号档位
        能不能生效，只落 plan 不落签名等于白兑。
        """
        code = self.redeem_edit.text().strip()
        if not code:
            self.ctx.show_toast("请先填兑换码")
            return
        token = self._account_token()
        if not token:
            self.ctx.show_toast("本机还没登录星群账号：先去「账号」里登录，再回来兑换")
            return
        self.btn_redeem.setEnabled(False)
        self.ent_status.setText("正在兑换…")
        worker = Worker(self)
        worker.finished.connect(self._on_redeemed)
        threading.Thread(
            target=lambda: worker.run(lambda: account.redeem(token, code)),
            daemon=True).start()

    def _on_redeemed(self, res):
        self.btn_redeem.setEnabled(True)
        if not isinstance(res, dict) or res.get("ok") is False:
            self.ent_status.setText("兑换失败：" + _detail_of(res))
            return
        self.redeem_edit.clear()
        self.ent_status.setText("兑换成功，正在刷新权益…")
        self._refresh_entitlement(silent=True)

    def _refresh_entitlement(self, silent=False):
        """去账号服务重新拉权益（刚买完 / 刚兑换完点这个）。"""
        token = self._account_token()
        if not token:
            self.ent_status.setText("本机还没登录星群账号：先去「账号」里登录")
            return
        self.btn_ent_refresh.setEnabled(False)
        if not silent:
            self.ent_status.setText("正在刷新权益…")
        worker = Worker(self)
        worker.finished.connect(self._on_entitlement_refreshed)
        threading.Thread(target=lambda: worker.run(lambda: account.me(token)), daemon=True).start()

    def _on_entitlement_refreshed(self, res):
        self.btn_ent_refresh.setEnabled(True)
        if not isinstance(res, dict) or res.get("ok") is False:
            self.ent_status.setText("权益刷新失败：" + _detail_of(res))
            return
        if not lic_mod.save_entitlements_from_account(res):
            # 服务器这次没下发签名：保持本机现有权益（以前会把签名写成空 -> 掉回未开通）
            self.ent_status.setText("权益已同步，但服务器没下发签名（本机现有权益保持不变）")
            return
        ent = lic_mod.entitlements()
        owned = ent.get("owned_plugins") or []
        self.ent_status.setText(
            "账号档位已刷新：" + ("、".join(owned) if owned else "无额外档位"))
        self._load_market()

    # ------------------------------------------------------------ 官方市场
    def _load_market(self):
        self.market_status.setText("正在加载插件商店...")
        worker = Worker(self)
        worker.finished.connect(self._on_market_loaded)

        def _run():
            entitlements = lic_mod.entitlements()
            try:
                acc = account.load_account()
                if acc and acc.get("token"):
                    me = account.me(acc["token"])
                    if me.get("ok") is not False and me.get("plan"):
                        # 拉最新权益并写本地，商店立即按最新权益显示。
                        # 走带保护的 helper：服务器没下发签名时不覆盖本机已有权益
                        if lic_mod.save_entitlements_from_account(me):
                            entitlements = lic_mod.entitlements()
            except Exception:  # noqa: BLE001
                pass
            return {
                "plugins": plugin_market.fetch_market(plugin_market.MARKET_DEFAULT_URL),
                "entitlements": entitlements,
            }

        threading.Thread(target=lambda: worker.run(_run), daemon=True).start()

    def _on_market_loaded(self, res):
        plugins = res.get("plugins") or [] if isinstance(res, dict) else []
        self._entitlements = (
            res.get("entitlements") if isinstance(res, dict)
            else lic_mod.entitlements()
        ) or lic_mod.entitlements()
        entries = {}
        categories = set()
        skipped = 0
        for e in plugins:
            if plugin_market.validate_market_plugin(e) is not None:
                skipped += 1
                continue
            entries[str(e["id"])] = e
            categories.add(str(e.get("category") or "未分类"))
        self._market_entries = entries
        self.market_combo.blockSignals(True)
        self.market_combo.clear()
        self.market_combo.addItem("全部分类", "")
        for c in sorted(categories):
            self.market_combo.addItem(c, c)
        self.market_combo.blockSignals(False)
        self._refresh_market_list()
        if not entries:
            # 把失败原因（验签失败/不在白名单/网络不通）直说，别只显示"暂不可用"
            why = str(getattr(plugin_market, "LAST_ERROR", "") or "").strip()
            self.market_status.setText(
                f"插件商店加载失败：{why}（可点「刷新」重试）" if why
                else "插件商店暂不可用或暂无内容，可稍后点「刷新」重试")
            return
        acc = account.load_account()
        if acc:
            plan_label = "当前账号：" + (
                "已开通" if self._entitlements.get("full") else "仅 QQ 通道")
        else:
            plan_label = "未登录星群账号（插件不受影响）"
        self.ent_status.setText(plan_label)
        self.market_status.setText(
            f"插件商店已加载：{len(entries)} 个（全部免费）· {plan_label}"
            + (f"（{skipped} 个条目校验未通过已跳过）" if skipped else ""))

    def _refresh_market_list(self):
        cat = str(self.market_combo.currentData() or "")
        self.market_list.clear()
        for eid, e in self._market_entries.items():
            if cat and str(e.get("category") or "") != cat:
                continue
            access = plugin_market.plugin_access(e, self._entitlements)
            item = QListWidgetItem(
                f"[{access['label']}] {e.get('name')}  v{e.get('version')}"
                f"  [{e.get('category') or '未分类'}]")
            item.setData(Qt.UserRole, eid)
            tip = str(e.get("description") or "")
            tip += "\n\n可安装：" + access["reason"]
            item.setToolTip(tip)
            item.setForeground(QColor("#34D399"))
            self.market_list.addItem(item)

    def _install_market_plugin(self):
        item = self.market_list.currentItem()
        if item is None:
            QMessageBox.information(self, "提示", "请先在官方插件市场选择一个插件")
            return
        e = self._market_entries.get(str(item.data(Qt.UserRole) or ""))
        if not e:
            QMessageBox.information(self, "提示", "插件信息已失效，请点「刷新」")
            return
        err = plugin_market.validate_market_plugin(e)
        if err:
            QMessageBox.warning(self, "校验失败", err)
            return
        perms = e.get("permissions") or []
        if perms:
            labels = [
                "• " + _PERM_LABELS.get(str(p), str(p))
                for p in perms if str(p)
            ]
            ret = QMessageBox.question(
                self, "插件权限确认",
                f"「{e.get('name')}」将使用以下权限：\n\n"
                + "\n".join(labels)
                + "\n\n是否安装？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
            if ret != QMessageBox.Yes:
                return
        if self.ctx.tasks.has_active("install"):
            QMessageBox.information(self, "提示", "已有安装任务正在执行，请稍候")
            return
        kind = str(e.get("kind") or "")
        if kind in ("tool-pack", "persona-pack", "behavior-pack"):
            self.ctx.tasks.submit(
                "安装市场插件", "install", InstallMarketPackTask,
                payload={"entry": e, "url": e["url"], "sha256": e["sha256"],
                         "name": e["name"], "version": e["version"]},
                retryable=True, settings=self.ctx.settings,
            )
        else:
            self.ctx.tasks.submit(
                "安装市场插件", "install", InstallMarketPluginTask,
                payload={"url": e["url"], "sha256": e["sha256"],
                         "name": e["name"], "version": e["version"]},
                retryable=True, settings=self.ctx.settings,
            )

    def _uninstall_pack(self):
        item = self.pack_list.currentItem()
        if not item:
            QMessageBox.information(self, "提示", "请先选择一个已装能力包")
            return
        pid = str(item.data(Qt.UserRole) or "")
        ret = QMessageBox.question(
            self, "卸载能力包",
            f"确定卸载「{item.text()}」吗？卸载后重启机器人即不再加载。",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ret != QMessageBox.Yes:
            return
        try:
            tool_packs.uninstall_pack(self.ctx.settings, pid)
        except OSError as e:
            self.ctx.show_toast("卸载失败: " + str(e))
            return
        self.refresh_lists()
        self.ctx.show_toast("能力包已卸载，重启机器人后生效")

    def _selected_pack_id(self) -> str:
        item = self.pack_list.currentItem()
        if not item:
            QMessageBox.information(self, "提示", "请先选择一个已装能力包")
            return ""
        return str(item.data(Qt.UserRole) or "")

    def _open_pack_detail(self):
        """能力包详情：介绍 / 功能 / 参数（参数按 manifest 的 schema 渲染）。"""
        pid = self._selected_pack_id()
        if not pid:
            return
        try:
            detail = tool_packs.pack_detail(self.ctx.settings, pid)
        except ValueError as exc:
            QMessageBox.warning(self, "打开详情失败", str(exc))
            return
        dlg = PackDetailDialog(self.ctx.settings, detail, self)
        dlg.exec()
        if dlg.changed:
            self.refresh_lists()

    def _config_pack(self):
        pid = self._selected_pack_id()
        if not pid:
            return
        pack_dir = Path(self.ctx.settings.root) / "tool_packs" / pid
        bundled_qw = (pack_dir / "bundled" / "qweather" / "manifest.json").exists()
        if pid == "qweather" or bundled_qw:
            # 和风天气要填项目ID/凭据ID/私钥路径，走它自己的专用对话框
            dlg = QWeatherConfigDialog(self.ctx.settings, self)
            if dlg.exec() == QDialog.Accepted:
                self.ctx.show_toast("和风天气配置已保存，重启机器人后生效")
            return
        self._open_pack_detail()

    def _reinstall_deps(self):
        item = self.local_list.currentItem()
        if not item:
            QMessageBox.information(self, "提示", "请先在列表中选择一个插件")
            return
        if self.ctx.tasks.has_active("install"):
            QMessageBox.information(self, "提示", "已有安装任务正在执行，请稍候")
            return
        plugin_dir = self.ctx.settings.plugins_dir / item.text()
        self.ctx.tasks.submit(
            "检查插件依赖", "install", CheckDepsTask,
            payload={"mode": "dir", "target": str(plugin_dir)},
            retryable=True, settings=self.ctx.settings,
        )

    def _restart_bot(self):
        if self.ctx.tasks.has_active("service"):
            QMessageBox.information(self, "提示", "已有服务任务正在执行，请稍候")
            return
        self.ctx.tasks.submit(
            "重启 NoneBot", "service", RestartBotTask,
            retryable=True, manager=self.ctx.manager,
        )

    # ------------------------------------------------------------ NoneBot 市场
    def _request_nonebot_market(self):
        """按搜索词过滤已加载列表；若尚未加载则先拉取。"""
        if self._nb_loaded:
            self._refresh_nonebot_list()
            return
        self._load_nonebot_market()

    def _load_nonebot_market(self):
        if not bool(getattr(self.ctx.settings, "developer_mode", False)):
            return
        self.nb_status.setText("正在连接 NoneBot 官方商店...")
        self.btn_nb_search.setEnabled(False)
        self.btn_nb_refresh.setEnabled(False)
        worker = Worker(self)
        worker.finished.connect(self._on_nonebot_market_loaded)

        def _run():
            return {"entries": nonebot_registry.fetch_registry()}

        threading.Thread(target=lambda: worker.run(_run), daemon=True).start()

    def _on_nonebot_market_loaded(self, res):
        self.btn_nb_search.setEnabled(True)
        self.btn_nb_refresh.setEnabled(True)
        err = str(res.get("error")) if isinstance(res, dict) else ""
        if isinstance(res, dict) and isinstance(res.get("entries"), list):
            self._nb_entries = res["entries"]
            self._nb_loaded = bool(self._nb_entries)
        else:
            self._nb_entries = []
            self._nb_loaded = True
        if not self._nb_entries:
            self.nb_status.setText(
                ("NoneBot 官方商店拉取失败: " + err) if err
                else "NoneBot 官方商店不可用或暂无内容，可点「刷新」重试")
            self.nb_list.clear()
            self._update_nonebot_buttons()
            return
        self._refresh_nonebot_list()

    def _refresh_nonebot_list(self):
        q = self.nb_search.text().strip()
        entries = nonebot_registry.search_plugins(self._nb_entries, q)
        self.nb_list.clear()
        for e in entries:
            ok, hint = nonebot_registry.adapter_compat(e)
            badge = "官方" if e.get("is_official") else "社区"
            item = QListWidgetItem(
                f"「{e.get('name')}」 v{e.get('version')}  [{badge}] "
                f"{e.get('project_link')}")
            item.setData(Qt.UserRole, e.get("module_name"))
            tip = str(e.get("desc") or "（无简介）")
            tip += f"\n\n作者: {e.get('author') or '未知'}"
            tip += f"\n主页: {e.get('homepage') or '未提供'}"
            tip += "\n兼容性: " + hint
            if not ok:
                tip += "\n⚠ 与当前协议不兼容，可能无法正常运行"
            if not e.get("valid"):
                tip += "\n⚠ 该插件未通过官方测试（valid=false），请谨慎安装"
            item.setToolTip(tip)
            if not ok or not e.get("valid"):
                item.setForeground(QColor("#94A3B8"))
            elif e.get("is_official"):
                item.setForeground(QColor("#34D399"))
            else:
                item.setForeground(QColor("#22D3EE"))
            self.nb_list.addItem(item)
        self.nb_status.setText(
            f"共 {len(entries)} 个结果"
            + ("（输入关键词后回车 / 点「搜索」可过滤）" if q else ""))
        self._update_nonebot_buttons()

    def _update_nonebot_buttons(self):
        self.btn_nb_install.setEnabled(self.nb_list.currentItem() is not None)

    def _install_nonebot_plugin(self):
        item = self.nb_list.currentItem()
        if item is None:
            QMessageBox.information(self, "提示", "请先选择一个 NoneBot 插件")
            return
        mod = str(item.data(Qt.UserRole) or "")
        e = next(
            (x for x in self._nb_entries if x.get("module_name") == mod), None)
        if not e:
            QMessageBox.information(self, "提示", "插件信息已失效，请点「刷新」")
            return
        link = str(e.get("project_link") or mod)
        _ok, hint = nonebot_registry.adapter_compat(e)
        lines = [
            f"「{e.get('name')}」 v{e.get('version')}",
            f"PyPI 包名: {link}",
            f"模块名: {mod}",
            "",
            "安装声明：",
            "· 该插件来自 NoneBot 官方/社区开源商店，未经星群校验。",
            "· 源码、可用性与许可协议（如 MIT / AGPL / GPL）由各自作者负责。",
            "· 星群默认不安装 GPL/AGPL 类插件；商业使用前请自行核对许可证。",
            "· 若协议不兼容或插件未通过官方测试，风险由用户自行承担。",
            "",
            "兼容性: " + hint,
            "安装后需重启 NoneBot 才生效。是否继续？",
        ]
        ret = QMessageBox.warning(
            self, "安装声明", "\n".join(lines),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ret != QMessageBox.Yes:
            return
        if self.ctx.tasks.has_active("install"):
            QMessageBox.information(self, "提示", "已有安装任务正在执行，请稍候")
            return
        self.ctx.tasks.submit(
            "安装插件", "install", InstallPluginTask,
            payload={"kind": "store", "target": link, "module_name": mod},
            retryable=True, settings=self.ctx.settings,
        )

    # ------------------------------------------------------------ 拖拽
    def dragEnterEvent(self, event):
        if not bool(getattr(self.ctx.settings, "developer_mode", False)):
            event.ignore()
            return
        urls = event.mimeData().urls()
        if any(u.isLocalFile() and u.toLocalFile().lower().endswith(".zip") for u in urls):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        if not bool(getattr(self.ctx.settings, "developer_mode", False)):
            event.ignore()
            return
        for u in event.mimeData().urls():
            if u.isLocalFile() and u.toLocalFile().lower().endswith(".zip"):
                self.zip_edit.setText(u.toLocalFile())
                break
        event.acceptProposedAction()

    # ------------------------------------------------------------ 刷新
    def refresh_lists(self):
        self._apply_mode()
        self.local_list.clear()
        for name in list_local_plugins(self.ctx.settings):
            if name == "ai":
                # 内置 AI 插件不可卸载/不可操作，只在 AI 大脑页关闭
                continue
            if name == "nonebot_adapter_ilink":
                # 内置微信 iLink 适配器（官方通道），不可操作，随机器人启动自动同步
                continue
            if name == "qbm_bridge_client":
                # 内置统一大脑桥客户端（微信 → dsh），不可卸载，随机器人启动自动同步
                continue
            self.local_list.addItem(name)
        self.store_list.clear()
        for name in list_store_plugins(self.ctx.settings):
            self.store_list.addItem(name)
        self.pack_list.clear()
        for p in tool_packs.installed(self.ctx.settings):
            frozen = "（冻结）" if p.get("frozen") else ""
            item = QListWidgetItem(
                f"{p.get('name') or p.get('id')} v{p.get('version') or '?'}{frozen}")
            item.setData(Qt.UserRole, p.get("id") or "")
            tool_names = "、".join(p.get("tools") or [])
            tip = (str(p.get("name") or "") + "\n")
            tip += ("工具：" + tool_names if tool_names else "行为/人设包")
            item.setToolTip(tip)
            self.pack_list.addItem(item)
        count = self.pack_list.count()
        self.pack_status.setText(
            f"共 {count} 个能力包" if count
            else "还没有装能力包；可在上面的插件商店里挑一个装上。")


class PackDetailDialog(QDialog):
    """能力包详情：介绍 / 功能 / 参数。

    参数来自 manifest 的 config.fields（没有则按 behavior 的键自动生成），
    按 type 渲染成开关 / 数字 / 下拉 / 文本框，保存后写 <能力包目录>/config.json，
    重启机器人生效。schema 与无头端控制台的参数表单一致。
    """

    def __init__(self, settings, detail: dict, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.detail = detail or {}
        self.changed = False
        self._widgets = {}      # key -> (field, 取值函数)
        self.setWindowTitle("能力包详情")
        self.setMinimumWidth(520)
        self._build_ui()

    def _build_ui(self):
        d = self.detail
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 24, 24, 24)
        lay.setSpacing(16)

        head = QHBoxLayout()
        name = QLabel(str(d.get("name") or d.get("id") or ""))
        name.setObjectName("cardTitle")
        head.addWidget(name)
        meta = " · ".join(x for x in (
            f"v{d.get('version')}" if d.get("version") else "",
            str(d.get("kind") or ""),
            str(d.get("tier") or ""),
        ) if x)
        m = QLabel(meta)
        m.setStyleSheet(f"color: {TEXT_3}; font-size: 12px;")
        head.addWidget(m)
        head.addStretch(1)
        lay.addLayout(head)

        desc = QLabel(str(d.get("description") or "（这个能力包没有写介绍）"))
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {TEXT_3}; font-size: 12px;")
        lay.addWidget(desc)

        feats = d.get("features") or []
        if feats:
            fl = QLabel("功能")
            fl.setObjectName("sectionTitle")
            lay.addWidget(fl)
            for f in feats[:12]:
                line = QLabel("· " + str(f.get("title")) +
                              (f"：{f.get('desc')}" if f.get("desc") else ""))
                line.setWordWrap(True)
                line.setStyleSheet(f"color: {TEXT_3}; font-size: 12px;")
                lay.addWidget(line)

        fields = d.get("fields") or []
        pl = QLabel("参数")
        pl.setObjectName("sectionTitle")
        lay.addWidget(pl)
        if not fields:
            none = QLabel("这个能力包没有可调参数，装上即用。")
            none.setWordWrap(True)
            none.setStyleSheet(f"color: {TEXT_3}; font-size: 12px;")
            lay.addWidget(none)
        else:
            form = QFormLayout()
            form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
            form.setHorizontalSpacing(12)
            form.setVerticalSpacing(8)
            values = d.get("values") or {}
            for field in fields:
                key = str(field.get("key") or "")
                if not key:
                    continue
                widget = self._make_widget(field, values.get(key, field.get("default")))
                label = str(field.get("label") or key)
                if field.get("unit"):
                    label += f"（{field['unit']}）"
                form.addRow(QLabel(label), widget)
                if field.get("help"):
                    hint = QLabel(str(field["help"]))
                    hint.setWordWrap(True)
                    hint.setStyleSheet(f"color: {TEXT_3}; font-size: 12px;")
                    form.addRow(QLabel(""), hint)
            lay.addLayout(form)

        row = QHBoxLayout()
        row.addStretch(1)
        btn_close = QPushButton("关闭")
        btn_close.setObjectName("ghost")
        btn_close.clicked.connect(self.reject)
        row.addWidget(btn_close)
        self.btn_save = QPushButton("保存参数")
        self.btn_save.setObjectName("primary")
        self.btn_save.setEnabled(bool(fields))
        self.btn_save.clicked.connect(self._save)
        row.addWidget(self.btn_save)
        lay.addLayout(row)

    def _make_widget(self, field: dict, value):
        """按 schema 的 type 造控件，并记住「怎么取值」。"""
        key = str(field.get("key"))
        ftype = str(field.get("type") or "text")
        if ftype == "bool":
            box = QCheckBox()
            box.setChecked(bool(value))
            self._widgets[key] = (field, box.isChecked)
            return box
        if ftype == "number":
            step = float(field.get("step") or 1)
            integer = step >= 1 and float(value or 0) == int(float(value or 0))
            box = QSpinBox() if integer else QDoubleSpinBox()
            box.setRange(int(field.get("min", -10 ** 9)) if integer else float(field.get("min", -1e9)),
                         int(field.get("max", 10 ** 9)) if integer else float(field.get("max", 1e9)))
            box.setSingleStep(int(step) if integer else step)
            try:
                box.setValue(int(float(value)) if integer else float(value))
            except (TypeError, ValueError):
                pass
            self._widgets[key] = (field, box.value)
            return box
        if ftype in ("enum", "select"):
            combo = QComboBox()
            for opt in field.get("options") or []:
                if isinstance(opt, dict):
                    combo.addItem(str(opt.get("label") or opt.get("value")), opt.get("value"))
                else:
                    combo.addItem(str(opt), opt)
            idx = combo.findData(value)
            combo.setCurrentIndex(idx if idx >= 0 else 0)
            self._widgets[key] = (field, combo.currentData)
            return combo
        edit = QLineEdit(str(value if value is not None else ""))
        self._widgets[key] = (field, edit.text)
        return edit

    def _save(self):
        patch = {key: getter() for key, (_f, getter) in self._widgets.items()}
        try:
            res = tool_packs.save_pack_config(self.settings, self.detail.get("id"), patch)
        except (ValueError, RuntimeError, OSError) as exc:
            QMessageBox.warning(self, "保存失败", str(exc))
            return
        self.changed = bool(res.get("changed"))
        self.accept()



class QWeatherConfigDialog(QDialog):
    """和风天气工具包配置：自动生成 Ed25519 密钥对 + 展示公钥 + 指引控制台。"""

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("和风天气 · 配置")
        self.resize(640, 560)
        self._key_path = str(Path(settings.root) / "qweather_ed25519_private.pem")
        cfg = tool_packs.load_qweather_config(settings)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 24, 24, 24)
        lay.setSpacing(12)
        tip = QLabel("步骤：① 生成密钥对 → ② 把公钥粘贴到和风控制台创建 JWT 凭据 → "
                     "③ 填项目ID/凭据ID → ④ 保存并重启机器人。")
        tip.setWordWrap(True)
        tip.setStyleSheet(f"color: {TEXT_3}; font-size: 12px;")
        lay.addWidget(tip)

        r0 = QHBoxLayout()
        r0.addWidget(QLabel("API Host"))
        self.edit_host = QLineEdit(str(cfg.get("api_host") or ""))
        self.edit_host.setPlaceholderText("控制台-设置里的专属 API Host，如 xxx.qweatherapi.com")
        r0.addWidget(self.edit_host, 1)
        lay.addLayout(r0)

        r1 = QHBoxLayout()
        r1.addWidget(QLabel("项目ID"))
        self.edit_project = QLineEdit(str(cfg.get("project_id") or "3K85YMFKU3"))
        r1.addWidget(self.edit_project, 1)
        lay.addLayout(r1)

        r2 = QHBoxLayout()
        r2.addWidget(QLabel("凭据ID"))
        self.edit_cred = QLineEdit(str(cfg.get("credential_id") or ""))
        self.edit_cred.setPlaceholderText("创建 JWT 凭据后页面显示的 ID")
        r2.addWidget(self.edit_cred, 1)
        lay.addLayout(r2)

        key_row = QHBoxLayout()
        self.btn_gen = QPushButton("生成密钥对")
        self.btn_gen.setObjectName("primary")
        self.btn_gen.clicked.connect(self._gen_keypair)
        self.lbl_key_status = QLabel("未生成")
        self.lbl_key_status.setStyleSheet(f"color: {TEXT_3}; font-size: 12px;")
        key_row.addWidget(self.btn_gen)
        key_row.addWidget(self.lbl_key_status, 1)
        lay.addLayout(key_row)

        self.pub_box = QPlainTextEdit()
        self.pub_box.setReadOnly(True)
        self.pub_box.setPlaceholderText("生成的公钥会显示在这里，整段复制到控制台…")
        self.pub_box.setMaximumHeight(120)
        lay.addWidget(self.pub_box)

        steps = QLabel(
            "控制台操作：\n"
            "1. 控制台 → 设置 → 复制「API Host」填到最上面（如 xxx.qweatherapi.com）\n"
            "2. 控制台 → 项目管理 → 点进你的项目，记下项目ID\n"
            "3. 添加凭据 → 身份认证方式选「JSON Web Token」\n"
            "4. 把上面公钥整段（含 BEGIN/END 行）粘贴进去 → 保存\n"
            "5. 保存后显示的「凭据 ID」填到凭据ID框\n"
            "6. 点「保存配置」，然后重启机器人")
        steps.setWordWrap(True)
        steps.setStyleSheet(f"color: {TEXT_3}; font-size: 12px;")
        lay.addWidget(steps)

        btn_row = QHBoxLayout()
        btn_open = QPushButton("打开官方文档")
        btn_open.setObjectName("ghost")
        btn_open.clicked.connect(
            lambda: QDesktopServices.openUrl(
                QUrl("https://dev.qweather.com/docs/configuration/authentication/")))
        btn_save = QPushButton("保存配置")
        btn_save.setObjectName("primary")
        btn_save.clicked.connect(self._save)
        btn_row.addWidget(btn_open)
        btn_row.addStretch(1)
        btn_row.addWidget(btn_save)
        lay.addLayout(btn_row)

    def _gen_keypair(self):
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
            from cryptography.hazmat.primitives import serialization
        except Exception:  # noqa: BLE001
            QMessageBox.warning(
                self, "缺少依赖",
                "当前程序缺 cryptography 库，无法生成密钥对。\n"
                "请更新程序后重试（开发预览请先安装 requirements.txt）。")
            return
        priv = Ed25519PrivateKey.generate()
        try:
            Path(self._key_path).parent.mkdir(parents=True, exist_ok=True)
            with open(self._key_path, "wb") as f:
                f.write(priv.private_bytes(
                    serialization.Encoding.PEM,
                    serialization.PrivateFormat.PKCS8,
                    serialization.NoEncryption()))
            try:
                os.chmod(self._key_path, 0o600)
            except OSError:
                pass
        except OSError as e:  # noqa: BLE001
            QMessageBox.warning(self, "保存失败", "私钥写入失败：" + str(e))
            return
        pub_pem = priv.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode()
        self.pub_box.setPlainText(pub_pem)
        self.lbl_key_status.setText("已生成，私钥保存在：" + self._key_path)

    def _save(self):
        api_host = self.edit_host.text().strip()
        project_id = self.edit_project.text().strip()
        credential_id = self.edit_cred.text().strip()
        key_path = self._key_path if os.path.exists(self._key_path) else ""
        try:
            tool_packs.save_qweather_config(
                self.settings, project_id, credential_id, key_path, api_host)
        except OSError as e:  # noqa: BLE001
            QMessageBox.warning(self, "保存失败", str(e))
            return
        self.accept()
