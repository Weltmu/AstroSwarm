# -*- coding: utf-8 -*-
"""UI 冒烟测试：主题 QSS 生成、导航项、图标字体加载。"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if not os.environ.get("QBM_POINTER_DIR"):
    os.environ["QBM_POINTER_DIR"] = str(Path(tempfile.mkdtemp(prefix="qbm_test_ptr_")))

from qbotmanager.ui import theme as theme_mod  # noqa: E402


def test_qss():
    css_cyber = theme_mod.build_qss("glass", "liquid", "cyber")
    css_def = theme_mod.build_qss("glass", "frosted", "default")
    assert "#22D3EE" in css_cyber
    assert css_cyber != css_def
    css_slate = theme_mod.build_qss("glass", "default", "slate")
    assert css_slate != css_def
    css_swiss = theme_mod.build_qss("swiss", "default", "default")
    assert css_swiss and "QPushButton" in css_swiss
    print("OK ui smoke")


def test_wizard_background_panel():
    """首次安装向导：图片背景资源存在、内容收进半透明面板、离屏渲染不崩。"""
    from PySide6.QtWidgets import QApplication

    from qbotmanager.ui import theme as theme_mod
    from qbotmanager.ui.wizard import ASSET_BG, DeployWizard

    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(theme_mod.build_qss())
    assert ASSET_BG.is_file()
    wiz = DeployWizard()
    assert wiz.findChild(object, "wizardPanel") is not None
    assert not wiz._bg.isNull()
    pix = wiz.grab()
    assert not pix.isNull()
    wiz.close()
    print("OK wizard background panel")


def test_theme_switch_keeps_page():
    """切换 UI 质感/主题后，当前页（设置=9）不应跳回首页。"""
    from PySide6.QtWidgets import QApplication

    from qbotmanager.core.settings import Settings
    from qbotmanager.tasks.task_manager import TaskManager
    from qbotmanager.ui import theme as theme_mod
    from qbotmanager.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    tmp = Path(tempfile.mkdtemp(prefix="qbm_ui_"))
    s = Settings(tmp)
    s.ensure_dirs()
    s.bg_video_enabled = False
    s.bg_image_enabled = False
    s.save()
    tasks = TaskManager()
    win = MainWindow(s, tasks)
    win.switch_page("设置")
    app.processEvents()
    assert win.stack.currentIndex() == win._page_index["设置"]

    # 切质感框
    sp = win.pages[win._page_index["设置"]]
    idx = sp.glass_combo.findData("liquid")
    if idx >= 0:
        sp.glass_combo.setCurrentIndex(idx)
        app.processEvents()
    assert win.stack.currentIndex() == win._page_index["设置"]
    assert theme_mod.CURRENT_GLASS == "liquid"

    # 强制重建布局（模拟主题切换），当前页必须保持
    theme_mod.UI_LAYOUT = "topnav" if theme_mod.UI_LAYOUT == "sidebar" else "sidebar"
    win._apply_layout()
    app.processEvents()
    assert win.stack.currentIndex() == win._page_index["设置"]
    win.close()
    print("OK ui theme_switch_keeps_page")


def test_brain_page_agent_profile_controls():
    """AI 大脑页应包含智能体档案控件（开关/档案选择/唤醒词/视觉模型）。"""
    from PySide6.QtWidgets import QApplication

    from qbotmanager.core.settings import Settings
    from qbotmanager.tasks.task_manager import TaskManager
    from qbotmanager.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    tmp = Path(tempfile.mkdtemp(prefix="qbm_ui_"))
    s = Settings(tmp)
    s.ensure_dirs()
    s.bg_video_enabled = False
    s.bg_image_enabled = False
    s.save()
    tasks = TaskManager()
    win = MainWindow(s, tasks)
    bp = win.pages[6]
    assert hasattr(bp, "chk_agent_profile")
    assert hasattr(bp, "agent_profile_combo")
    assert hasattr(bp, "agent_wake_edit")
    assert hasattr(bp, "chk_wake_auto")
    assert hasattr(bp, "agent_owner_edit")
    assert hasattr(bp, "vision_url_edit")
    assert hasattr(bp, "vision_key_edit")
    win.close()
    print("OK ui brain_page_agent_profile_controls")


def test_brain_page_memory_and_kb_controls():
    """AI 大脑页有记忆时间线/导出/删除和本地知识库控件。"""
    from PySide6.QtWidgets import QApplication

    from qbotmanager.core.settings import Settings
    from qbotmanager.tasks.task_manager import TaskManager
    from qbotmanager.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    tmp = Path(tempfile.mkdtemp(prefix="qbm_memkb_"))
    s = Settings(tmp)
    s.ensure_dirs()
    s.bg_video_enabled = False
    s.bg_image_enabled = False
    s.save()
    tasks = TaskManager()
    win = MainWindow(s, tasks)
    app.processEvents()
    brain = win.pages[6]
    assert hasattr(brain, "memory_list")
    assert hasattr(brain, "btn_memory_export")
    assert hasattr(brain, "btn_memory_delete")
    assert hasattr(brain, "btn_kb_add")
    assert hasattr(brain, "kb_list")
    assert hasattr(brain, "btn_persona_guide"), "人设工坊应有「模板说明」入口"
    brain._refresh_kb_list()
    assert brain.kb_list.count() >= 1
    win.close()
    print("OK ui brain_page_memory_kb")


def test_brain_page_auto_restart_on_profile_change():
    """切换智能体档案并保存后，应自动提交重启 NoneBot 任务以载入新档案。"""
    from PySide6.QtWidgets import QApplication

    from qbotmanager.core.settings import Settings
    from qbotmanager.tasks.workers import RestartBotTask
    from qbotmanager.ui.pages.brain_page import BrainPage
    from qbotmanager.ui.pages.common import PageContext

    app = QApplication.instance() or QApplication([])
    tmp = Path(tempfile.mkdtemp(prefix="qbm_autore_"))
    s = Settings(tmp)
    s.ensure_dirs()
    s.save()
    submitted = []
    toasts = []

    class FakeTasks:
        def submit(self, *args, **kwargs):
            submitted.append((args, kwargs))

    ctx = PageContext(
        s, None, FakeTasks(),
        {"show_toast": lambda *a: toasts.append(a)})
    bp = BrainPage(ctx)
    assert bp.agent_profile_combo.findData("star_helper") >= 0
    idx = bp.agent_profile_combo.findData("liqinghan")
    assert idx >= 0
    bp.agent_profile_combo.setCurrentIndex(idx)
    bp.chk_agent_profile.setChecked(True)
    bp._save_config()

    assert submitted, "切换档案后保存应自动提交重启任务"
    name, category, task_cls = submitted[0][0]
    assert task_cls is RestartBotTask, submitted[0][0]
    assert "重启" in str(name)
    assert any("自动" in str(t) or "重启" in str(t) for t in toasts), toasts
    win = None
    bp.deleteLater()
    print("OK ui brain_page_auto_restart_on_profile_change")


def test_plugins_page_restricts_third_party_install():
    """插件页应限制任意第三方安装（PyPI/zip），只保留官方市场占位与本地列表。"""
    from PySide6.QtWidgets import QApplication, QLabel

    from qbotmanager.core.settings import Settings
    from qbotmanager.tasks.task_manager import TaskManager
    from qbotmanager.ui.pages.common import PageContext
    from qbotmanager.ui.pages.plugins_page import PluginsPage

    app = QApplication.instance() or QApplication([])
    tmp = Path(tempfile.mkdtemp(prefix="qbm_pluginui_"))
    s = Settings(tmp)
    s.ensure_dirs()
    s.save()
    ctx = PageContext(s, None, TaskManager(), {"show_toast": lambda *a: None})
    pp = PluginsPage(ctx)

    # 任意安装入口必须禁用或不存在
    if hasattr(pp, "btn_store"):
        assert not pp.btn_store.isEnabled(), "PyPI 安装按钮应禁用"
    if hasattr(pp, "store_edit"):
        assert not pp.store_edit.isEnabled(), "PyPI 包名输入应禁用"
    if hasattr(pp, "btn_zip"):
        assert not pp.btn_zip.isEnabled(), "zip 安装按钮应禁用"
    if hasattr(pp, "zip_edit"):
        assert not pp.zip_edit.isEnabled(), "zip 路径输入应禁用"

    # 官方市场面板存在
    texts = [lbl.text() for lbl in pp.findChildren(QLabel)]
    joined = "\n".join(texts)
    assert "插件商店" in joined, joined

    # 本地插件列表仍可用（重装依赖/打开目录等运维能力保留）
    assert pp.local_list is not None
    pp.deleteLater()
    print("OK ui plugins_page_restricts_third_party_install")


def test_plugins_page_market_panel_exists():
    """插件页应有官方市场面板（分类/列表/安装/刷新）与状态提示。"""
    from PySide6.QtWidgets import QApplication, QComboBox, QLabel, QListWidget, QPushButton

    from qbotmanager.core.settings import Settings
    from qbotmanager.tasks.task_manager import TaskManager
    from qbotmanager.ui.pages.common import PageContext
    from qbotmanager.ui.pages.plugins_page import PluginsPage

    app = QApplication.instance() or QApplication([])
    tmp = Path(tempfile.mkdtemp(prefix="qbm_mktui_"))
    s = Settings(tmp)
    s.ensure_dirs()
    s.save()
    ctx = PageContext(s, None, TaskManager(), {"show_toast": lambda *a: None})
    pp = PluginsPage(ctx)
    assert isinstance(pp.market_combo, QComboBox)
    assert isinstance(pp.market_list, QListWidget)
    assert isinstance(pp.btn_market_install, QPushButton)
    assert isinstance(pp.btn_market_refresh, QPushButton)
    assert isinstance(pp.market_status, QLabel)

    # 模拟市场加载结果：列表应渲染出条目且带插件 id（回归：addItem 返回值陷阱）
    from PySide6.QtCore import QPoint, Qt
    pp._on_market_loaded({"plugins": [{
        "id": "daily-motto", "name": "每日一言", "version": "1.0.0",
        "category": "功能扩展", "description": "每天一句",
        "url": "https://astroswarm.cn/plugins/daily-motto-1.0.0.zip", "sha256": "abc",
    }]})
    assert pp.market_list.count() == 1, pp.market_list.count()
    item = pp.market_list.item(0)
    assert item.data(Qt.UserRole) == "daily-motto"
    pp.deleteLater()
    print("OK ui plugins_page_market_panel_exists")


def test_plugins_page_developer_mode_enables_zip_install():
    """开发者模式开启后恢复第三方 zip/PyPI 安装入口，默认关闭时禁用。"""
    from PySide6.QtWidgets import QApplication

    from qbotmanager.core.settings import Settings
    from qbotmanager.tasks.task_manager import TaskManager
    from qbotmanager.ui.pages.common import PageContext
    from qbotmanager.ui.pages.plugins_page import PluginsPage

    app = QApplication.instance() or QApplication([])
    tmp = Path(tempfile.mkdtemp(prefix="qbm_devui_"))
    s = Settings(tmp)
    s.ensure_dirs()
    s.save()
    ctx = PageContext(s, None, TaskManager(), {"show_toast": lambda *a: None})
    pp = PluginsPage(ctx)
    assert not pp.btn_zip.isEnabled()
    assert not pp.btn_store.isEnabled()
    s.developer_mode = True
    pp._apply_mode()
    assert pp.btn_zip.isEnabled()
    assert pp.btn_store.isEnabled()
    s.developer_mode = False
    pp._apply_mode()
    assert not pp.btn_zip.isEnabled()
    pp.deleteLater()
    print("OK ui plugins_page_developer_mode_enables_zip_install")


def test_plugins_page_all_plugins_free():
    """插件已全部免费：带 tier=member 的历史条目也按免费渲染，页面不留购买入口。"""
    from PySide6.QtWidgets import QApplication

    from qbotmanager.core.settings import Settings
    from qbotmanager.tasks.task_manager import TaskManager
    from qbotmanager.ui.pages.common import PageContext
    from qbotmanager.ui.pages.plugins_page import PluginsPage

    app = QApplication.instance() or QApplication([])
    tmp = Path(tempfile.mkdtemp(prefix="qbm_gateui_"))
    s = Settings(tmp)
    s.ensure_dirs()
    s.save()
    ctx = PageContext(s, None, TaskManager(), {"show_toast": lambda *a: None})
    pp = PluginsPage(ctx)
    assert not hasattr(pp, "btn_market_buy"), "商店不该再有「购买能力包」按钮"
    assert not hasattr(pp, "_open_buy"), "商店不该再有跳转付款页的方法"
    pp._entitlements = {
        "plan": "none", "plan_expires_at": 0,
        "full": False, "owned_plugins": [],
    }
    pp._market_entries = {
        "free-a": {
            "id": "free-a", "name": "免费插件", "version": "1.0.0",
            "category": "功能扩展", "tier": "free", "description": "",
            "url": "https://astroswarm.cn/plugins/free-a.zip", "sha256": "abc",
        },
        "member-b": {
            "id": "member-b", "name": "会员插件", "version": "1.0.0",
            "category": "官方能力包", "tier": "member", "description": "",
            "url": "https://astroswarm.cn/plugins/member-b.zip", "sha256": "abc",
        },
    }
    pp._refresh_market_list()
    assert pp.market_list.count() == 2
    texts = [pp.market_list.item(i).text()
             for i in range(pp.market_list.count())]
    assert all("[免费]" in t for t in texts), texts
    assert not any("买断" in t for t in texts), texts
    for i in range(pp.market_list.count()):
        pp.market_list.setCurrentRow(i)
        app.processEvents()
    pp.market_list.setCurrentRow(0)
    app.processEvents()
    pp.deleteLater()
    print("OK ui plugins_all_free")


def test_account_window_top_left():
    """星群账号独立窗口：非模态、默认贴屏幕左上角、含登录控件。"""
    from PySide6.QtWidgets import QApplication

    from qbotmanager.core.settings import Settings
    from qbotmanager.tasks.task_manager import TaskManager
    from qbotmanager.ui.pages.account_window import AccountWindow
    from qbotmanager.ui.pages.common import PageContext

    app = QApplication.instance() or QApplication([])
    tmp = Path(tempfile.mkdtemp(prefix="qbm_acctwin_"))
    s = Settings(tmp)
    s.ensure_dirs()
    s.save()
    ctx = PageContext(s, None, TaskManager(), {"show_toast": lambda *a: None})
    win = AccountWindow(ctx)
    win.show()
    app.processEvents()
    assert win.x() <= 20 and win.y() <= 20, (win.x(), win.y())
    assert win.acct_email is not None
    assert win.acct_password is not None
    assert win.btn_account.text() in ("登录并同步", "退出账号")
    win.close()
    print("OK ui account_window_top_left")


def test_main_window_account_corner_entry():
    """主界面左上角有星群账号入口，点击打开个人中心窗口（贴左上角）。"""
    from PySide6.QtWidgets import QApplication

    from qbotmanager.core.settings import Settings
    from qbotmanager.tasks.task_manager import TaskManager
    from qbotmanager.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    tmp = Path(tempfile.mkdtemp(prefix="qbm_acctcorner_"))
    s = Settings(tmp)
    s.ensure_dirs()
    s.bg_video_enabled = False
    s.bg_image_enabled = False
    s.save()
    tasks = TaskManager()
    win = MainWindow(s, tasks)
    app.processEvents()
    assert hasattr(win, "btn_account_side")
    assert hasattr(win, "btn_account_top")
    assert hasattr(win, "btn_account_rail")
    win._open_account_window()
    app.processEvents()
    assert win._account_window is not None
    assert win._account_window.isVisible()
    assert win._account_window.x() <= 20 and win._account_window.y() <= 20
    win._account_window.close()
    win.close()
    print("OK ui main_window_account_corner")


def test_llbot_tutorial_bundled():
    """QQ 配置页有接入教程入口；内置教程含免责声明和四张截图。"""
    from PySide6.QtWidgets import QApplication

    from qbotmanager.core.settings import Settings
    from qbotmanager.tasks.task_manager import TaskManager
    from qbotmanager.ui.main_window import MainWindow
    from qbotmanager.ui.pages.tutorial_dialog import TUTORIAL_DIR, TutorialDialog

    assert (TUTORIAL_DIR / "index.html").is_file()
    pngs = sorted(TUTORIAL_DIR.glob("*.png"))
    assert len(pngs) == 4, [p.name for p in pngs]

    app = QApplication.instance() or QApplication([])
    tmp = Path(tempfile.mkdtemp(prefix="qbm_tut_"))
    s = Settings(tmp)
    s.ensure_dirs()
    s.bg_video_enabled = False
    s.bg_image_enabled = False
    s.save()
    tasks = TaskManager()
    win = MainWindow(s, tasks)
    app.processEvents()
    rp = win.pages[3]
    assert hasattr(rp, "btn_tutorial")
    assert "接入教程" in rp.btn_tutorial.text()

    dlg = TutorialDialog()
    dlg.show()
    app.processEvents()
    assert "#ffffff" in dlg.browser.styleSheet(), "教程窗口应强制白底（防深色主题黑底）"
    text = dlg.browser.toPlainText()
    assert "重要声明" in text
    assert "违反腾讯用户协议" in text
    assert "星群不提供内嵌式 QQ 通讯协议" in text
    assert "第 4 步" in text
    assert "常见问题" in text
    dlg.close()
    win.close()
    print("OK ui llbot_tutorial_bundled")


def test_settings_page_developer_mode_requires_confirm():
    """开发者模式开启前必须确认免责声明，拒绝则回弹。"""
    from PySide6.QtWidgets import QApplication, QMessageBox

    from qbotmanager.core.settings import Settings
    from qbotmanager.tasks.task_manager import TaskManager
    from qbotmanager.ui.pages.common import PageContext
    from qbotmanager.ui.pages.settings_page import SettingsPage

    app = QApplication.instance() or QApplication([])
    tmp = Path(tempfile.mkdtemp(prefix="qbm_devset_"))
    s = Settings(tmp)
    s.ensure_dirs()
    s.save()
    ctx = PageContext(s, None, TaskManager(), {"show_toast": lambda *a: None})
    sp = SettingsPage(ctx)
    assert hasattr(sp, "chk_developer_mode")
    orig = QMessageBox.question
    try:
        QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.No)
        sp.chk_developer_mode.setChecked(True)
        assert not sp.chk_developer_mode.isChecked(), "拒绝免责声明后应回弹"
        QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
        sp.chk_developer_mode.setChecked(True)
        assert sp.chk_developer_mode.isChecked(), "确认免责声明后应保持开启"
    finally:
        QMessageBox.question = orig
    sp.deleteLater()
    print("OK ui settings_page_developer_mode_requires_confirm")


def test_swiss_qss_styles_messagebox():
    """瑞士极简主题必须给弹窗（QMessageBox/QDialog）白底深字，否则关闭弹窗黑底黑字。"""
    import qbotmanager.ui.theme as theme_mod
    orig_style = theme_mod.UI_STYLE
    orig_cache = dict(theme_mod._QSS_CACHE)
    try:
        theme_mod.UI_STYLE = "swiss"
        theme_mod._QSS_CACHE.clear()
        qss = theme_mod.build_qss("swiss")
        assert "QMessageBox" in qss, "瑞士 QSS 缺少 QMessageBox 样式"
        assert "QDialog" in qss, "瑞士 QSS 缺少 QDialog 样式"
        assert "background: #FFFFFF" in qss, "弹窗应为白底"
        assert "color: #111111" in qss, "弹窗文字应为深色"
    finally:
        theme_mod.UI_STYLE = orig_style
        theme_mod._QSS_CACHE.clear()
        theme_mod._QSS_CACHE.update(orig_cache)
    print("OK ui swiss_qss_styles_messagebox")


def test_swiss_uses_selected_accent():
    """瑞士极简的强调色必须跟随当前皮肤，而不是写死红色。"""
    import qbotmanager.ui.theme as theme_mod
    orig_style = theme_mod.UI_STYLE
    orig_cache = dict(theme_mod._QSS_CACHE)
    try:
        theme_mod.UI_STYLE = "swiss"
        theme_mod._QSS_CACHE.clear()
        qss = theme_mod.build_qss("swiss", "default", "cyber")
        assert "#22D3EE" in qss, "瑞士 QSS 未使用当前皮肤强调色"
        assert "QPushButton#primary { background: #22D3EE" in qss, "瑞士 QSS 主按钮应使用当前强调色"
        assert "QPushButton#primary { background: #E30613" not in qss, "瑞士 QSS 主按钮不应再写死红色"
        assert "QPushButton#primary:hover" in qss, "瑞士 QSS 主按钮缺少 hover 态"
    finally:
        theme_mod.UI_STYLE = orig_style
        theme_mod._QSS_CACHE.clear()
        theme_mod._QSS_CACHE.update(orig_cache)
    print("OK ui swiss_uses_selected_accent")


def test_primary_disabled_uses_current_accent():
    """主按钮禁用态颜色必须跟随当前皮肤，不能写死默认蓝。"""
    import qbotmanager.ui.theme as theme_mod
    orig_style = theme_mod.UI_STYLE
    orig_cache = dict(theme_mod._QSS_CACHE)
    try:
        theme_mod.UI_STYLE = "glass"
        theme_mod._QSS_CACHE.clear()
        qss = theme_mod.build_qss("glass", "default", "midnight")
        assert "rgba(139,92,246,0.35)" in qss, "禁用态应使用当前强调色的半透明"
        assert "rgba(61,107,255,0.35)" not in qss, "禁用态不应写死默认蓝"
    finally:
        theme_mod.UI_STYLE = orig_style
        theme_mod._QSS_CACHE.clear()
        theme_mod._QSS_CACHE.update(orig_cache)
    print("OK ui primary_disabled_uses_current_accent")


def test_theme_tokens_contrast_and_sidebar():
    """TEXT_3 对比度提升；侧边栏为纯胶囊选中态，不再有左边框混搭。"""
    import qbotmanager.ui.theme as theme_mod
    assert theme_mod.TEXT_3 == "#7E8A9C", "TEXT_3 应提升对比度"
    assert theme_mod.THEMES["slate"]["TEXT_3"] == "#7E8A9C", "slate 皮肤 TEXT_3 应同步"
    orig_style = theme_mod.UI_STYLE
    orig_cache = dict(theme_mod._QSS_CACHE)
    try:
        theme_mod.UI_STYLE = "glass"
        theme_mod._QSS_CACHE.clear()
        qss = theme_mod.build_qss("glass")
        assert "border-left: 3px solid" not in qss, "侧边栏不应再有左边框"
        assert "QPushButton:focus" in qss, "按钮应有键盘焦点态"
    finally:
        theme_mod.UI_STYLE = orig_style
        theme_mod._QSS_CACHE.clear()
        theme_mod._QSS_CACHE.update(orig_cache)
    print("OK ui theme_tokens_contrast_and_sidebar")


def test_terminal_qss():
    """深空终端主题：等宽字体、实体面板、左侧竖线导航、强调色跟随皮肤。"""
    import qbotmanager.ui.theme as theme_mod
    orig_style = theme_mod.UI_STYLE
    orig_cache = dict(theme_mod._QSS_CACHE)
    try:
        theme_mod.UI_STYLE = "terminal"
        theme_mod._QSS_CACHE.clear()
        qss = theme_mod.build_qss("terminal", "terminal", "cyber")
        assert "Cascadia Mono" in qss, "终端主题应使用等宽字体"
        assert "background: #11151A" in qss, "终端主题面板应为实体深色"
        assert "border-left: 3px solid #22D3EE" in qss, "终端侧边栏选中态应为左侧荧光竖线"
        assert "QListWidget#rail" in qss, "终端主题应带左侧图标栏（rail）样式"
        assert "QPushButton#primary { background: #22D3EE" in qss, "主按钮应使用当前强调色"
        assert "QMessageBox" in qss, "终端主题缺少弹窗样式"
    finally:
        theme_mod.UI_STYLE = orig_style
        theme_mod._QSS_CACHE.clear()
        theme_mod._QSS_CACHE.update(orig_cache)
    print("OK ui terminal_qss")


def test_beginner_mode_nav():
    """小白模式默认隐藏高级页面，关闭后全部恢复，且首页隐藏飞书/纸飞机卡片。"""
    from PySide6.QtWidgets import QApplication

    from qbotmanager.core.settings import Settings
    from qbotmanager.tasks.task_manager import TaskManager
    from qbotmanager.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    tmp = Path(tempfile.mkdtemp(prefix="qbm_beginner_"))
    s = Settings(tmp)
    s.ensure_dirs()
    s.bg_video_enabled = False
    s.bg_image_enabled = False
    s.save()
    tasks = TaskManager()
    win = MainWindow(s, tasks)
    app.processEvents()

    assert s.beginner_mode is True
    assert win.nav_row_hidden("飞书"), "小白模式应隐藏飞书"
    assert win.nav_row_hidden("插件"), "小白模式应隐藏插件"
    if win._rail_rows:
        assert win.rail_list.isRowHidden(win._rail_rows["日志"]), "小白模式应隐藏日志"

    home = win.pages[0]
    feishu_card = home._cards_layout.itemAt(2).widget()
    assert feishu_card is not None and feishu_card.isHidden(), "小白模式首页应隐藏飞书卡"

    brain = win.pages[6]
    assert brain._agent_panel.isHidden(), "小白模式 AI 大脑应隐藏智能体档案"
    assert brain._workshop_panel.isHidden(), "小白模式 AI 大脑应隐藏人设工坊"
    assert brain._mem_panel.isHidden(), "小白模式 AI 大脑应隐藏 MCP"
    assert brain.chk_feishu.isHidden(), "小白模式 AI 大脑应隐藏飞书平台开关"

    sp = win.pages[win._page_index["设置"]]
    from qbotmanager.ui.widgets import ToggleSwitch
    assert isinstance(sp.chk_beginner_mode, ToggleSwitch), "小白模式应为椭圆滑块开关"
    assert not hasattr(sp, "chk_nonebot_enabled"), "NoneBot 开关应已移除"
    assert hasattr(sp, "btn_account"), "星群账号应保留单一登录/退出按钮"
    assert not hasattr(sp, "btn_sync"), "手动同步按钮应已移除"
    assert win._account_sync_timer.interval() == 3600000, "激活状态应每小时自动同步"
    assert win._device_check_timer.interval() == 900000, "被踢检测应每 15 分钟执行"

    # 通过设置页滑块走完整 UI 链路切换，验证点击后立即生效
    sp.chk_beginner_mode.setChecked(False)
    app.processEvents()
    assert not win.nav_row_hidden("飞书"), "关闭小白模式应显示飞书"
    assert not win.nav_row_hidden("插件"), "关闭小白模式应显示插件"
    assert not feishu_card.isHidden(), "关闭小白模式首页应显示飞书卡"
    assert not brain._agent_panel.isHidden(), "关闭小白模式 AI 大脑应显示档案"
    assert not brain._workshop_panel.isHidden(), "关闭小白模式 AI 大脑应显示人设工坊"
    assert not brain._mem_panel.isHidden(), "关闭小白模式 AI 大脑应显示 MCP"
    assert not brain.chk_feishu.isHidden(), "关闭小白模式 AI 大脑应显示飞书平台开关"

    sp.chk_beginner_mode.setChecked(True)
    app.processEvents()
    assert win.nav_row_hidden("飞书"), "重新开启小白模式应再次隐藏飞书"
    assert feishu_card.isHidden(), "重新开启小白模式首页应隐藏飞书卡"

    win.close()
    print("OK ui beginner_mode_nav")


def test_run_page_reverse_ws_panel():
    """QQ 页提供反向 WS：默认反向模式、地址可直接复制、模式切换面板联动。"""
    from PySide6.QtWidgets import QApplication

    from qbotmanager.core.settings import Settings
    from qbotmanager.tasks.task_manager import TaskManager
    from qbotmanager.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    tmp = Path(tempfile.mkdtemp(prefix="qbm_reverse_ws_"))
    s = Settings(tmp)
    s.ensure_dirs()
    s.bg_video_enabled = False
    s.bg_image_enabled = False
    s.qq_channel = "onebot"
    s.qq_onebot_mode = "reverse"
    s.qq_onebot_listen_host = "127.0.0.1"
    s.save()
    tasks = TaskManager()
    win = MainWindow(s, tasks)
    app.processEvents()

    rp = win.pages[3]
    assert rp.combo_onebot_mode.currentData() == "reverse"
    assert not rp.panel_reverse.isHidden(), "默认应显示反向 WS 面板"
    assert rp.panel_forward.isHidden(), "默认应隐藏正向 WS 面板"
    assert "12111" in rp.edit_reverse_port.text()
    assert rp.edit_reverse_url.text() == "ws://127.0.0.1:12111/onebot/v11/ws"
    assert rp.btn_copy_reverse_url.text() == "复制地址"

    # 切到正向：反向面板隐藏，正向字段保留
    rp.combo_onebot_mode.setCurrentIndex(1)
    app.processEvents()
    assert rp.panel_reverse.isHidden(), "正向模式应隐藏反向面板"
    assert not rp.panel_forward.isHidden(), "正向模式应显示正向面板"
    assert rp.edit_onebot_host.text() == "127.0.0.1"

    # 监听地址改为 0.0.0.0 时，给协议端粘贴的地址仍是本机可连地址
    rp.combo_onebot_mode.setCurrentIndex(0)
    rp.edit_onebot_listen_host.setText("0.0.0.0")
    assert rp.edit_reverse_url.text() == "ws://127.0.0.1:12111/onebot/v11/ws"

    win.close()
    print("OK ui run_page_reverse_ws")


def test_free_tier_pay_entries_exist():
    """首页与微信页在免费版下应提供「解锁微信」付费入口。"""
    import tempfile
    from pathlib import Path

    from PySide6.QtWidgets import QApplication

    from qbotmanager.core.settings import Settings
    from qbotmanager.tasks.task_manager import TaskManager
    from qbotmanager.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    tmp = Path(tempfile.mkdtemp(prefix="qbm_pay_"))
    s = Settings(tmp)
    s.ensure_dirs()
    s.bg_video_enabled = False
    s.bg_image_enabled = False
    s.save()
    # 隔离本机真实授权：测试环境固定为免费版（本机账号已是永久，直接读会误判）
    from qbotmanager.core import license as lic
    orig_license_file = lic.license_file
    lic.license_file = lambda: tmp / "license.json"
    tasks = TaskManager()
    win = MainWindow(s, tasks)
    app.processEvents()

    home = win.pages[0]
    assert hasattr(home, "wx_pay_btn"), "首页缺少解锁微信按钮"
    assert home.wx_pay_btn.text() == "解锁微信"

    wechat = next(
        (p for p in win.pages if type(p).__name__ == "WechatPage"), None
    )
    assert wechat is not None and hasattr(wechat, "btn_pay"), "微信页缺少付费解锁按钮"
    assert "解锁微信" in wechat.btn_pay.text()

    sp = win.pages[win._page_index["设置"]]
    assert sp.info_labels["license_status"].text() == "免费版（仅 QQ 通道）"
    assert "机器码" not in sp.info_labels["license_status"].toolTip()

    lic.license_file = orig_license_file
    win.close()
    print("OK ui free_tier_pay_entries")


def test_beginner_toggle_survives_appearance_error():
    """外观应用抛异常时，小白模式切换仍必须生效（修复按钮“不好使”）。"""
    from PySide6.QtWidgets import QApplication

    from qbotmanager.core.settings import Settings
    from qbotmanager.tasks.task_manager import TaskManager
    from qbotmanager.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    tmp = Path(tempfile.mkdtemp(prefix="qbm_beginner_err_"))
    s = Settings(tmp)
    s.ensure_dirs()
    s.bg_video_enabled = False
    s.bg_image_enabled = False
    s.beginner_mode = True
    s.save()
    tasks = TaskManager()
    win = MainWindow(s, tasks)
    app.processEvents()
    sp = win.pages[win._page_index["设置"]]

    def boom():
        raise RuntimeError("appearance boom")

    sp.ctx.apply_appearance = boom
    sp.chk_beginner_mode.setChecked(False)
    app.processEvents()
    assert s.beginner_mode is False, "外观异常时小白模式仍应保存关闭状态"
    assert not win.nav_row_hidden("插件"), "外观异常时高级页面仍应显示"

    sp.chk_beginner_mode.setChecked(True)
    app.processEvents()
    assert s.beginner_mode is True, "外观异常时重新开启小白模式仍应保存"
    assert win.nav_row_hidden("插件"), "外观异常时重新开启仍应隐藏高级页面"
    win.close()
    print("OK ui beginner_toggle_survives_appearance_error")


def test_toggle_switch_click_area():
    """小白模式滑块：真实鼠标点击右侧滑块必须能切换（防 hitButton 只认左侧小方框）。"""
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    from qbotmanager.ui.widgets import ToggleSwitch

    app = QApplication.instance() or QApplication([])
    sw = ToggleSwitch("小白模式")
    sw.resize(220, 28)
    sw.show()
    app.processEvents()
    assert sw.isChecked() is False
    # 点击右侧滑块中心（可见开关的位置，而不是左侧隐藏的小方框）
    QTest.mouseClick(sw, Qt.LeftButton, pos=sw.rect().center() + QPoint(80, 0))
    app.processEvents()
    assert sw.isChecked() is True, "点击滑块本体应能打开小白模式"
    QTest.mouseClick(sw, Qt.LeftButton, pos=sw.rect().center() + QPoint(80, 0))
    app.processEvents()
    assert sw.isChecked() is False, "再次点击滑块本体应能关闭小白模式"
    sw.close()
    print("OK ui toggle_switch_click_area")


def test_access_page_lists_all_channels():
    """接入页：四个通道各一行、状态带文字、未开放的禁用，可展开就地配置。"""
    from PySide6.QtWidgets import QApplication

    from qbotmanager.core.settings import Settings
    from qbotmanager.tasks.task_manager import TaskManager
    from qbotmanager.ui.main_window import MainWindow
    from qbotmanager.ui.pages.channel_panels import QQChannelPanel, WeChatChannelPanel

    app = QApplication.instance() or QApplication([])
    tmp = Path(tempfile.mkdtemp(prefix="qbm_access_"))
    s = Settings(tmp)
    s.ensure_dirs()
    s.bg_video_enabled = False
    s.bg_image_enabled = False
    s.save()
    win = MainWindow(s, TaskManager())
    win.switch_page("接入")
    app.processEvents()
    ap = win.pages[1]
    collapsed_min = ap.scroll.widget().minimumHeight()
    assert set(ap._rows) == {"qq", "wechat", "feishu", "telegram"}, ap._rows.keys()

    # 未开放的通道：按钮禁用且写着「规划中」，不做成灰的可点按钮
    for key in ("feishu", "telegram"):
        btn = ap._rows[key][1]
        assert btn.text() == "规划中" and not btn.isEnabled(), key

    # 状态必须带文字（不能只有颜色）
    for key in ("qq", "wechat"):
        badge = ap._rows[key][0]
        text = badge.label.text()
        assert text and ("·" in text), (key, text)
        assert any(word in text for word in
                   ("运行中", "已停止", "未连接", "未登录", "已连接", "未安装", "解锁", "规划中")), text

    # 「去配置」跳到真实通道页
    ap._rows["qq"][1].click()
    app.processEvents()
    assert not ap._bodies["qq"].isHidden(), "点「配置」应就地展开，而不是跳页"
    assert isinstance(ap._panels["qq"], QQChannelPanel)
    assert ap._panels["qq"].edit_reverse_url.text() == "ws://127.0.0.1:12111/onebot/v11/ws"
    assert ap._rows["qq"][1].text() == "收起"

    # 展开区里的「打开完整页」才跳页（QQ/微信 独立页仍在）
    ap._links["qq"].click()
    app.processEvents()
    assert win.stack.currentIndex() == win._page_index["QQ"]

    ap._rows["wechat"][1].click()
    app.processEvents()
    assert not ap._bodies["wechat"].isHidden(), "微信也应能就地展开"
    assert isinstance(ap._panels["wechat"], WeChatChannelPanel)
    assert ap._bodies["qq"].isHidden(), "一次只展开一条通道"
    ap._links["wechat"].click()
    app.processEvents()
    assert win.stack.currentIndex() == win._page_index["微信"]

    # 再点一次收起：展开区高度必须归零、滚动内容回到基线高度
    # （只 setVisible(False) 的话 Qt 会留着展开时的 sizeHint，行间出现大片空白）
    ap._rows["wechat"][1].click()
    app.processEvents()
    assert ap._bodies["wechat"].isHidden() and ap._bodies["wechat"].height() == 0
    assert ap.scroll.widget().minimumHeight() == collapsed_min

    # 小白模式：接入页留着当入口，微信/QQ 页面收起来
    assert "接入" not in MainWindow.ADVANCED_PAGES
    for name in ("微信", "QQ"):
        assert name in MainWindow.ADVANCED_PAGES, name
    win.deleteLater()
    print("OK ui access_page")


def test_brain_page_ai_memory_block():
    """AI 大脑页的内置 AI 全局记忆：能列出、能删一条（留备份）、能清空全局。"""
    from PySide6.QtWidgets import QApplication

    from qbotmanager.core import ai_config, ai_memory
    from qbotmanager.core.settings import Settings
    from qbotmanager.tasks.task_manager import TaskManager
    from qbotmanager.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    tmp = Path(tempfile.mkdtemp(prefix="qbm_aimemui_"))
    s = Settings(tmp)
    s.ensure_dirs()
    s.bg_video_enabled = False
    s.bg_image_enabled = False
    s.save()
    # 先造一份记忆（含全局与用户两组），再让页面去读
    ai_memory._save(s, {"global": ["他怕辣", "喜欢美式咖啡"],
                        "users": {"10001": ["住杭州"]}})

    win = MainWindow(s, TaskManager())
    win.switch_page("AI 大脑")
    app.processEvents()
    bp = win.pages[6]
    bp._refresh_ai_memory()
    app.processEvents()

    texts = [bp.ai_mem_list.item(i).text() for i in range(bp.ai_mem_list.count())]
    assert any("他怕辣" in x for x in texts), texts
    assert any("用户 10001" in x for x in texts), texts
    assert "共 3 条" in bp.ai_mem_tip.text(), bp.ai_mem_tip.text()

    # 选中一条删掉（确认框用 monkeypatch 直接放行，避免弹窗卡住测试）
    from PySide6.QtWidgets import QMessageBox

    orig = QMessageBox.question
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
    try:
        idx = next(i for i, t in enumerate(texts) if "他怕辣" in t)
        bp.ai_mem_list.setCurrentRow(idx)
        bp._delete_ai_memory()
        app.processEvents()
    finally:
        QMessageBox.question = orig

    left = ai_memory.load(s)
    assert left["global"] == ["喜欢美式咖啡"], left
    assert left["users"] == {"10001": ["住杭州"]}, "删全局不能动用户记忆"
    backups = list(ai_config.memory_file(s).parent.glob("aichat_memory.json.bak.*"))
    assert backups, "改动前必须留备份"

    # 清空全局（用户记忆保留）
    orig = QMessageBox.question
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
    try:
        bp._clear_ai_memory()
        app.processEvents()
    finally:
        QMessageBox.question = orig
    after = ai_memory.load(s)
    assert after["global"] == [] and after["users"] == {"10001": ["住杭州"]}

    win.deleteLater()
    print("OK ui brain_ai_memory")


def test_nav_groups_match_console():
    """侧栏分组与控制台一致（运行 / 能力 / 系统），「全局管理」是真页面不是占位。"""
    from PySide6.QtWidgets import QApplication

    from qbotmanager.core.settings import Settings
    from qbotmanager.tasks.task_manager import TaskManager
    from qbotmanager.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    tmp = Path(tempfile.mkdtemp(prefix="qbm_nav_"))
    s = Settings(tmp)
    s.ensure_dirs()
    s.bg_video_enabled = False
    s.bg_image_enabled = False
    s.beginner_mode = False
    s.save()
    win = MainWindow(s, TaskManager())
    app.processEvents()

    assert [t for t, _items in MainWindow.NAV_GROUPS] == ["运行", "能力", "系统"]
    assert [n for _t, items in MainWindow.NAV_GROUPS for n in items] == list(MainWindow.PAGE_ORDER)
    # 组内顺序与控制台一致：能力组是「AI 大脑 / 插件」，系统组第一项是「全局管理」
    assert MainWindow.NAV_GROUPS[1][1] == ("AI 大脑", "插件")
    assert MainWindow.NAV_GROUPS[2][1][0] == "全局管理"

    # 页面下标必须与 PAGE_ORDER 一一对应（加页面时最容易被写歪的地方）
    assert len(win.pages) == len(MainWindow.PAGE_ORDER)
    for i, name in enumerate(MainWindow.PAGE_ORDER):
        assert win._page_index[name] == i, name

    win.switch_page("全局管理")
    app.processEvents()
    assert win.stack.currentIndex() == win._page_index["全局管理"]
    assert win.nav_lists[2].currentRow() == 0, "选中行要跟着切到系统组第一项"

    # 一次只有一组能高亮
    win.nav_lists[0].setCurrentRow(0)
    app.processEvents()
    assert win.nav_lists[2].currentRow() == -1, "切回运行组后系统组不该还高亮"
    assert win.stack.currentIndex() == win._page_index["首页"]
    win.deleteLater()
    print("OK ui nav_groups")


def test_services_page_controls():
    """全局管理页：机器人开关 + DSH 状态行 + 运维细节（端口 / 目录）默认收起。"""
    from PySide6.QtWidgets import QApplication

    from qbotmanager.core.settings import Settings
    from qbotmanager.tasks.task_manager import TaskManager
    from qbotmanager.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    tmp = Path(tempfile.mkdtemp(prefix="qbm_services_"))
    s = Settings(tmp)
    s.ensure_dirs()
    s.bg_video_enabled = False
    s.bg_image_enabled = False
    s.save()
    win = MainWindow(s, TaskManager())
    win.switch_page("全局管理")
    app.processEvents()
    sp = win.pages[win._page_index["全局管理"]]

    assert hasattr(sp, "bot_badge") and hasattr(sp, "btn_bot")
    assert hasattr(sp, "dsh_badge")
    assert sp.btn_bot.text() in ("启动", "重启")
    assert "·" in sp.bot_badge.label.text() or sp.bot_badge.label.text(), sp.bot_badge.label.text()

    # 运维细节默认收起；展开后端口 / 目录必须是真值，不写死
    assert not sp.details.isVisibleTo(sp), "运维细节默认要收起"
    assert sp.detail_labels["port"].text() == str(s.nonebot_port)
    assert str(s.logs_dir) in sp.detail_labels["logs_dir"].text()
    assert str(s.bot_dir) in sp.detail_labels["bot_dir"].text()
    assert sp.detail_labels["version"].text().startswith("v")
    sp._toggle_details()
    assert sp.details.isVisibleTo(sp) and "▴" in sp.btn_fold.text()
    sp._toggle_details()
    assert not sp.details.isVisibleTo(sp)
    win.deleteLater()
    print("OK ui services_page")


def test_logs_export_writes_file():
    """日志页：能导出单份日志，也能把「全部」日志尾部拼成一份。"""
    import time as _time

    from PySide6.QtWidgets import QApplication, QFileDialog

    from qbotmanager.core.settings import Settings
    from qbotmanager.tasks.task_manager import TaskManager
    from qbotmanager.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    tmp = Path(tempfile.mkdtemp(prefix="qbm_logs_"))
    s = Settings(tmp)
    s.ensure_dirs()
    s.bg_video_enabled = False
    s.bg_image_enabled = False
    s.save()
    (s.logs_dir / "nonebot.log").write_text("机器人日志一行\n", encoding="utf-8")
    (s.logs_dir / "deploy.log").write_text("部署日志一行\n", encoding="utf-8")

    win = MainWindow(s, TaskManager())
    win.switch_page("日志")
    app.processEvents()
    lp = win.pages[win._page_index["日志"]]
    assert lp.btn_export.isEnabled()

    def _export(label, dest):
        orig = QFileDialog.getSaveFileName
        QFileDialog.getSaveFileName = staticmethod(
            lambda *a, **k: (str(dest), "日志文件 (*.log)"))
        try:
            lp.src_combo.setCurrentText(label)
            lp._export_logs()
        finally:
            QFileDialog.getSaveFileName = orig
        for _ in range(300):
            if dest.exists():
                break
            _time.sleep(0.02)
        assert dest.exists(), f"{label} 导出没落盘：{dest}"

    one = tmp / "one.log"
    _export("NoneBot", one)
    assert "机器人日志一行" in one.read_text(encoding="utf-8")
    assert "部署日志一行" not in one.read_text(encoding="utf-8")

    every = tmp / "every.log"
    _export("全部", every)
    text = every.read_text(encoding="utf-8")
    assert "机器人日志一行" in text and "部署日志一行" in text
    assert "===== nonebot" in text and "===== deploy" in text
    win.deleteLater()
    print("OK ui logs_export")


def test_message_center_shows_scene_and_room():
    """消息中心：标题能区分「QQ 群 12345 / QQ 好友 67890」，并给出条数与会话总数。"""
    import json as _json

    from PySide6.QtWidgets import QApplication

    from qbotmanager.core.settings import Settings
    from qbotmanager.tasks.task_manager import TaskManager
    from qbotmanager.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    tmp = Path(tempfile.mkdtemp(prefix="qbm_msgcenter_"))
    s = Settings(tmp)
    s.ensure_dirs()
    s.bg_video_enabled = False
    s.bg_image_enabled = False
    s.save()
    ctx_file = s.bot_dir / "data" / "ai" / "aichat_context.json"
    ctx_file.parent.mkdir(parents=True, exist_ok=True)
    ctx_file.write_text(_json.dumps({
        "group_12345": [{"content": "群里说的话"}],
        "67890": [{"content": "私聊里说的话"}],
    }, ensure_ascii=False), encoding="utf-8")

    win = MainWindow(s, TaskManager())
    win.switch_page("消息中心")
    app.processEvents()
    mc = win.pages[win._page_index["消息中心"]]
    mc.refresh()
    app.processEvents()
    texts = [mc.list.item(i).text() for i in range(mc.list.count())]
    assert any("QQ 群 12345" in t for t in texts), texts
    assert any("QQ 好友 67890" in t for t in texts), texts
    assert any("1 条" in t for t in texts), texts
    assert "共 2 个会话" in mc.stat_label.text(), mc.stat_label.text()
    win.deleteLater()
    print("OK ui message_center")


if __name__ == "__main__":
    test_qss()
    test_theme_switch_keeps_page()
    test_brain_page_agent_profile_controls()
    test_brain_page_memory_and_kb_controls()
    test_brain_page_auto_restart_on_profile_change()
    test_plugins_page_restricts_third_party_install()
    test_plugins_page_market_panel_exists()
    test_plugins_page_developer_mode_enables_zip_install()
    test_plugins_page_all_plugins_free()
    test_account_window_top_left()
    test_main_window_account_corner_entry()
    test_llbot_tutorial_bundled()
    test_settings_page_developer_mode_requires_confirm()
    test_swiss_qss_styles_messagebox()
    test_swiss_uses_selected_accent()
    test_primary_disabled_uses_current_accent()
    test_theme_tokens_contrast_and_sidebar()
    test_terminal_qss()
    test_beginner_mode_nav()
    test_beginner_toggle_survives_appearance_error()
    test_toggle_switch_click_area()
    test_run_page_reverse_ws_panel()
    test_free_tier_pay_entries_exist()
    test_access_page_lists_all_channels()
    test_brain_page_ai_memory_block()
    test_nav_groups_match_console()
    test_services_page_controls()
    test_logs_export_writes_file()
    test_message_center_shows_scene_and_room()
