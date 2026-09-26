"""主窗口：B 样式无边框窗口 + 侧边栏 + 统一任务系统接线 + 动态视频背景。

后台任务全部走 TaskManager（Worker -> Signal -> TaskManager -> UI），
主窗口只负责接线与展示，不直接执行任何耗时操作。
"""
import ctypes
import time
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QRect, QRectF, QSize, QTimer, Qt, QUrl, Signal
from PySide6.QtGui import (
    QColor, QDesktopServices, QGuiApplication, QLinearGradient, QPainter,
    QPainterPath, QRadialGradient,
)
from PySide6.QtWidgets import (
    QApplication, QDialog, QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QMessageBox, QProgressBar, QPushButton, QScrollArea, QStackedWidget,
    QVBoxLayout, QWidget,
)

from ..constants import APP_VERSION
from ..core import autostart as autostart_mod
from ..core.manager import Manager
from ..core.video_tools import find_default_background
from ..tasks.workers import StartStopTask
from . import theme as theme_mod
from .icon_font import make_icon
from .image_background import ImageBackground
from .pages.common import PageContext, Worker
from .pages.access_page import AccessPage
from .pages.brain_page import BrainPage
from .pages.deps_page import DepsPage
from .pages.feishu_page import FeishuPage
from .pages.home_page import HomePage
from .pages.logs_page import LogsPage
from .pages.message_center_page import MessageCenterPage
from .pages.plugins_page import PluginsPage
from .pages.run_page import RunPage
from .pages.services_page import ServicesPage
from .pages.settings_page import SettingsPage
from .pages.telegram_page import TelegramPage
from .pages.wechat_page import WechatPage
from .theme import build_qss
from .video_background import VideoBackground


# 侧栏 / 顶栏 / 图标栏共用的图标表：一个名字只对应一个语义，互不重复。
# 「接入」原来写的是 plugs-connected —— 图标字体里没有这个字形，渲染出来是空白，
# 这里改成确实存在的字形（arrow-right = 进入通道配置）。
NAV_ICONS = {
    "首页": "home",
    "接入": "arrow-right",
    "微信": "chat-circle-dots",
    "QQ": "chat-circle",
    "飞书": "paper-plane-tilt",
    "纸飞机": "paper-plane",
    "AI 大脑": "brain",
    "插件": "puzzle-piece",
    "全局管理": "robot",
    "消息中心": "chat-centered",
    "日志": "terminal-window",
    "依赖": "package",
    "设置": "gear-six",
}


class LogBus(QObject):
    """统一日志总线：Manager / 任务 / 外观等来源都汇聚到这里，供日志页订阅。"""
    entry = Signal(str, str, str)   # source, level, msg

    def emit_entry(self, source, level, msg):
        self.entry.emit(source, level, str(msg))


class ResizeHandle(QWidget):
    """无边框窗口边缘拖拽手柄：按下并移动时调整 MainWindow 大小。"""

    def __init__(self, win, edge, cursor, parent=None):
        super().__init__(parent or win)
        self._win = win
        self._edge = edge
        self.setCursor(cursor)
        self.setMouseTracking(True)
        self._pressed = False
        self._start_geom = None
        self._start_gpos = None

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and not self._win.isMaximized():
            self._pressed = True
            self._start_geom = self._win.geometry()
            self._start_gpos = event.globalPosition().toPoint()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._pressed and self._start_geom is not None:
            self._win._apply_resize_edge(
                self._edge, self._start_geom, self._start_gpos,
                event.globalPosition().toPoint())
            event.accept()

    def mouseReleaseEvent(self, event):
        self._pressed = False
        event.accept()


class TitleBar(QFrame):
    """自定义标题栏：拖拽移动窗口、双击最大化、最小化/最大化/关闭按钮。"""

    def __init__(self, win, title="AstroSwarm 星群", subtitle=""):
        super().__init__()
        self.setObjectName("titlebar")
        self.setFixedHeight(44)
        self._win = win
        self._drag_pos = None

        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 0, 0, 0)
        lay.setSpacing(8)
        self.title = QLabel(title)
        self.title.setObjectName("appTitle")
        self.sub = QLabel(subtitle)
        self.sub.setObjectName("appSub")
        lay.addWidget(self.title)
        lay.addWidget(self.sub)
        lay.addStretch(1)
        for text, obj_name, handler in (
            ("—", "winMin", win.showMinimized),
            ("□", "winMax", win.toggle_max),
            ("✕", "winClose", win.close),
        ):
            btn = QPushButton(text)
            btn.setObjectName(obj_name)
            btn.setProperty("class", "winbtn")
            btn.setFixedSize(46, 36)
            btn.setFocusPolicy(Qt.NoFocus)
            btn.clicked.connect(handler)
            lay.addWidget(btn)

    # ---- 拖拽移动 ----
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self._win.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_pos is not None and (event.buttons() & Qt.LeftButton):
            self._win.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_pos = None

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._win.toggle_max()


