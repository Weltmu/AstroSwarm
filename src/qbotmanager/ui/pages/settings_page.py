# -*- coding: utf-8 -*-
"""设置：环境信息（只读）+ 外观与动态背景（实时预览 + 保存持久化）。

重要：refresh_status 只更新只读信息，绝不重置外观控件，
否则主窗口的定时刷新会把用户正在调整的路径/滑条“复原”。
外观区任何改动都立即应用到内存设置并即时生效，点保存才写盘。
"""
import os
import threading
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QColorDialog, QComboBox, QFileDialog, QFrame,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
    QScrollArea, QSlider, QTabWidget, QVBoxLayout, QWidget,
)

from ...constants import APP_VERSION
from ...core import autostart as autostart_mod
from ...core import license as lic_mod
from ...core import migrate as migrate_mod
from ...core import update_check
from ...tasks.workers import UninstallTask
from .. import theme as theme_mod
from ..theme import TEXT_3, THEMES, UI_THEMES
from ..widgets import GlassPanel, ToggleSwitch
from .common import PageContext, Worker, make_row


class SettingsPage(QWidget):
    def __init__(self, ctx: PageContext):
        super().__init__()
        self.ctx = ctx
        self._uninstall_tid = None
        self._config_restored = False
        self._build_ui()
        self.load_settings()
        self._connect_signals()
        self.ctx.tasks.finished.connect(self._on_task_finished)

    # ------------------------------------------------------------ UI
    # 间距刻度：组内 8 / 12，组间 24（卡内 12 ≤ 卡间 24，组外 ≥ 组内 1.5 倍）
    _INFO_KEYS = (
        ("root", "安装根目录"),
        ("nonebot_port", "NoneBot 端口"),
        ("python_source", "Python 来源"),
        ("python_exe", "Python 路径"),
        ("pip_index", "pip 源"),
        ("account_qq", "登录 QQ"),
        ("wechat_status", "微信 ClawBot"),
        ("app_version", "当前版本"),
        ("latest_version", "最新版本"),
        ("update_time", "上次检查"),
        ("license_status", "授权状态"),
    )
    _INFO_LABELS = dict(_INFO_KEYS)

    def _build_ui(self):
        self.info_labels = {}
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---- 页头：三个页签共用（标题 / 说明 / BETA 提示）----
        head = QVBoxLayout()
        head.setContentsMargins(24, 24, 24, 16)
        head.setSpacing(8)
        title = QLabel("设置")
        title.setObjectName("pageTitle")
        sub = QLabel("外观、账号与高级选项；外观改动实时预览，点「保存设置」写入配置")
        sub.setObjectName("pageSub")
        head.addWidget(title)
        head.addWidget(sub)
        self.beta_notice = QLabel(
            "⚠ 当前为 BETA 测试版，未经充分测试，可能存在不兼容或 Bug。"
            "如遇问题，请等待后续更新。")
        self.beta_notice.setWordWrap(True)
        self.beta_notice.setStyleSheet(
            "font-size: 12px; color: #F59E0B; background: rgba(245,158,11,0.12);"
            "border: 1px solid rgba(245,158,11,0.35); border-radius: 8px;"
            "padding: 8px 10px;")
        head.addWidget(self.beta_notice)
        root.addLayout(head)

        # ---- 三页签：外观（默认）/ 账号 / 高级 ----
        self.tabs = QTabWidget()
        self.tabs.setObjectName("settingsTabs")
        self.tabs.setDocumentMode(True)
        self.tabs.setUsesScrollButtons(False)
        self.tabs.tabBar().setElideMode(Qt.ElideNone)
        self.tabs.tabBar().setExpanding(False)
        self.tabs.addTab(self._build_appearance_tab(), "外观")
        self.tabs.addTab(self._build_account_tab(), "账号")
        self.tabs.addTab(self._build_advanced_tab(), "高级")
        self.tabs.setCurrentIndex(0)     # 默认停在「外观」
        self._style_tabs(force=True)
        tabs_wrap = QVBoxLayout()
        tabs_wrap.setContentsMargins(8, 0, 8, 0)
        tabs_wrap.setSpacing(0)
        tabs_wrap.addWidget(self.tabs)
        root.addLayout(tabs_wrap, 1)

        # ---- 页脚主操作：三页签共用一个「保存设置」（一屏只有一个实心主按钮）----
        foot = QHBoxLayout()
        foot.setContentsMargins(24, 16, 24, 16)
        foot.setSpacing(8)
        self.btn_save = QPushButton("保存设置")
        self.btn_save.setObjectName("primary")
        self.btn_save.setMinimumHeight(32)
        self.btn_save.clicked.connect(self._save)
        foot.addWidget(self.btn_save)
        save_hint = QLabel("改动即时预览；这里保存全部页签的设置")
        save_hint.setStyleSheet(f"color: {TEXT_3}; font-size: 12px;")
        foot.addWidget(save_hint)
        foot.addStretch(1)
        root.addLayout(foot)

    # ------------------------------------------------------------ 版式构件
    def _make_tab_area(self, build):
        """每个页签自带滚动区：页签栏固定不动，内容各自滚动。"""
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.NoFrame)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        content = QWidget()
        lay = QVBoxLayout(content)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(24)
        build(lay)
        lay.addStretch(1)
        area.setWidget(content)
        return area

    def _card(self, title_text, tip_text="", strong=False, title_color=""):
        """标准分区卡：内边距 16、卡内行距 12、12px 灰色说明。"""
        panel = GlassPanel(strong=strong)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(12)
        title = QLabel(title_text)
        title.setObjectName("sectionTitle")
        if title_color:
            title.setStyleSheet(f"color: {title_color};")
        lay.addWidget(title)
        if tip_text:
            tip = QLabel(tip_text)
            tip.setWordWrap(True)
            tip.setStyleSheet(f"color: {TEXT_3}; font-size: 12px;")
            lay.addWidget(tip)
        return panel, lay

    def _labeled_row(self, label_text):
        """滑条/下拉用的「灰色小标签 + 控件」行，行内间距 8。"""
        row = QHBoxLayout()
        row.setSpacing(8)
        lbl = QLabel(label_text)
        lbl.setStyleSheet(f"color: {TEXT_3}; font-size: 12px;")
        row.addWidget(lbl)
        return row, lbl

    def _add_info_rows(self, layout, keys):
        for key in keys:
            val = QLabel("—")
            val.setWordWrap(True)
            val.setStyleSheet("font-size: 12px;")
            self.info_labels[key] = val
            layout.addLayout(make_row(self._INFO_LABELS[key], val))

    # ------------------------------------------------------------ 页签 1：外观
    def _build_appearance_tab(self):
        area = self._make_tab_area(self._fill_appearance_tab)
        self.scroll = area   # 兼容旧引用：过去这里是整页滚动区，现在归属「外观」页签
        return area

    def _fill_appearance_tab(self, lay):
        # ---- 动态背景 ----
        bg, bl = self._card(
            "动态背景",
            "背景只是氛围层，不影响任何后台任务；改动实时生效，点「保存设置」写入配置。",
            strong=True)
        lay.addWidget(bg)

        self.chk_enabled = QCheckBox("启用背景（图片/视频）")
        bl.addWidget(self.chk_enabled)

        path_row = QHBoxLayout()
        path_row.setSpacing(8)
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("选择视频或图片背景（留空 = 默认）")
        btn_browse = QPushButton("选择文件 ...")
        btn_browse.setMinimumHeight(32)
        btn_browse.setToolTip("支持 mp4/mkv/mov 视频 与 png/jpg/webp 等图片")
        btn_browse.clicked.connect(self._browse_bg)
        btn_default = QPushButton("清除")
        btn_default.setMinimumHeight(32)
        btn_default.clicked.connect(self._clear_bg)
        path_row.addWidget(self.path_edit, 1)
        path_row.addWidget(btn_browse)
        path_row.addWidget(btn_default)
        bl.addLayout(path_row)

        play_row = QHBoxLayout()
        play_row.setSpacing(16)
        self.chk_autoplay = QCheckBox("自动播放")
        self.chk_loop = QCheckBox("循环播放")
        play_row.addWidget(self.chk_autoplay)
        play_row.addWidget(self.chk_loop)
        play_row.addStretch(1)
        bl.addLayout(play_row)

        mask_row, _ = self._labeled_row("遮罩强度")
        self.mask_slider = QSlider(Qt.Horizontal)
        self.mask_slider.setRange(30, 95)
        self.mask_value = QLabel("0.68")
        self.mask_value.setStyleSheet("font-size: 12px; color: #F2F5FA; min-width: 34px;")
        mask_row.addWidget(self.mask_slider, 1)
        mask_row.addWidget(self.mask_value)
        bl.addLayout(mask_row)

        bright_row, _ = self._labeled_row("视频亮度")
        self.bright_slider = QSlider(Qt.Horizontal)
        self.bright_slider.setRange(-100, 100)
        self.bright_slider.setValue(0)
        self.bright_value = QLabel("0")
        self.bright_value.setStyleSheet("font-size: 12px; color: #F2F5FA; min-width: 34px;")
        bright_row.addWidget(self.bright_slider, 1)
        bright_row.addWidget(self.bright_value)
        bl.addLayout(bright_row)

        # ---- 界面主题 ----
        ui, ul = self._card(
            "界面主题",
            "每个 UI 主题拥有独立的布局、导航、配色与质感；改动即时生效。",
            strong=True)
        lay.addWidget(ui)

        theme_row, _ = self._labeled_row("UI 主题")
        self.theme_combo = QComboBox()
        for key, cfg in UI_THEMES.items():
            self.theme_combo.addItem(cfg["name"], key)
        self.theme_combo.setToolTip("每个 UI 主题拥有独立的布局、导航、配色与质感")
        theme_row.addWidget(self.theme_combo, 1)
        ul.addLayout(theme_row)

        self.accent_box = QWidget()
        accent_row, _ = self._labeled_row("强调色")
        accent_row.setContentsMargins(0, 0, 0, 0)
        self.accent_combo = QComboBox()
        for key, cfg in THEMES.items():
            self.accent_combo.addItem(cfg["name"], key)
        accent_row.addWidget(self.accent_combo, 1)
        self.accent_box.setLayout(accent_row)
        ul.addWidget(self.accent_box)

        self.glass_box = QWidget()
        glass_row, _ = self._labeled_row("UI 框质感")
        glass_row.setContentsMargins(0, 0, 0, 0)
        self.glass_combo = QComboBox()
        self.glass_combo.addItem("默认（原样）", "default")
        self.glass_combo.addItem("液态玻璃", "liquid")
        self.glass_combo.addItem("颗粒磨砂", "frosted")
        self.glass_combo.setToolTip("液态玻璃：通透渐变 + 高光描边；颗粒磨砂：半透明磨砂质感")
        glass_row.addWidget(self.glass_combo, 1)
        self.glass_box.setLayout(glass_row)
        ul.addWidget(self.glass_box)

        self.color_box = QWidget()
        color_row, _ = self._labeled_row("UI 框颜色")
        color_row.setContentsMargins(0, 0, 0, 0)
        self.btn_color = QPushButton("#FFFFFF")
        self.btn_color.setCursor(Qt.PointingHandCursor)
        self.btn_color.setFixedHeight(30)
        self.btn_color.setToolTip("瑞士极简的卡片/面板底色，默认白色；建议选浅色保证文字可读")
        self.btn_color.clicked.connect(self._pick_color)
        color_row.addWidget(self.btn_color, 1)
        self.color_box.setLayout(color_row)
        ul.addWidget(self.color_box)

        self.opacity_box = QWidget()
        op_row, _ = self._labeled_row("UI 不透明度")
        op_row.setContentsMargins(0, 0, 0, 0)
        self.opacity_slider = QSlider(Qt.Horizontal)
        self.opacity_slider.setRange(10, 95)
        self.opacity_slider.setValue(70)
        self.opacity_value = QLabel("70%")
        self.opacity_value.setStyleSheet("font-size: 12px; color: #F2F5FA; min-width: 34px;")
        op_row.addWidget(self.opacity_slider, 1)
        op_row.addWidget(self.opacity_value)
        self.opacity_box.setLayout(op_row)
        ul.addWidget(self.opacity_box)

        self.chk_animations = QCheckBox("减少界面动效")
        self.chk_animations.setToolTip("关闭进度条平滑动画等界面动效，老旧电脑更流畅")
        ul.addWidget(self.chk_animations)

    # ------------------------------------------------------------ 页签 2：账号
    def _build_account_tab(self):
        return self._make_tab_area(self._fill_account_tab)

    def _fill_account_tab(self, lay):
        # ---- 星群账号 ----
        acct, al = self._card(
            "星群账号",
            "授权随星群账号同步（邮箱登录，无需激活码）。",
            strong=True)
        lay.addWidget(acct)

        self.acct_status = QLabel("未登录")
        self.acct_status.setWordWrap(True)
        self.acct_status.setStyleSheet("font-size: 12px;")
        al.addWidget(self.acct_status)

        acct_btns = QHBoxLayout()
        acct_btns.setSpacing(8)
        self.btn_account = QPushButton("打开星群账号窗口")
        self.btn_account.setMinimumHeight(32)
        self.btn_account.clicked.connect(self._open_account_window)
        acct_btns.addWidget(self.btn_account)
        acct_btns.addStretch(1)
        al.addLayout(acct_btns)

        # ---- 账号与授权（环境信息里与账号/授权有关的行）----
        info, il = self._card("账号与授权")
        lay.addWidget(info)
        self._add_info_rows(il, ("account_qq", "wechat_status", "license_status"))

    # ------------------------------------------------------------ 页签 3：高级
    def _build_advanced_tab(self):
        return self._make_tab_area(self._fill_advanced_tab)

    def _fill_advanced_tab(self, lay):
        swiss = theme_mod.UI_STYLE == "swiss"

        # ---- 配置抢救提示（仅当配置被抢救过时出现）----
        self.rescue_box = QFrame()
        self.rescue_box.setObjectName("rescueBox")
        warn_fg = "#8A5300" if swiss else "#F59E0B"
        warn_bg = "rgba(245,158,11,0.10)" if swiss else "rgba(245,158,11,0.12)"
        warn_border = "rgba(245,158,11,0.55)" if swiss else "rgba(245,158,11,0.35)"
        self.rescue_box.setStyleSheet(
            f"QFrame#rescueBox {{ background: {warn_bg}; border: 1px solid {warn_border};"
            " border-radius: 8px; }")
        rl = QVBoxLayout(self.rescue_box)
        rl.setContentsMargins(12, 12, 12, 12)
        rl.setSpacing(8)
        self.rescue_text = QLabel("")
        self.rescue_text.setWordWrap(True)
        self.rescue_text.setStyleSheet(
            f"background: transparent; border: none; color: {warn_fg}; font-size: 12px;")
        rl.addWidget(self.rescue_text)
        rescue_row = QHBoxLayout()
        rescue_row.setSpacing(8)
        self.btn_restore_config = QPushButton("回滚到上一份配置")
        self.btn_restore_config.setMinimumHeight(32)
        self.btn_restore_config.setToolTip(
            "把上一份能正常解析的配置（settings.json.bak）恢复回来，重启程序后生效")
        self.btn_restore_config.clicked.connect(self._restore_last_good)
        rescue_row.addWidget(self.btn_restore_config)
        rescue_row.addStretch(1)
        rl.addLayout(rescue_row)
        self.rescue_box.setVisible(False)
        lay.addWidget(self.rescue_box)

        # ---- 环境信息（只读；账号/授权相关的行在「账号」页签）----
        env, el = self._card("环境信息", "安装位置与运行环境，只读；账号与授权信息在「账号」页签。")
        lay.addWidget(env)
        self._add_info_rows(el, ("root", "nonebot_port", "python_source", "python_exe", "pip_index"))

        # ---- 版本与更新 ----
        ver, vl = self._card("版本与更新")
        lay.addWidget(ver)
        self._add_info_rows(vl, ("app_version", "latest_version", "update_time"))
        upd_row = QHBoxLayout()
        upd_row.setSpacing(8)
        btn_update = QPushButton("检查更新")
        btn_update.setObjectName("ghost")
        btn_update.setMinimumHeight(32)
        btn_update.setMinimumWidth(110)
        btn_update.clicked.connect(self._check_update)
        upd_row.addWidget(btn_update)
        upd_row.addStretch(1)
        vl.addLayout(upd_row)

        # ---- AI 插件（内置，可停用；接口配置在「AI 大脑」页）----
        ai, al = self._card(
            "AI 插件",
            "内置 AI 插件已随程序自动安装到机器人，不可卸载；关闭后机器人启动时不会加载 AI 功能。"
            "接口配置与平台开关请到「AI 大脑」页设置。",
            strong=True)
        lay.addWidget(ai)
        self.chk_ai_enabled = QCheckBox("启用 AI 插件")
        self.chk_ai_enabled.setToolTip("关闭后启动机器人会注入 AI_DISABLED=1，内置 AI 插件不注册任何功能")
        al.addWidget(self.chk_ai_enabled)

        # ---- 启动行为 ----
        boot, bl = self._card(
            "启动行为",
            "开机自启动写入当前用户注册表"
            "（HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run）。",
            strong=True)
        lay.addWidget(boot)
        self.chk_auto_start_services = QCheckBox("启动程序时自动启动全部服务")
        self.chk_auto_start_services.setToolTip("打开程序后自动提交「启动全部」，无需手动点击")
        self.chk_autostart_boot = QCheckBox("开机自动启动 AstroSwarm")
        self.chk_autostart_boot.setToolTip("登录 Windows 时自动启动本程序（当前用户）")
        self.chk_developer_mode = QCheckBox("开发者模式（恢复第三方插件安装，后果自负）")
        self.chk_developer_mode.setToolTip(
            "开启后插件页恢复 PyPI / zip 第三方插件安装；兼容性、安全性、"
            "平台协议合规由用户自行承担")
        self.chk_beginner_mode = ToggleSwitch("小白模式（只显示常用功能）")
        self.chk_beginner_mode.setToolTip(
            "默认开启：侧边栏只保留 首页 / 微信 / QQ / AI 大脑 / 设置，"
            "飞书、纸飞机、消息中心、插件、日志、依赖自动隐藏")
        bl.addWidget(self.chk_auto_start_services)
        bl.addWidget(self.chk_autostart_boot)
        bl.addWidget(self.chk_developer_mode)
        bl.addWidget(self.chk_beginner_mode)

        # ---- 维护 ----
        mnt, ml = self._card(
            "维护",
            "打开配置文件或安装目录；也可关联旧版本安装目录，配置、插件与登录信息原地保留。",
            strong=True)
        lay.addWidget(mnt)
        mnt_row1 = QHBoxLayout()
        mnt_row1.setSpacing(8)
        btn_settings = QPushButton("打开 settings.json")
        btn_settings.setObjectName("ghost")
        btn_settings.setMinimumHeight(32)
        btn_settings.setMinimumWidth(120)
        btn_settings.clicked.connect(lambda: os.startfile(str(self.ctx.settings.settings_file)))
        btn_root = QPushButton("打开安装目录")
        btn_root.setObjectName("ghost")
        btn_root.setMinimumHeight(32)
        btn_root.setMinimumWidth(120)
        btn_root.clicked.connect(lambda: os.startfile(str(self.ctx.settings.root)))
        mnt_row1.addWidget(btn_settings)
        mnt_row1.addWidget(btn_root)
        mnt_row1.addStretch(1)
        ml.addLayout(mnt_row1)

        mnt_row2 = QHBoxLayout()
        mnt_row2.setSpacing(8)
        btn_import = QPushButton("导入旧版本")
        btn_import.setObjectName("ghost")
        btn_import.setMinimumHeight(32)
        btn_import.setMinimumWidth(130)
        btn_import.setToolTip("选择旧版本安装目录并沿用：配置、插件、QQ/微信登录信息原地保留，无需重新部署")
        btn_import.clicked.connect(self._import_old)
        mnt_row2.addWidget(btn_import)
        mnt_row2.addStretch(1)
        ml.addLayout(mnt_row2)

        # ---- 危险操作（页签底部单独一行，远离主按钮）----
        dgr, dl = self._card(
            "危险操作",
            "卸载会停止全部服务并删除整个安装目录（bot / python / 日志等）；"
            "账号登录与授权保留，exe 文件需手动删除。",
            strong=True,
            title_color="#B00020" if swiss else theme_mod.DANGER)
        lay.addWidget(dgr)
        dgr_row = QHBoxLayout()
        dgr_row.setSpacing(8)
        btn_uninstall = QPushButton("卸载 AstroSwarm")
        btn_uninstall.setObjectName("danger")
        btn_uninstall.setMinimumHeight(32)
        btn_uninstall.setMinimumWidth(130)
        btn_uninstall.setToolTip("停止全部服务并删除整个安装目录（bot / python 等），账号登录与授权保留；exe 文件需手动删除")
        btn_uninstall.clicked.connect(self._uninstall_app)
        dgr_row.addWidget(btn_uninstall)
        dgr_row.addStretch(1)
        dl.addLayout(dgr_row)

    # ------------------------------------------------------------ 页签外观
    def _tab_qss(self) -> str:
        """页签样式：跟随当前 UI 主题（瑞士浅色 / 玻璃·终端深色）与皮肤强调色。"""
        accent = theme_mod.THEMES.get(
            self.ctx.settings.accent or "default",
            theme_mod.THEMES["default"])["ACCENT"]
        if theme_mod.UI_STYLE == "swiss":
            idle, hover, active = "#6B6B67", "#111111", "#111111"
        else:
            idle, hover, active = theme_mod.TEXT_3, theme_mod.TEXT_2, theme_mod.TEXT
        return f"""
QTabWidget::pane {{ border: none; background: transparent; }}
QTabBar {{ background: transparent; }}
QTabBar::tab {{
    background: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    color: {idle};
    font-size: 14px;
    font-weight: 600;
    padding: 8px 16px;
    margin: 0 8px 0 0;
}}
QTabBar::tab:hover {{ color: {hover}; }}
QTabBar::tab:selected {{ color: {active}; border-bottom: 2px solid {accent}; }}
"""

    def _style_tabs(self, force: bool = False):
        """按当前 UI 主题/皮肤重算页签样式。

        页面构建时主题可能还没套用（apply_skin 晚于建页），所以这里用「生成的 QSS
        字符串」做缓存，任何一次刷新发现样式变了都会重刷，避免浅色主题下选中页签看不清。
        """
        qss = self._tab_qss()
        if not force and qss == getattr(self, "_tab_qss_applied", None):
            return
        self._tab_qss_applied = qss
        self.tabs.setStyleSheet(qss)

    def showEvent(self, event):
        super().showEvent(event)
        self._style_tabs()      # 切到本页时按当前主题校正页签配色

    def _connect_signals(self):
        self._apply_timer = QTimer(self)
        self._apply_timer.setSingleShot(True)
        self._apply_timer.setInterval(80)
        self._apply_timer.timeout.connect(self._apply_live)
        self.chk_enabled.toggled.connect(self._apply_live)
        self.path_edit.editingFinished.connect(self._apply_live)
        self.chk_autoplay.toggled.connect(self._apply_live)
        self.chk_loop.toggled.connect(self._apply_live)
        self.mask_slider.valueChanged.connect(self._on_mask_changed)
        self.opacity_slider.valueChanged.connect(self._on_opacity_changed)
        self.bright_slider.valueChanged.connect(self._on_brightness_changed)
        self.chk_animations.toggled.connect(self._apply_live)
        self.theme_combo.currentIndexChanged.connect(self._apply_live)
        self.accent_combo.currentIndexChanged.connect(self._apply_live)
        self.glass_combo.currentIndexChanged.connect(self._apply_live)
        self.chk_ai_enabled.toggled.connect(self._apply_live)
        self.chk_auto_start_services.toggled.connect(self._apply_live)
        self.chk_autostart_boot.toggled.connect(self._on_autostart_toggled)
        self.chk_developer_mode.toggled.connect(self._on_developer_toggled)
        self.chk_beginner_mode.toggled.connect(self._on_beginner_toggled)

    # ------------------------------------------------------------ 状态
    def load_settings(self):
        s = self.ctx.settings
        src_map = {"system": "系统 Python（独立虚拟环境）", "venv": "独立虚拟环境", "embedded": "内置 Python"}
        self.info_labels["root"].setText(str(s.root))
        self.info_labels["nonebot_port"].setText(str(s.nonebot_port))
        self.info_labels["python_source"].setText(src_map.get(s.python_source, "自动探测"))
        self.info_labels["python_exe"].setText(str(s.python_exe))
        self.info_labels["pip_index"].setText(s.pip_index or "官方 PyPI")
        self.info_labels["account_qq"].setText(s.account_qq or "未登录")
        self._fill_license_status()
        self._refresh_account_status()

        self.chk_enabled.setChecked(s.bg_video_enabled or s.bg_image_enabled)
        self.path_edit.setText(s.bg_video_path or s.bg_image_path or "")
        self.chk_autoplay.setChecked(s.bg_video_autoplay)
        self.chk_loop.setChecked(s.bg_video_loop)
        self.mask_slider.setValue(int(round(max(0.30, min(0.95, s.bg_mask_strength)) * 100)))
        self.opacity_slider.setValue(max(10, min(95, s.ui_opacity)))
        self.bright_slider.setValue(max(-100, min(100, s.bg_brightness)))
        self.chk_animations.setChecked(not s.animations_enabled)
        idx = self.theme_combo.findData(s.theme)
        self.theme_combo.setCurrentIndex(idx if idx >= 0 else 0)
        idx = self.accent_combo.findData(s.accent)
        self.accent_combo.setCurrentIndex(idx if idx >= 0 else 0)
        idx = self.glass_combo.findData(s.glass_effect)
        self.glass_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._set_color_button(s.ui_color or "#FFFFFF")
        self._update_ui_rows()
        # ---- AI 插件 ----
        self.chk_ai_enabled.setChecked(s.ai_enabled)
        self.chk_auto_start_services.setChecked(s.auto_start_services)
        # 注册表是真相：安装包（Inno 附加任务）也会写同一个值，避免界面与实际不一致
        try:
            on_boot = autostart_mod.is_enabled()
        except Exception:  # noqa: BLE001
            on_boot = False
        self.chk_autostart_boot.setChecked(bool(on_boot or s.auto_launch_on_boot))
        self.chk_developer_mode.setChecked(s.developer_mode)
        self.chk_beginner_mode.setChecked(s.beginner_mode)
        self._refresh_rescue_banner()

    def refresh_status(self):
        """定时刷新：只更新只读信息，不碰外观控件（防止用户操作被重置）。"""
        s = self.ctx.settings
        src_map = {"system": "系统 Python（独立虚拟环境）", "venv": "独立虚拟环境", "embedded": "内置 Python"}
        self.info_labels["nonebot_port"].setText(str(s.nonebot_port))
        self.info_labels["python_source"].setText(src_map.get(s.python_source, "自动探测"))
        self.info_labels["python_exe"].setText(str(s.python_exe))
        self.info_labels["account_qq"].setText(s.account_qq or "未登录")
        st = update_check.read_state()
        self.info_labels["app_version"].setText(APP_VERSION)
        self.info_labels["latest_version"].setText(str(st.get("latest") or "—"))
        t = st.get("checked_at") or 0
        self.info_labels["update_time"].setText(
            time.strftime("%Y-%m-%d %H:%M", time.localtime(t)) if t else "从未")
        wx = self.ctx.manager.wechat_status()
        if not wx["installed"]:
            self.info_labels["wechat_status"].setText("未安装适配器")
        elif wx.get("connected"):
            self.info_labels["wechat_status"].setText(f"已连接（{wx['bot_id']}）")
        elif wx["logged_in"]:
            self.info_labels["wechat_status"].setText(f"未连接（{wx['bot_id']}）")
        else:
            self.info_labels["wechat_status"].setText("未登录")
        self._fill_license_status()
        self._style_tabs()      # 主题变了（含启动时套皮肤）就校正一次页签配色

    def _fill_license_status(self):
        try:
            lic = lic_mod.load_license() or {}
            plan = str(lic.get("plan") or "none").lower()
            plan_exp = float(lic.get("plan_expires_at") or 0)
        except Exception:  # noqa: BLE001
            plan, plan_exp = "none", 0
        if plan == "permanent" or (plan == "monthly" and plan_exp > time.time()):
            label = "付费版 · 全功能"
        elif plan == "monthly":
            label = "付费已过期 · 免费版（仅 QQ）"
        else:
            label = "免费版（仅 QQ 通道）"
        self.info_labels["license_status"].setText(label)
        self.info_labels["license_status"].setToolTip(
            "授权随星群账号同步（邮箱登录，无需激活码）")

    # ------------------------------------------------------------ 星群账号
    def _refresh_account_status(self):
        from ...core import account
        acc = account.load_account()
        self.btn_account.setText(
            "星群账号（已登录：%s）" % acc.get("email") if acc else "打开星群账号窗口")
        self.acct_status.setText(
            f"已登录：{acc.get('email')}，点上方按钮可退出/切换账号"
            if acc else "未登录，点上方按钮打开账号窗口")

    def _open_account_window(self):
        """打开主窗口托管的独立账号窗口（默认贴屏幕左上角）。"""
        self.ctx.open_account()

    # ------------------------------------------------------------ 配置抢救
    def _refresh_rescue_banner(self):
        """配置被抢救过（config_error 非空）时，在「高级」页签顶部亮黄条。"""
        msg = str(getattr(self.ctx.settings, "config_error", "") or "").strip()
        box = getattr(self, "rescue_box", None)
        if box is None:
            return
        if msg and getattr(self, "_config_restored", False):
            self.rescue_text.setText("✅ 已回滚到上一份配置，重启程序生效。")
            self.btn_restore_config.setVisible(False)
        elif msg:
            self.rescue_text.setText(
                "⚠ 配置文件曾被抢救：%s\n当前用的是抢救后的配置，建议回滚到上一份能正常解析的配置。" % msg)
            self.btn_restore_config.setVisible(True)
        box.setVisible(bool(msg))

    def _restore_last_good(self):
        """回滚到上一份好配置（settings.json.bak），重启程序后生效。"""
        try:
            res = self.ctx.settings.restore_last_good() or {}
        except Exception as e:  # noqa: BLE001 —— 回滚失败不能崩界面
            res = {"ok": False, "error": str(e)}
        if not res.get("ok"):
            self.ctx.show_toast("回滚失败：" + str(res.get("error") or "没有可回滚的备份"))
            return
        self._config_restored = True
        self.ctx.show_toast("已回滚，重启程序生效")
        try:
            self.load_settings()      # 回滚后内存里的设置已换，重新载入界面
        except Exception:  # noqa: BLE001 —— 界面刷新失败不影响回滚结果
            pass

    # ------------------------------------------------------------ 外观
    def _apply_live(self):
        """把外观控件当前值写入内存设置并即时生效（不写盘）。"""
        s = self.ctx.settings
        p = self.path_edit.text().strip()
        img = p.lower().endswith((".png", ".jpg", ".jpeg", ".bmp", ".webp"))
        enabled = self.chk_enabled.isChecked() and bool(p)
        s.bg_image_enabled = enabled and img
        s.bg_image_path = p if img else ""
        s.bg_video_enabled = enabled and not img
        s.bg_video_path = p if not img else ""
        s.bg_video_autoplay = self.chk_autoplay.isChecked()
        s.bg_video_loop = self.chk_loop.isChecked()
        s.bg_mask_strength = self.mask_slider.value() / 100.0
        s.ui_opacity = self.opacity_slider.value()
        s.bg_brightness = self.bright_slider.value()
        s.animations_enabled = not self.chk_animations.isChecked()
        s.theme = self.theme_combo.currentData() or "glass"
        s.accent = self.accent_combo.currentData() or "default"
        s.glass_effect = self.glass_combo.currentData() or "default"
        s.ui_color = self.btn_color.text().strip() or "#FFFFFF"
        s.nonebot_enabled = True  # NoneBot 是内置进程，不允许关闭
        s.ai_enabled = self.chk_ai_enabled.isChecked()
        s.auto_start_services = self.chk_auto_start_services.isChecked()
        s.auto_launch_on_boot = self.chk_autostart_boot.isChecked()
        s.developer_mode = self.chk_developer_mode.isChecked()
        s.beginner_mode = self.chk_beginner_mode.isChecked()
        self._update_ui_rows()
        self._style_tabs()          # 换主题/皮肤时页签配色跟着走
        self.ctx.apply_appearance()

    def _on_mask_changed(self, value):
        self.mask_value.setText(f"{value / 100:.2f}")
        self._apply_timer.start()

    def _on_opacity_changed(self, value):
        self.opacity_value.setText(f"{value}%")
        self._apply_timer.start()

    def _on_brightness_changed(self, value):
        self.bright_value.setText(str(value))
        self._apply_timer.start()

    def _on_autostart_toggled(self, checked):
        ok = autostart_mod.set_enabled(checked)
        if not ok and checked:
            self.ctx.show_toast("开机自启动设置失败（非 Windows 或权限不足）")
        self._apply_live()

    def _on_developer_toggled(self, checked):
        """开发者模式必须明确确认免责声明；拒绝则回弹。"""
        if not checked:
            self._apply_live()
            return
        ret = QMessageBox.question(
            self, "开发者模式",
            "开启后插件页将恢复 PyPI / zip 第三方插件安装。\n\n"
            "第三方插件、第三方 OneBot 协议端与官方通道的兼容性、安全性，"
            "以及是否违反平台协议，均由您自行承担；非官方插件或协议端可能导致"
            "机器人异常、消息丢失、账号被限制或封禁。\n\n"
            "确定开启吗？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if ret != QMessageBox.Yes:
            self.chk_developer_mode.blockSignals(True)
            self.chk_developer_mode.setChecked(False)
            self.chk_developer_mode.blockSignals(False)
        self._apply_live()

    def _on_beginner_toggled(self, checked):
        """小白模式：立即生效，隐藏/显示高级页面。

        先刷新外观再切模式，且任一步异常都不能把切换吃掉（修复按钮“不好使”）。
        """
        try:
            self._apply_live()
        except Exception:  # noqa: BLE001 —— 外观异常不影响小白模式切换
            pass
        setter = getattr(self.ctx, "set_beginner_mode", None)
        if setter:
            try:
                setter(bool(checked))
            except Exception:  # noqa: BLE001 —— 切换失败不崩溃 UI
                pass

    def _update_ui_rows(self):
        """按 UI 主题类型显示/隐藏质感、透明度、颜色、强调色设置。"""
        key = self.theme_combo.currentData() or "glass"
        ui = UI_THEMES.get(key, UI_THEMES["glass"])
        is_glass = ui["style"] == "glass"
        self.glass_box.setVisible(is_glass)
        self.accent_box.setVisible(is_glass)
        self.opacity_box.setVisible(True)          # 两种主题都支持不透明度
        self.color_box.setVisible(not is_glass)    # 颜色设置仅非玻璃主题

    def _set_color_button(self, hexv: str):
        c = QColor(hexv or "#FFFFFF")
        text = c.name().upper()
        fg = "#111111" if c.lightness() > 140 else "#FFFFFF"
        self.btn_color.setText(text)
        self.btn_color.setStyleSheet(
            f"background:{text};color:{fg};border:1px solid #C9C9C5;"
            "border-radius:0;font-weight:600;")

    def _pick_color(self):
        c = QColorDialog.getColor(
            QColor(self.btn_color.text() or "#FFFFFF"), self, "选择 UI 框颜色")
        if c.isValid():
            self._set_color_button(c.name().upper())
            self._apply_live()

    def _browse_bg(self):
        f, _ = QFileDialog.getOpenFileName(
            self, "选择背景文件", "",
            "媒体文件 (*.mp4 *.mkv *.mov *.png *.jpg *.jpeg *.bmp *.webp)")
        if f:
            self.path_edit.setText(f)
            self._apply_live()
            kind = "图片" if f.lower().endswith((".png", ".jpg", ".jpeg", ".bmp", ".webp")) else "视频"
            self.ctx.show_toast(f"{kind}背景已应用（点「保存设置」写入配置）")

    def _clear_bg(self):
        self.path_edit.setText("")
        self.chk_enabled.setChecked(False)
        self._apply_live()
        self.ctx.show_toast("已清除背景")

    # ------------------------------------------------------------ 版本/导入
    def _check_update(self):
        worker = Worker(self)
        worker.finished.connect(self._on_update_done)
        threading.Thread(
            target=lambda: worker.run(lambda: update_check.check(force=True)),
            daemon=True,
        ).start()
        self.ctx.show_toast("正在检查更新...")

    def _on_update_done(self, res):
        self.refresh_status()
        if res.get("newer"):
            notes = (res.get("notes") or "").strip()
            QMessageBox.information(
                self, "发现新版本",
                f"发现新版本 {res.get('latest')}\n当前版本 {res.get('current')}\n\n"
                + (notes + "\n\n" if notes else "")
                + "请从下载地址获取新版，配置与插件会自动沿用。")
        elif res.get("ok"):
            self.ctx.show_toast("已是最新版本")
        else:
            self.ctx.show_toast("检查更新失败：" + str(res.get("error") or "网络错误"))

    def _import_old(self):
        p = QFileDialog.getExistingDirectory(self, "选择旧版本安装目录", "")
        if not p:
            return
        if not migrate_mod.is_install_root(p):
            QMessageBox.warning(self, "导入失败", "该目录不是有效的 AstroSwarm 安装目录（缺少 settings.json）")
            return
        if not migrate_mod.is_deployed_root(p):
            QMessageBox.warning(self, "导入失败", "该安装目录未完成部署，无法沿用")
            return
        if migrate_mod.adopt_root(p):
            QMessageBox.information(
                self, "导入成功",
                "已关联旧版本安装目录，其配置、插件、登录信息将原地保留。\n重启程序后生效。")
        else:
            QMessageBox.warning(self, "导入失败", "写入安装指针失败，请检查权限")

    # ------------------------------------------------------------ 卸载
    def _uninstall_app(self):
        ret = QMessageBox.question(
            self, "卸载 AstroSwarm",
            "将停止全部服务并删除整个安装目录（bot / python / 日志等），\n\n"
            "账号登录与授权状态不受影响，之后需要时重新部署。确认卸载？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ret != QMessageBox.Yes:
            return
        if self.ctx.tasks.has_active("service") or self.ctx.tasks.has_active("install"):
            QMessageBox.information(self, "提示", "有任务正在执行，请稍后再卸载")
            return
        self._uninstall_tid = self.ctx.tasks.submit(
            "卸载 AstroSwarm", "install", UninstallTask,
            manager=self.ctx.manager, settings=self.ctx.settings,
        )

    def _on_task_finished(self, tid, status, result):
        if tid != getattr(self, "_uninstall_tid", None):
            return
        self._uninstall_tid = None
        if status == "success":
            QMessageBox.information(
                self, "卸载完成",
                "AstroSwarm 已卸载完成。\n\n程序即将退出，exe 文件请手动删除。")
            QApplication.instance().quit()
        else:
            QMessageBox.warning(
                self, "卸载失败",
                "卸载未完全成功：" + str(result.get("error") or result))

    # ------------------------------------------------------------ 保存
    def _save(self):
        s = self.ctx.settings
        p = self.path_edit.text().strip()
        img = p.lower().endswith((".png", ".jpg", ".jpeg", ".bmp", ".webp"))
        enabled = self.chk_enabled.isChecked() and bool(p)
        s.bg_image_enabled = enabled and img
        s.bg_image_path = p if img else ""
        s.bg_video_enabled = enabled and not img
        s.bg_video_path = p if not img else ""
        s.bg_video_autoplay = self.chk_autoplay.isChecked()
        s.bg_video_loop = self.chk_loop.isChecked()
        s.bg_mask_strength = self.mask_slider.value() / 100.0
        s.ui_opacity = self.opacity_slider.value()
        s.bg_brightness = self.bright_slider.value()
        s.animations_enabled = not self.chk_animations.isChecked()
        s.theme = self.theme_combo.currentData() or "glass"
        s.accent = self.accent_combo.currentData() or "default"
        s.glass_effect = self.glass_combo.currentData() or "default"
        s.ui_color = self.btn_color.text().strip() or "#FFFFFF"
        s.nonebot_enabled = True  # NoneBot 是内置进程，不允许关闭
        s.ai_enabled = self.chk_ai_enabled.isChecked()
        s.auto_start_services = self.chk_auto_start_services.isChecked()
        s.auto_launch_on_boot = self.chk_autostart_boot.isChecked()
        try:
            s.save()
        except OSError as e:
            self.ctx.show_toast("保存设置失败: " + str(e))
            return
        autostart_mod.set_enabled(s.auto_launch_on_boot)
        self.ctx.apply_appearance()
        self.ctx.show_toast("设置已保存")