class MainWindow(QWidget):
    account_kicked = Signal(str)

    # 侧栏分组与控制台（无头端）的 NAV_GROUPS 一一对应：运行 / 能力 / 系统。
    # 桌面端多出四个通道配置页（微信/QQ/飞书/纸飞机）—— 无头端把通道配置收在「接入」页里，
    # 桌面端保留独立页面，统一挂在「运行」组，顺序与以前一致（少一次记忆迁移）。
    NAV_GROUPS = (
        ("运行", ("首页", "接入", "微信", "QQ", "飞书", "纸飞机")),
        ("能力", ("AI 大脑", "插件")),
        ("系统", ("全局管理", "消息中心", "日志", "依赖", "设置")),
    )
    # 页面索引顺序：与控制台一致，新增页插在它该在的位置（不再往后追加）
    PAGE_ORDER = tuple(n for _title, _items in NAV_GROUPS for n in _items)
    # 小白模式（默认开启）下隐藏这些入口，可在「设置」里关掉
    ADVANCED_PAGES = ("微信", "QQ", "飞书", "纸飞机", "消息中心", "插件", "日志", "依赖")
    SEPARATOR = "— 全局管理 —"
    RESIZE_MARGIN = 8          # 窗口边缘可拖拽区宽度（px）
    MIN_WINDOW_W = 960         # 窗口最小宽
    MIN_WINDOW_H = 640         # 窗口最小高

    def __init__(self, settings, tasks):
        super().__init__()
        self.settings = settings
        self.tasks = tasks
        self._closing = False
        self.setMinimumSize(self.MIN_WINDOW_W, self.MIN_WINDOW_H)
        self._exit_stop_tid = None
        self._exit_poll = None
        self._exit_dialog = None

        self.setWindowTitle("AstroSwarm 星群")
        self.setMinimumSize(1080, 700)
        self.resize(1280, 800)
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        # 透明窗口 + 抗锯齿圆角绘制：区域遮罩（setMask）有锯齿，改用透明合成
        self.setAttribute(Qt.WA_TranslucentBackground, True)

        # 统一日志总线：Manager 实时日志 + 任务日志
        self.log_bus = LogBus(self)
        self.manager = Manager(
            settings,
            on_log=lambda line: self.log_bus.emit_entry("管理器", "INFO", line),
        )
        self.tasks.log.connect(
            lambda tid, lv, msg: self.log_bus.emit_entry("任务", lv, msg))

        # 背景层（先添加 = 位于底层）
        self.img_bg = ImageBackground(self)
        self.img_bg.setVisible(False)
        self.bg = VideoBackground(self)
        self.bg.loadFailed.connect(self._on_bg_load_failed)
        self.bg.fallbackNotice.connect(self._on_bg_fallback)
        self.bg.playbackRequested.connect(self._on_bg_playback_requested)
        self._applied_skin = None
        self._current_layout_mode = None
        self._account_buttons = []
        self._account_window = None

        self._build_ui()
        self._refresh_account_buttons()
        self._create_resize_handles()
        self.apply_appearance()
        self._center_on_screen()

        self.watch_timer = QTimer(self)
        self.watch_timer.setInterval(2000)
        self.watch_timer.timeout.connect(self._on_tick)
        self.watch_timer.start()
        # 启动后自动检查新版本（后台线程，不阻塞界面）
        self._update_prompted = False
        QTimer.singleShot(2500, self._start_update_check)
        # 星群账号激活状态：登录后每小时自动同步一次
        self._account_sync_timer = QTimer(self)
        self._account_sync_timer.setInterval(3600 * 1000)
        self._account_sync_timer.timeout.connect(self._hourly_account_sync)
        self._account_sync_timer.start()
        QTimer.singleShot(10000, self._hourly_account_sync)
        # 账号一设备一登录：每 15 分钟检测本机是否已被其他设备顶下线
        self.account_kicked.connect(self._on_account_kicked)
        self._device_check_timer = QTimer(self)
        self._device_check_timer.setInterval(15 * 60 * 1000)
        self._device_check_timer.timeout.connect(self._account_device_check)
        self._device_check_timer.start()
        QTimer.singleShot(5000, self._account_device_check)
        QTimer.singleShot(800, self._maybe_auto_start)

    def _hourly_account_sync(self):
        """后台自动同步激活状态到星群账号（每小时一次）。"""
        import threading

        from ..core import account, license as lic_mod
        acc = account.load_account()
        if not acc:
            return
        st = lic_mod.status()
        if not st.get("activated"):
            return

        def _sync():
            try:
                data = account.sync(
                    acc["token"], st["machine_id"], st.get("key", ""),
                    st.get("expires_at") or 0)
                if data.get("ok"):
                    # 同步服务器 plan / 已登记插件，保持插件商店权益最新
                    # 没签名就不写：这次同步的响应不带 entitlement_sig 时，
                    # 原来的写法会把本机已生效的权益抹成空签名（当场掉回未开通）
                    lic_mod.save_entitlements_from_account(data)
            except Exception:  # noqa: BLE001
                pass

        threading.Thread(target=_sync, daemon=True).start()

    def _account_device_check(self):
        """检测本机是否仍是账号活跃设备；被顶下线则清空本机授权。"""
        import threading

        from ..core import account, license as lic_mod
        acc = account.load_account()
        if not acc:
            return
        mid = lic_mod.machine_code()

        def _check():
            try:
                data = account.check_device(acc["token"], mid)
                if data.get("ok") and data.get("active") is False:
                    lic_mod.clear_license()
                    account.clear_account()
                    self.account_kicked.emit("该账号已在其他设备登录，本机已下线")
            except Exception:  # noqa: BLE001
                pass

        threading.Thread(target=_check, daemon=True).start()

    def _on_account_kicked(self, msg):
        self.show_toast(msg, 4000)
        for page in self.pages:
            if hasattr(page, "_refresh_account_status"):
                try:
                    page._refresh_account_status()
                except Exception:  # noqa: BLE001
                    pass
        self._refresh_account_buttons()

    # ------------------------------------------------------------ 左上角账号入口
    def _make_account_button(self, icon_only=False):
        """创建主界面左上角的星群账号入口按钮（侧边栏/顶栏/图标栏各一份）。"""
        btn = QPushButton()
        btn.setObjectName("ghost")
        btn.setCursor(Qt.PointingHandCursor)
        btn.setIcon(make_icon("gear", "#A7B1C2", 16))
        btn.setToolTip("星群账号 · 未登录")
        btn.setMinimumHeight(30)
        if icon_only:
            btn.setFixedSize(38, 38)
        else:
            btn.setText("星群账号")
        btn.clicked.connect(self._open_account_window)
        self._account_buttons.append(btn)
        return btn

    def _refresh_account_buttons(self):
        """更新左上角账号按钮的登录提示。"""
        try:
            from ..core import account
            acc = account.load_account()
        except Exception:  # noqa: BLE001
            acc = None
        tip = ("星群账号 · 已登录：" + str(acc.get("email") or "")
               if acc else "星群账号 · 未登录，点击登录")
        for btn in self._account_buttons:
            btn.setToolTip(tip)

    def _open_account_window(self):
        """打开个人中心（星群账号）独立窗口，默认贴屏幕左上角。"""
        if getattr(self, "_account_window", None) is None:
            from .pages.account_window import AccountWindow
            self._account_window = AccountWindow(self._page_ctx, parent=self)
            self._account_window.account_changed.connect(self._on_account_changed)
        win = self._account_window
        win._refresh_status()
        win.show()
        win.raise_()
        win.activateWindow()

    def _on_account_changed(self):
        """账号登录/退出后：刷新左上角按钮与各页面状态。"""
        self._refresh_account_buttons()
        for page in self.pages:
            if hasattr(page, "_refresh_account_status"):
                try:
                    page._refresh_account_status()
                except Exception:  # noqa: BLE001
                    pass
            if hasattr(page, "_fill_license_status"):
                try:
                    page._fill_license_status()
                except Exception:  # noqa: BLE001
                    pass

    def _maybe_auto_start(self):
        """按设置自动处理：开机自启动注册表补写 + 启动程序时自动启动全部服务。"""
        if self._closing:
            return
        try:
            if getattr(self.settings, "auto_launch_on_boot", False):
                autostart_mod.set_enabled(True)
            if not getattr(self.settings, "auto_start_services", False):
                return
            if self.manager.bot_running() or self.manager.dsh_running() or self.manager.qq_running():
                return
            self.tasks.submit(
                "启动服务", "service", StartStopTask,
                payload={"start": True}, retryable=True, manager=self.manager,
            )
            self.show_toast("已按设置自动启动全部服务", 2600)
        except Exception as e:  # noqa: BLE001
            self.log_bus.emit_entry("管理器", "ERROR", f"自动启动失败: {e}")

    # ------------------------------------------------------------ 版本检查
    def _start_update_check(self):
        import os as _os
        import threading
        from ..core import update_check

        if _os.environ.get("QBM_NO_UPDATE") == "1":
            return
        worker = Worker(self)
        worker.finished.connect(self._on_update_result)
        threading.Thread(
            target=lambda: worker.run(lambda: update_check.check(force=False)),
            daemon=True,
        ).start()

    def _on_update_result(self, res):
        if self._update_prompted or not res.get("newer"):
            return
        self._update_prompted = True
        url = res.get("url") or ""
        notes = (res.get("notes") or "").strip()
        msg = f"发现新版本 {res.get('latest')}\n当前版本 {res.get('current')}"
        if notes:
            msg += "\n\n更新说明：\n" + notes
        box = QMessageBox(self)
        box.setWindowTitle("发现新版本")
        box.setText(msg)
        box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        box.button(QMessageBox.Yes).setText("前往下载")
        box.button(QMessageBox.No).setText("稍后")
        if box.exec() == QMessageBox.Yes and url:
            QDesktopServices.openUrl(QUrl(url))

    # ------------------------------------------------------------ UI
    def _build_ui(self):
        self.titlebar = TitleBar(self, "AstroSwarm 星群", f"v{APP_VERSION}")

        self.sidebar = QWidget()
        self.sidebar.setObjectName("sidebarWrap")
        self.sidebar.setFixedWidth(180)
        side = QVBoxLayout(self.sidebar)
        side.setContentsMargins(0, 0, 0, 0)
        side.setSpacing(0)

        # 三组导航比原来的两组高，窗口矮的时候必须能滚：内容装进 QScrollArea，
        # 每个列表按内容定高（内部不再出现第二根滚动条 —— 那会让「插件」「设置」
        # 看起来像被截断了）。
        nav_container = QWidget()
        nav = QVBoxLayout(nav_container)
        nav.setContentsMargins(8, 10, 8, 10)
        nav.setSpacing(6)

        self.btn_account_side = self._make_account_button()
        nav.addWidget(self.btn_account_side)

        # 一组一个列表：组名与控制台 NAV_GROUPS 同名（运行 / 能力 / 系统），
        # 组内顺序也一致 —— 两边看同一套侧栏，用户不用重新找菜单位置。
        self.nav_lists = []
        self._nav_rows = {}
        for gi, (group_title, items) in enumerate(self.NAV_GROUPS):
            lbl = QLabel(group_title)
            lbl.setObjectName("sidebarGroupTitle")
            nav.addWidget(lbl)
            lst = QListWidget()
            lst.setObjectName("sidebar")
            lst.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            lst.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            for row, name in enumerate(items):
                item = QListWidgetItem(name)
                item.setIcon(make_icon(NAV_ICONS.get(name, "home"), "#A7B1C2", 15))
                # 行高写死 40：样式表默认算出来 58px，13 个菜单项加起来会把侧栏
                # 顶到要滚动（默认窗口高度只有 800）。40 刚好放下 15px 图标 + 14px 文字。
                item.setSizeHint(QSize(0, 40))
                lst.addItem(item)
                self._nav_rows[name] = (gi, row)
            lst.currentRowChanged.connect(
                lambda _row, l=lst: self._on_sidebar_changed(l))
            # 按内容定高：列表自己不再出现第二根滚动条（那会让「插件」「设置」像被截断）
            lst.setFixedHeight(40 * lst.count() + 6)
            nav.addWidget(lst)
            self.nav_lists.append(lst)
        # 旧代码/测试沿用的两个别名（运行组、系统组）；能力组是新增的中间一组
        self.sidebar_platform = self.nav_lists[0]
        self.sidebar_skill = self.nav_lists[1]
        self.sidebar_global = self.nav_lists[2]
        nav.addStretch(1)

        sidebar_scroll = QScrollArea()
        sidebar_scroll.setObjectName("sidebarScroll")
        # 滚动区只是「窗口太矮时能滚」，视觉上必须和侧栏一样透，不能出现白底
        sidebar_scroll.setStyleSheet(
            "QScrollArea#sidebarScroll{background:transparent;border:none;}"
            "QScrollArea#sidebarScroll > QWidget > QWidget{background:transparent;}")
        sidebar_scroll.setWidget(nav_container)
        sidebar_scroll.setWidgetResizable(True)
        sidebar_scroll.setFrameShape(QFrame.NoFrame)
        sidebar_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        sidebar_scroll.viewport().setAutoFillBackground(False)
        nav_container.setAutoFillBackground(False)
        side.addWidget(sidebar_scroll, 1)

        # 页面索引（所有导航共用）
        self._page_index = {n: i for i, n in enumerate(self.PAGE_ORDER)}
        self._build_rail()
        self._build_topnav()
        self._apply_nav_mode()

        self.stack = QStackedWidget()
        callbacks = {
            "open_logs": self.open_logs,
            "show_toast": self.show_toast,
            "switch_page": self.switch_page,
            "apply_appearance": self.apply_appearance,
            "apply_skin": self.apply_skin,
            "set_beginner_mode": self.set_beginner_mode,
            "bg_status": self.bg.capability,
        }
        ctx = PageContext(self.settings, self.manager, self.tasks, callbacks)
        self._page_ctx = ctx
        # 顺序必须与 PAGE_ORDER 一一对应（页面下标 = 导航字典里的索引）
        self.pages = [
            HomePage(ctx),                 # 首页
            AccessPage(ctx),               # 接入
            WechatPage(ctx),               # 微信
            RunPage(ctx),                  # QQ
            FeishuPage(ctx),               # 飞书
            TelegramPage(ctx),             # 纸飞机
            BrainPage(ctx),                # AI 大脑
            PluginsPage(ctx),              # 插件
            ServicesPage(ctx),             # 全局管理（服务启停 + 运维细节）
            MessageCenterPage(ctx),        # 消息中心
            LogsPage(ctx, self.log_bus),   # 日志
            DepsPage(ctx),                 # 依赖
            SettingsPage(ctx),             # 设置
        ]
        assert len(self.pages) == len(self.PAGE_ORDER), (
            "页面数量与 PAGE_ORDER 不一致：加页面时 NAV_GROUPS 与这里都要改")
        for page in self.pages:
            self.stack.addWidget(page)
        # 启动落在「首页」：等 stack 建好再选行，否则 setCurrentRow 回调
        # _on_sidebar_changed -> _go_page 会去碰还不存在的 self.stack
        self._go_page("首页")

        self.overlay = QWidget(self)
        self._outer = QVBoxLayout(self.overlay)
        self._outer.setContentsMargins(0, 0, 0, 0)
        self._outer.setSpacing(0)
        self._outer.addWidget(self.titlebar)
        self._apply_layout()

        # Toast
        self._toast = QLabel(self.overlay)
        self._toast.setObjectName("toast")
        self._toast.hide()
        self._toast_timer = QTimer(self)
        self._toast_timer.setSingleShot(True)
        self._toast_timer.timeout.connect(self._toast.hide)

        for page in self.pages:
            if hasattr(page, "refresh_status"):
                page.refresh_status()

    # ------------------------------------------------------------ 页面/导航
    def _build_topnav(self):
        """瑞士极简的顶部横排导航（与侧边栏二选一，由 UI 主题决定）。"""
        self.topnav = QWidget()
        self.topnav.setObjectName("topnav")
        self.topnav.setFixedHeight(54)
        lay = QHBoxLayout(self.topnav)
        lay.setContentsMargins(16, 0, 24, 0)
        lay.setSpacing(2)
        self.btn_account_top = self._make_account_button()
        lay.addWidget(self.btn_account_top)
        lay.addSpacing(10)
        self._topnav_map = {}
        for _title, items in self.NAV_GROUPS:
            for name in items:
                b = QPushButton(name)
                b.setObjectName("topnavItem")
                b.setCheckable(True)
                b.setCursor(Qt.PointingHandCursor)
                b.setIcon(make_icon(NAV_ICONS.get(name, "home"), "#444444", 14))
                b.clicked.connect(lambda checked=False, n=name: self._go_page(n))
                self._topnav_map[b] = name
                lay.addWidget(b)
            sep = QFrame()
            sep.setFrameShape(QFrame.VLine)
            sep.setStyleSheet("color:#D9D9D6;")
            lay.addWidget(sep)
            lay.addSpacing(6)
        lay.addStretch(1)

    def _build_rail(self):
        """深空终端的左侧图标栏（窄 Dock，与侧边栏/顶部导航互不重复）。"""
        self._rail_icons = dict(NAV_ICONS)
        self._rail_names = list(self.PAGE_ORDER)
        self.rail = QWidget()
        self.rail.setObjectName("railWrap")
        self.rail.setFixedWidth(54)
        lay = QVBoxLayout(self.rail)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.btn_account_rail = self._make_account_button(icon_only=True)
        lay.addWidget(self.btn_account_rail, 0, Qt.AlignHCenter)
        lay.addSpacing(4)
        self.rail_list = QListWidget()
        self.rail_list.setObjectName("rail")
        self.rail_list.setFixedWidth(54)
        self.rail_list.setIconSize(QSize(20, 20))
        self.rail_list.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.rail_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._rail_rows = {}
        for i, name in enumerate(self._rail_names):
            item = QListWidgetItem()
            item.setIcon(make_icon(self._rail_icons.get(name, "home"), "#9BA7B4", 20))
            item.setToolTip(name)
            item.setTextAlignment(Qt.AlignCenter)
            self.rail_list.addItem(item)
            self._rail_rows[name] = i
        self.rail_list.setCurrentRow(0)
        self.rail_list.currentRowChanged.connect(self._on_rail_changed)
        lay.addWidget(self.rail_list)

    def _on_rail_changed(self, row):
        if row < 0:
            return
        name = self._rail_names[row]
        self._go_page(name)

    def _paint_rail(self, active_name):
        """图标栏：当前页图标用强调色，其余用中性灰。"""
        if not self._rail_names:
            return
        accent = theme_mod.THEMES.get(
            getattr(self.settings, "accent", "default") or "default",
            theme_mod.THEMES["default"])["ACCENT"]
        for i, name in enumerate(self._rail_names):
            color = accent if name == active_name else "#9BA7B4"
            self.rail_list.item(i).setIcon(
                make_icon(self._rail_icons.get(name, "home"), color, 20))

    def _apply_layout(self):
        """按当前 UI 主题布局重建主区域（侧边栏 / 顶部导航）。"""
        if theme_mod.UI_LAYOUT == self._current_layout_mode:
            return  # 布局没变就不拆装页面，避免整棵控件树重挂载卡顿
        current_page = self.stack.currentIndex()
        while self._outer.count() > 1:
            item = self._outer.takeAt(1)
            w = item.widget()
            if w is not None:
                w.setParent(None)
            elif item.layout() is not None:
                while item.layout().count():
                    it = item.layout().takeAt(0)
                    if it.widget() is not None:
                        it.widget().setParent(None)
        if theme_mod.UI_LAYOUT == "topnav":
            self._outer.addWidget(self.topnav)
            self._outer.addWidget(self.stack, 1)
        else:
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(0)
            if theme_mod.UI_LAYOUT == "rail":
                row.addWidget(self.rail)
            else:
                row.addWidget(self.sidebar)
            row.addWidget(self.stack, 1)
            self._outer.addLayout(row, 1)
        # 重建后恢复原页面，避免布局切换时跳回首页
        self.stack.setCurrentIndex(min(current_page, max(0, self.stack.count() - 1)))
        self._current_layout_mode = theme_mod.UI_LAYOUT

    def _on_sidebar_changed(self, lst):
        row = lst.currentRow()
        if row < 0:
            return
        gi = self.nav_lists.index(lst)
        items = self.NAV_GROUPS[gi][1]
        if row >= len(items):
            return
        # 只有一组能选中：切这一组时把其余组清空，否则会出现两处同时高亮
        for other in self.nav_lists:
            if other is not lst:
                other.setCurrentItem(None)
        self._go_page(items[row])

    def _apply_nav_mode(self):
        """小白模式：隐藏高级页面（通道页 + 消息中心/插件/日志/依赖）。"""
        beginner = bool(self.settings.beginner_mode)
        for gi, (_title, items) in enumerate(self.NAV_GROUPS):
            lst = self.nav_lists[gi]
            for row, name in enumerate(items):
                lst.setRowHidden(row, beginner and name in self.ADVANCED_PAGES)
        if self._rail_rows:
            for name in self._rail_names:
                self.rail_list.setRowHidden(
                    self._rail_rows[name], beginner and name in self.ADVANCED_PAGES)
        for btn, name in self._topnav_map.items():
            btn.setVisible(not (beginner and name in self.ADVANCED_PAGES))

    def nav_row_hidden(self, name) -> bool:
        """某个导航项当前是否被小白模式藏起来了（设置页/测试用它，别写死行号）。"""
        loc = self._nav_rows.get(name)
        if loc is None:
            return True
        gi, row = loc
        return bool(self.nav_lists[gi].isRowHidden(row))

    def set_beginner_mode(self, on: bool):
        """切换小白模式：立即生效并保存。"""
        on = bool(on)
        self.settings.beginner_mode = on
        self.settings.save()
        self._apply_nav_mode()
        if on:
            idx = self.stack.currentIndex()
            name = next((n for n, i in self._page_index.items() if i == idx), None)
            if name in self.ADVANCED_PAGES:
                self._go_page("首页")
        for page in self.pages:
            if hasattr(page, "set_beginner"):
                try:
                    page.set_beginner(on)
                except Exception:  # noqa: BLE001
                    pass
        self.show_toast(
            "已开启小白模式（只显示常用功能）" if on else "已关闭小白模式（显示全部功能）",
            2200)

    def _go_page(self, name):
        idx = self._page_index.get(name)
        if idx is None:
            return
        self.stack.setCurrentIndex(idx)
        self._sync_nav(name)
        QTimer.singleShot(60, self._refresh_glass_panels)

    def _refresh_glass_panels(self):
        """页面切换后统一刷新玻璃背景（替代原来的 700ms 周期抓屏）。"""
        for w in self.findChildren(QWidget):
            if w.metaObject().className() == "GlassPanel" and w.isVisible():
                try:
                    w.refresh_now()
                except Exception:  # noqa: BLE001
                    pass

    def _sync_nav(self, name):
        loc = self._nav_rows.get(name)
        if loc is not None:
            gi, row = loc
            lst = self.nav_lists[gi]
            if lst.currentRow() != row:
                # setCurrentRow 会回调 _on_sidebar_changed -> _go_page，
                # 第二次进来 currentRow 已经相等，不会递归
                lst.setCurrentRow(row)
            for other in self.nav_lists:
                if other is not lst:
                    other.setCurrentItem(None)
        if self._rail_rows:
            row = self._rail_rows.get(name)
            if row is not None and self.rail_list.currentRow() != row:
                self.rail_list.setCurrentRow(row)
            self._paint_rail(name)
        for btn, n in self._topnav_map.items():
            btn.setChecked(n == name)

    def switch_page(self, name):
        self._go_page(name)

    def open_logs(self):
        self.switch_page("日志")

    # ------------------------------------------------------------ Toast
    def show_toast(self, msg, duration=2800):
        self._toast.setText(str(msg))
        self._toast.adjustSize()
        self._toast.show()
        self._toast.raise_()
        self._reposition_toast()
        self._toast_timer.start(duration)

    def _reposition_toast(self):
        self._toast.move(
            (self.width() - self._toast.width()) // 2,
            self.height() - self._toast.height() - 72,
        )

    def paintEvent(self, event):
        """极光玻璃底色：视频/图片背景启用时由上层背景覆盖。"""
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        r = 0 if (self.isMaximized() or self.isFullScreen()) else theme_mod.WINDOW_RADIUS
        if r:
            path.addRoundedRect(rect, r, r)
        else:
            path.addRect(rect)
        p.setClipPath(path)
        if theme_mod.UI_STYLE == "swiss":
            p.fillRect(self.rect(), QColor(247, 247, 245))
            p.end()
            return
        if theme_mod.UI_STYLE == "terminal":
            p.fillRect(self.rect(), QColor(10, 13, 16))
            p.end()
            return
        g = QLinearGradient(0, 0, self.width(), self.height())
        g.setColorAt(0, QColor(18, 22, 46))
        g.setColorAt(0.55, QColor(24, 22, 58))
        g.setColorAt(1, QColor(10, 13, 24))
        p.fillRect(self.rect(), g)
        for cx, cy, r, c in (
            (self.width() * 0.22, self.height() * 0.15, 340, QColor(88, 101, 242, 70)),
            (self.width() * 0.82, self.height() * 0.28, 300, QColor(139, 92, 246, 60)),
            (self.width() * 0.55, self.height() * 0.85, 360, QColor(56, 189, 248, 46)),
        ):
            rg = QRadialGradient(cx, cy, r)
            rg.setColorAt(0, c)
            rg.setColorAt(1, QColor(0, 0, 0, 0))
            p.fillRect(self.rect(), rg)
        p.end()

    # ------------------------------------------------------------ 背景
    def apply_appearance(self):
        s = self.settings
        self.apply_skin()
        # UI 框透明度变化时强制重建样式触发全局重绘
        op = max(0.1, min(0.95, s.ui_opacity / 100.0))
        if abs(op - theme_mod.UI_OPACITY) > 0.001:
            theme_mod.UI_OPACITY = op
            self._repaint_glass()
        color = (s.ui_color or "#FFFFFF").strip()
        if color.upper() != theme_mod.UI_FRAME_COLOR.upper():
            theme_mod.UI_FRAME_COLOR = color
            self._repaint_glass()
        self.bg.set_mask_strength(s.bg_mask_strength)
        self.bg.set_autoplay(s.bg_video_autoplay)
        self.bg.set_loop(s.bg_video_loop)
        self.bg.set_brightness(s.bg_brightness)
        # 图片背景优先于视频
        img_ok = False
        if s.bg_image_enabled and s.bg_image_path:
            self.img_bg.set_image(s.bg_image_path)
            img_ok = self.img_bg.has_image()
        self.img_bg.setVisible(img_ok)
        if img_ok:
            self.bg.set_enabled(False)
            self.bg.set_video(None)
            self.bg.setVisible(False)
            self.manager.log("图片背景: " + str(s.bg_image_path))
            return
        self.bg.set_enabled(s.bg_video_enabled)
        path = s.bg_video_path or find_default_background(s)
        if not path:
            self.bg.set_video(None)
            self.bg.setVisible(False)
            return
        # Phase 2：set_video 会发出 playbackRequested，由主窗口选档并走后台任务准备/转码
        self.bg.setVisible(True)
        # 路径比较必须统一为 Path 对象（正/反斜杠、大小写都归一），
        # 否则每次外观刷新（含滑条/换档）都会误判路径变化重拉视频。
        path_changed = Path(str(path)) != getattr(self.bg, "_path", None)
        if path_changed:
            self.bg.set_video(str(path))
        if s.bg_video_enabled:
            self.manager.log("动态背景源: " + str(path))

    def _repaint_glass(self):
        """玻璃/瑞士卡片自绘参数变化时全量重绘。"""
        for w in self.findChildren(QWidget):
            if w.metaObject().className() in ("GlassPanel", "StatusBadge", "TaskProgressBar"):
                w.update()

    def apply_skin(self, force: bool = False):
        """按设置的 UI 主题（布局/导航/配色/质感）重建界面。"""
        theme = self.settings.theme or "glass"
        if theme not in theme_mod.UI_THEMES:
            theme = "glass"
        glass = self.settings.glass_effect or "default"
        accent = self.settings.accent or "default"
        ui = theme_mod.UI_THEMES[theme]
        key = (theme, glass, accent, ui["layout"], ui["style"])
        if not force and key == self._applied_skin:
            return  # 主题/质感没变就跳过重建，避免拖动滑条时卡顿
        self._applied_skin = key
        theme_mod.UI_STYLE = ui["style"]
        theme_mod.UI_LAYOUT = ui["layout"]
        theme_mod.CURRENT_GLASS = glass
        theme_mod.UI_FRAME_COLOR = (self.settings.ui_color or "#FFFFFF").strip()
        theme_mod.SUPPRESS_BACKDROP_REFRESH = True
        try:
            self._apply_layout()
        finally:
            # 等布局与样式应用完再统一刷新玻璃背景，避免每个面板各自抓屏导致卡顿
            QTimer.singleShot(180, self._finish_theme_switch)
        try:
            QApplication.instance().setStyleSheet(
                build_qss(theme, glass, accent))
        except Exception:  # noqa: BLE001
            QApplication.instance().setStyleSheet(build_qss("glass", glass))

    def _finish_theme_switch(self):
        theme_mod.SUPPRESS_BACKDROP_REFRESH = False
        self._refresh_glass_panels()
        self._repaint_glass()

    def _on_bg_playback_requested(self, src):
        self.manager.log("动态背景: 直接播放原视频 " + str(src))
        self.bg.play_file(str(src))

    def _on_bg_fallback(self, reason):
        self.log_bus.emit_entry("外观", "WARN", "动态背景: " + str(reason))

    def _on_bg_load_failed(self, desc):
        self.log_bus.emit_entry(
            "外观", "WARN", "背景视频加载失败，已切换静态背景: " + str(desc))
        self.manager.log("背景视频播放失败: " + str(desc))

    def _on_tick(self):
        if self._closing:
            return
        for page in self.pages:
            if hasattr(page, "refresh_status"):
                try:
                    page.refresh_status()
                except Exception as e:  # noqa: BLE001
                    self.log_bus.emit_entry(
                        "管理器", "ERROR", f"{type(page).__name__} 刷新失败: {e}")
    # ------------------------------------------------------------ 窗口
    def toggle_max(self):
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def _center_on_screen(self):
        scr = QGuiApplication.primaryScreen()
        if scr is not None:
            geo = scr.availableGeometry()
            self.move(
                geo.center().x() - self.width() // 2,
                geo.center().y() - self.height() // 2,
            )

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.WindowStateChange:
            self.bg.set_window_active(not self.isMinimized())
            self._sync_corner_radius()

    def showEvent(self, event):
        super().showEvent(event)
        self._sync_corner_radius()

    def _sync_corner_radius(self):
        """通知各背景层圆角半径（最大化/全屏时变直角），并重绘本窗口。"""
        square = self.isMaximized() or self.isFullScreen()
        r = 0 if square else theme_mod.WINDOW_RADIUS
        if hasattr(self, "titlebar"):
            self.titlebar.setProperty("corner", "square" if square else "round")
            style = self.titlebar.style()
            style.unpolish(self.titlebar)
            style.polish(self.titlebar)
            self.titlebar.update()
        self.bg.set_corner_radius(r)
        self.img_bg.set_corner_radius(r)
        self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.bg.setGeometry(self.rect())
        self.img_bg.setGeometry(self.rect())
        self.overlay.setGeometry(self.rect())
        self._layout_resize_handles()
        self._reposition_toast()
        self._sync_corner_radius()

    # ------------------------------------------------------------ 边缘拖拽缩放
    def _create_resize_handles(self):
        """创建 8 个边缘手柄（四边 + 四角），置于 overlay 之上。"""
        cursors = {
            "left": Qt.SizeHorCursor, "right": Qt.SizeHorCursor,
            "top": Qt.SizeVerCursor, "bottom": Qt.SizeVerCursor,
            "topleft": Qt.SizeFDiagCursor, "bottomright": Qt.SizeFDiagCursor,
            "topright": Qt.SizeBDiagCursor, "bottomleft": Qt.SizeBDiagCursor,
        }
        self._resize_handles = {
            name: ResizeHandle(self, name, cur, parent=self.overlay)
            for name, cur in cursors.items()
        }
        self._layout_resize_handles()
        for h in self._resize_handles.values():
            h.raise_()

    def _layout_resize_handles(self):
        if not hasattr(self, "_resize_handles"):
            return
        r = self.overlay.rect()
        t = self.RESIZE_MARGIN
        c = t * 2
        pos = {
            "left": (0, 0, t, r.height()),
            "right": (r.width() - t, 0, t, r.height()),
            "top": (0, 0, r.width(), t),
            "bottom": (0, r.height() - t, r.width(), t),
            "topleft": (0, 0, c, c),
            "topright": (r.width() - c, 0, c, c),
            "bottomleft": (0, r.height() - c, c, c),
            "bottomright": (r.width() - c, r.height() - c, c, c),
        }
        for name, h in self._resize_handles.items():
            x, y, w, hgt = pos[name]
            h.setGeometry(x, y, w, hgt)
        for h in self._resize_handles.values():
            h.raise_()

    def _apply_resize_edge(self, edge, start_geom, start_gpos, gpos):
        """按边缘方向把窗口从 start_geom 调整到 gpos（含最小尺寸保护）。"""
        g = QRect(start_geom)
        dx = gpos.x() - start_gpos.x()
        dy = gpos.y() - start_gpos.y()
        e = edge
        if "left" in e:
            g.setLeft(g.left() + dx)
        if "right" in e:
            g.setRight(g.right() + dx)
        if "top" in e:
            g.setTop(g.top() + dy)
        if "bottom" in e:
            g.setBottom(g.bottom() + dy)
        if g.width() < self.MIN_WINDOW_W:
            if "left" in e:
                g.setLeft(g.right() - self.MIN_WINDOW_W)
            else:
                g.setWidth(self.MIN_WINDOW_W)
        if g.height() < self.MIN_WINDOW_H:
            if "top" in e:
                g.setTop(g.bottom() - self.MIN_WINDOW_H)
            else:
                g.setHeight(self.MIN_WINDOW_H)
        self.setGeometry(g)

    def nativeEvent(self, eventType, message):
        """Windows 原生命中测试：让系统直接处理边缘/顶角缩放，精确且不受子控件遮挡影响。"""
        try:
            if isinstance(eventType, bytes) and b"windows_generic_MSG" in eventType:
                msg = ctypes.wintypes.MSG.from_address(int(message))
                if msg.message == 0x0084:  # WM_NCHITTEST
                    if self.isMaximized() or self.isFullScreen():
                        return False, 0
                    dpr = self.devicePixelRatioF() or 1.0
                    x = ctypes.c_short(msg.lParam & 0xFFFF).value
                    y = ctypes.c_short((msg.lParam >> 16) & 0xFFFF).value
                    g = self.geometry()
                    left = int(g.left() * dpr)
                    top = int(g.top() * dpr)
                    right = int(g.right() * dpr)
                    bottom = int(g.bottom() * dpr)
                    m = int(self.RESIZE_MARGIN * dpr)
                    c = int(m * 2)
                    hit = 0
                    if x <= left + c and y <= top + c:
                        hit = 13  # HTTOPLEFT
                    elif x >= right - c and y <= top + c:
                        hit = 14  # HTTOPRIGHT
                    elif x <= left + c and y >= bottom - c:
                        hit = 16  # HTBOTTOMLEFT
                    elif x >= right - c and y >= bottom - c:
                        hit = 17  # HTBOTTOMRIGHT
                    elif x <= left + m:
                        hit = 10  # HTLEFT
                    elif x >= right - m:
                        hit = 11  # HTRIGHT
                    elif y <= top + m:
                        hit = 12  # HTTOP
                    elif y >= bottom - m:
                        hit = 15  # HTBOTTOM
                    if hit:
                        return True, hit
        except Exception:  # noqa: BLE001
            pass
        return False, 0

    # ------------------------------------------------------------ 关闭
    def closeEvent(self, event):
        if self._closing:
            event.accept()
            return
        self.watch_timer.stop()
        running = self.manager.bot_running()
        if running:
            ret = QMessageBox.question(
                self, "退出 AstroSwarm",
                "机器人服务仍在运行，关闭程序将停止全部服务。\n\n"
                "确定退出吗？",
                QMessageBox.Yes | QMessageBox.Cancel,
                QMessageBox.Yes,
            )
            if ret == QMessageBox.Cancel:
                event.ignore()
                self.watch_timer.start()
                return
        event.accept()
        self._begin_close(stop_all=running)

    def _begin_close(self, stop_all):
        self._closing = True
        self.hide()
        self.bg.shutdown()
        for st in self.tasks.active_states():
            self.tasks.cancel(st.task_id)
        if stop_all:
            self._stop_services_on_exit()
        else:
            QTimer.singleShot(80, self._really_quit)

    def _stop_services_on_exit(self):
        self._exit_dialog = QDialog()
        self._exit_dialog.setWindowTitle("AstroSwarm")
        self._exit_dialog.setModal(True)
        lay = QVBoxLayout(self._exit_dialog)
        lay.addWidget(QLabel("正在停止机器人服务，请稍候 ..."))
        bar = QProgressBar()
        bar.setRange(0, 0)
        lay.addWidget(bar)
        self._exit_dialog.show()
        self._exit_stop_started = time.time()
        self._exit_stop_tid = self.tasks.submit(
            "停止服务", "service", StartStopTask,
            payload={"start": False}, retryable=False, manager=self.manager,
        )
        self._exit_poll = QTimer(self)
        self._exit_poll.setInterval(250)
        self._exit_poll.timeout.connect(self._poll_exit_stop)
        self._exit_poll.start()

    def _poll_exit_stop(self):
        st = self.tasks.get(self._exit_stop_tid)
        if st is not None and st.status.value in ("success", "failed", "cancelled"):
            self._exit_poll.stop()
            # 二次清理：即使上面的停止任务异常，也确保机器人进程被终止后再退出
            try:
                self.manager.stop_all()
            except Exception as e:  # noqa: BLE001
                self.manager.log("退出前清理服务失败: " + str(e))
            QTimer.singleShot(120, self._really_quit)
        elif time.time() - self._exit_stop_started > 30:
            # 兜底：停止任务 30 秒仍未结束（如 taskkill 卡死），不再等待，
            # 直接退出；残留子进程由 Windows 退出作业（KILL_ON_JOB_CLOSE）兜底终止
            self._exit_poll.stop()
            self.manager.log("停止服务超时，强制执行退出清理")
            try:
                self.manager.stop_all()
            except Exception as e:  # noqa: BLE001
                self.manager.log("退出前清理服务失败: " + str(e))
            QTimer.singleShot(120, self._really_quit)

    def _really_quit(self):
        if self._exit_dialog is not None:
            self._exit_dialog.close()
            self._exit_dialog = None
        app = QApplication.instance()
        if app is not None:
            app.quit()
