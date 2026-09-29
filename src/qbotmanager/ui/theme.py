"""AstroSwarm 星群视觉主题：颜色令牌 + 全局 QSS。克制、深色、玻璃质感。"""

# ---- 颜色令牌（单一强调色：深蓝）----
ACCENT = "#3D6BFF"
ACCENT_HOVER = "#5A85FF"
ACCENT_ACTIVE = "#2F5CE8"
ACCENT_SOFT = "rgba(61,107,255,0.16)"
ACCENT_GLOW = "rgba(61,107,255,0.45)"

BG_0 = "#0B0E14"
BG_1 = "#111722"
PANEL = "rgba(17,22,34,0.62)"
PANEL_STRONG = "rgba(19,26,40,0.78)"
PANEL_SOLID = "#141A26"
BORDER_LIGHT = "rgba(255,255,255,0.08)"
BORDER_STRONG = "rgba(255,255,255,0.14)"

TEXT = "#F2F5FA"
TEXT_2 = "#A7B1C2"
TEXT_3 = "#7E8A9C"

SUCCESS = "#34D399"
DANGER = "#F87171"
WARN = "#FBBF24"
INFO = "#60A5FA"
NEUTRAL = "#8A94A6"

RADIUS = 12
RADIUS_SM = 8
WINDOW_RADIUS = 14       # 主窗口四角圆角半径（平滑圆角，非区域遮罩）

FONT_FAMILY = '"Microsoft YaHei UI", "Segoe UI", sans-serif'
MONO_FAMILY = '"Cascadia Mono", Consolas, monospace'

STATUS_COLORS = {
    "running": SUCCESS,
    "connected": SUCCESS,
    "success": SUCCESS,
    "ok": SUCCESS,
    "stopped": DANGER,
    "failed": DANGER,
    "error": DANGER,
    "warning": WARN,
    "warn": WARN,
    "pending": WARN,
    "info": INFO,
    "unknown": NEUTRAL,
    "idle": NEUTRAL,
}

# ---- 皮肤主题（多套强调色） ----
THEMES = {
    "default": {
        "name": "深邃蓝",
        "ACCENT": "#3D6BFF",
        "ACCENT_HOVER": "#5A85FF",
        "ACCENT_ACTIVE": "#2F5CE8",
        "ACCENT_SOFT": "rgba(61,107,255,0.16)",
        "ACCENT_GLOW": "rgba(61,107,255,0.45)",
    },
    "midnight": {
        "name": "暗夜紫",
        "ACCENT": "#8B5CF6",
        "ACCENT_HOVER": "#A78BFA",
        "ACCENT_ACTIVE": "#7C3AED",
        "ACCENT_SOFT": "rgba(139,92,246,0.18)",
        "ACCENT_GLOW": "rgba(139,92,246,0.45)",
    },
    "cyber": {
        "name": "赛博青",
        "ACCENT": "#22D3EE",
        "ACCENT_HOVER": "#67E8F9",
        "ACCENT_ACTIVE": "#0891B2",
        "ACCENT_SOFT": "rgba(34,211,238,0.15)",
        "ACCENT_GLOW": "rgba(34,211,238,0.40)",
    },
    "sunset": {
        "name": "暖阳橙",
        "ACCENT": "#F59E0B",
        "ACCENT_HOVER": "#FBBF24",
        "ACCENT_ACTIVE": "#D97706",
        "ACCENT_SOFT": "rgba(245,158,11,0.15)",
        "ACCENT_GLOW": "rgba(245,158,11,0.40)",
    },
    "forest": {
        "name": "薄荷绿",
        "ACCENT": "#34D399",
        "ACCENT_HOVER": "#6EE7B7",
        "ACCENT_ACTIVE": "#059669",
        "ACCENT_SOFT": "rgba(52,211,153,0.15)",
        "ACCENT_GLOW": "rgba(52,211,153,0.40)",
    },
    "slate": {
        "name": "深空绿（新色板）",
        "ACCENT": "#22C55E",
        "ACCENT_HOVER": "#4ADE80",
        "ACCENT_ACTIVE": "#16A34A",
        "ACCENT_SOFT": "rgba(34,197,94,0.16)",
        "ACCENT_GLOW": "rgba(34,197,94,0.42)",
        "TEXT": "#F8FAFC",
        "TEXT_2": "#94A3B8",
        "TEXT_3": "#7E8A9C",
    },
}

# ---- UI 框玻璃质感（default=原样 / liquid=液态玻璃 / frosted=颗粒磨砂） ----
GLASS = {
    "default": {
        "PANEL": PANEL,
        "PANEL_STRONG": PANEL_STRONG,
        "PANEL_SOLID": PANEL_SOLID,
        "BORDER_LIGHT": BORDER_LIGHT,
        "BORDER_STRONG": BORDER_STRONG,
    },
    "liquid": {
        "PANEL": "qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 rgba(255,255,255,0.14), "
                 "stop:0.45 rgba(17,22,34,0.42), stop:1 rgba(10,14,22,0.60))",
        "PANEL_STRONG": "qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 rgba(255,255,255,0.17), "
                        "stop:0.45 rgba(19,26,40,0.52), stop:1 rgba(10,14,22,0.74))",
        "PANEL_SOLID": "#141A26",
        "BORDER_LIGHT": "rgba(255,255,255,0.18)",
        "BORDER_STRONG": "rgba(255,255,255,0.32)",
    },
    "frosted": {
        "PANEL": "qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 rgba(255,255,255,0.10), "
                 "stop:0.5 rgba(17,22,34,0.56), stop:1 rgba(255,255,255,0.06))",
        "PANEL_STRONG": "qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 rgba(255,255,255,0.12), "
                        "stop:0.5 rgba(19,26,40,0.68), stop:1 rgba(255,255,255,0.08))",
        "PANEL_SOLID": "#151B27",
        "BORDER_LIGHT": "rgba(255,255,255,0.10)",
        "BORDER_STRONG": "rgba(255,255,255,0.16)",
    },
    "terminal": {
        "PANEL": "#11151A",
        "PANEL_STRONG": "#141A21",
        "PANEL_SOLID": "#0E1217",
        "BORDER_LIGHT": "rgba(255,255,255,0.10)",
        "BORDER_STRONG": "rgba(255,255,255,0.18)",
    },
}

CURRENT_GLASS = "default"  # GlassPanel 自绘时读取的当前质感模式
UI_OPACITY = 0.70          # UI 框透明度（GlassPanel 自绘读取，0.0-1.0）
SUPPRESS_BACKDROP_REFRESH = False  # 主题切换期间暂停玻璃面板抓屏，切完统一刷新

# ---- UI 主题（每个主题 = 布局 + 导航 + 配色 + 质感 的整体方案） ----
UI_THEMES = {
    "glass": {"name": "极光玻璃", "style": "glass", "layout": "sidebar"},
    "swiss": {"name": "瑞士极简", "style": "swiss", "layout": "topnav"},
    "terminal": {"name": "深空终端", "style": "terminal", "layout": "rail"},
}
UI_STYLE = "glass"     # glass / swiss（决定 QSS 与自绘风格）
UI_LAYOUT = "sidebar"  # sidebar / topnav（决定导航布局）
UI_FRAME_COLOR = "#FFFFFF"  # UI 框颜色（瑞士极简卡片底色，默认白）

TOKEN_KEYS = (
    "ACCENT", "ACCENT_HOVER", "ACCENT_ACTIVE", "ACCENT_SOFT", "ACCENT_GLOW",
    "BG_0", "BG_1", "TEXT", "TEXT_2", "TEXT_3",
    "PANEL", "PANEL_STRONG", "PANEL_SOLID", "BORDER_LIGHT", "BORDER_STRONG",
)

_QSS_CACHE: dict = {}


def status_color(key: str) -> str:
    return STATUS_COLORS.get((key or "").lower(), NEUTRAL)


def rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


def _build_qss_inner() -> str:
    return f"""
* {{
    font-family: {FONT_FAMILY};
    outline: none;
}}
QPushButton:focus {{
    border-color: {ACCENT};
}}
QListWidget:focus {{
    border-color: {ACCENT};
}}
QCheckBox:focus::indicator {{
    border-color: {ACCENT};
}}
QMainWindow, QWidget {{
    background: transparent;
    color: {TEXT};
}}
QLabel {{
    background: transparent;
    color: {TEXT};
}}
QLabel#pageTitle {{
    font-size: 22px;
    font-weight: 600;
    color: {TEXT};
    letter-spacing: 0.5px;
}}
QLabel#pageSub {{
    font-size: 13px;
    color: {TEXT_2};
}}
QLabel#sectionTitle {{
    font-size: 15px;
    font-weight: 600;
    color: {TEXT};
}}
QLabel#caption {{
    font-size: 12px;
    color: {TEXT_3};
}}
QLabel#value {{
    font-size: 14px;
    font-weight: 600;
    color: {TEXT};
}}

/* ---- 玻璃面板 ---- */
QFrame#glass {{
    background: {PANEL};
    border: 1px solid {BORDER_LIGHT};
    border-top: 1px solid {BORDER_STRONG};
    border-radius: {RADIUS}px;
}}
QFrame#glassStrong {{
    background: {PANEL_STRONG};
    border: 1px solid {BORDER_LIGHT};
    border-top: 1px solid {BORDER_STRONG};
    border-radius: {RADIUS}px;
}}

/* ---- 按钮 ---- */
QPushButton {{
    background: rgba(255,255,255,0.06);
    border: 1px solid {BORDER_LIGHT};
    border-radius: 8px;
    color: {TEXT};
    padding: 7px 14px;
    font-size: 13px;
}}
QPushButton:hover {{
    background: rgba(255,255,255,0.10);
    border-color: {BORDER_STRONG};
}}
QPushButton:pressed {{
    background: rgba(255,255,255,0.05);
}}
QPushButton:disabled {{
    color: {TEXT_3};
    background: rgba(255,255,255,0.03);
    border-color: rgba(255,255,255,0.04);
}}
QPushButton#primary {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {ACCENT}, stop:1 {ACCENT_ACTIVE});
    border: none;
    color: white;
    font-weight: 600;
    padding: 8px 18px;
}}
QPushButton#primary:hover {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {ACCENT_HOVER}, stop:1 {ACCENT});
}}
QPushButton#primary:disabled {{
    background: {rgba(ACCENT, 0.35)};
    color: rgba(255,255,255,0.7);
}}
QPushButton#danger {{
    background: rgba(248,113,113,0.12);
    border: 1px solid rgba(248,113,113,0.35);
    color: #FCA5A5;
}}
QPushButton#danger:hover {{
    background: rgba(248,113,113,0.22);
}}
QPushButton#ghost {{
    background: transparent;
    border: 1px solid {BORDER_LIGHT};
}}
QPushButton#ghost:hover {{
    background: rgba(255,255,255,0.06);
}}
QPushButton.winbtn {{
    background: transparent;
    border: none;
    border-radius: 0;
    color: {TEXT_2};
    font-size: 14px;
    padding: 0 14px;
    min-width: 40px;
    min-height: 36px;
}}
QPushButton.winbtn:hover {{
    background: rgba(255,255,255,0.10);
    color: {TEXT};
}}
QPushButton.winbtn#winClose:hover {{
    background: #E81123;
    color: white;
}}

/* ---- 输入 ---- */
QLineEdit, QComboBox {{
    background: rgba(10,14,22,0.6);
    border: 1px solid {BORDER_LIGHT};
    border-radius: 8px;
    color: {TEXT};
    padding: 7px 10px;
    font-size: 13px;
    selection-background-color: {ACCENT};
}}
QLineEdit:focus, QComboBox:focus {{
    border-color: {ACCENT};
}}
QComboBox::drop-down {{
    border: none;
    width: 22px;
}}
QComboBox::down-arrow {{
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {TEXT_2};
    margin-right: 8px;
}}
QComboBox QAbstractItemView {{
    background: {PANEL_SOLID};
    border: 1px solid {BORDER_LIGHT};
    border-radius: 8px;
    color: {TEXT};
    selection-background-color: {ACCENT_SOFT};
}}

/* ---- 进度条 ---- */
QProgressBar {{
    background: rgba(255,255,255,0.06);
    border: none;
    border-radius: 5px;
    min-height: 8px;
    max-height: 8px;
    text-align: center;
}}
QProgressBar::chunk {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {ACCENT}, stop:1 {ACCENT_HOVER});
    border-radius: 5px;
}}

/* ---- 日志 ---- */
QPlainTextEdit#logView {{
    background: rgba(9,12,19,0.62);
    border: 1px solid {BORDER_LIGHT};
    border-radius: 10px;
    color: #C9D4E4;
    font-family: {MONO_FAMILY};
    font-size: 12px;
    padding: 8px;
    selection-background-color: rgba(61,107,255,0.4);
}}
QPlainTextEdit {{
    background: rgba(9,12,19,0.62);
    border: 1px solid {BORDER_LIGHT};
    border-radius: 10px;
    color: {TEXT};
    font-family: {MONO_FAMILY};
    font-size: 12px;
    padding: 6px;
}}

/* ---- 滚动条 ---- */
QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: rgba(255,255,255,0.16);
    border-radius: 4px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{
    background: rgba(255,255,255,0.28);
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 8px;
    margin: 2px;
}}
QScrollBar::handle:horizontal {{
    background: rgba(255,255,255,0.16);
    border-radius: 4px;
    min-width: 30px;
}}
QScrollBar::add-line, QScrollBar::sub-line {{
    width: 0; height: 0;
}}
QScrollBar::add-page, QScrollBar::sub-page {{
    background: transparent;
}}

/* ---- 其他 ---- */
QCheckBox {{
    color: {TEXT_2};
    font-size: 13px;
    spacing: 8px;
}}
QCheckBox::indicator {{
    width: 16px; height: 16px;
    border-radius: 4px;
    border: 1px solid {BORDER_STRONG};
    background: rgba(255,255,255,0.04);
}}
QCheckBox::indicator:checked {{
    background: {ACCENT};
    border-color: {ACCENT};
}}
QSlider::groove:horizontal {{
    height: 4px;
    background: rgba(255,255,255,0.10);
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    width: 14px; height: 14px;
    margin: -5px 0;
    border-radius: 7px;
    background: {ACCENT};
    border: 2px solid #FFFFFF;
}}
QToolTip {{
    background: {PANEL_SOLID};
    color: {TEXT};
    border: 1px solid {BORDER_STRONG};
    border-radius: 6px;
    padding: 5px 8px;
}}
QMessageBox {{
    background: {PANEL_SOLID};
}}
QMenu {{
    background: {PANEL_SOLID};
    color: {TEXT};
    border: 1px solid {BORDER_LIGHT};
    border-radius: 8px;
}}
QMenu::item:selected {{
    background: {ACCENT_SOFT};
}}

/* ---- 侧边栏 ---- */
QListWidget#sidebar {{
    background: rgba(10,14,22,0.55);
    border: none;
    padding: 10px 8px;
    font-size: 14px;
    color: {TEXT_2};
    outline: none;
}}
QListWidget#sidebar::item {{
    border-radius: 8px;
    padding: 10px 14px;
    margin: 2px 0;
}}
QListWidget#sidebar::item:hover {{
    background: rgba(255,255,255,0.06);
    color: {TEXT};
}}
QListWidget#sidebar::item:selected {{
    background: {ACCENT_SOFT};
    color: white;
    font-weight: 600;
}}
QLabel#sidebarGroupTitle {{
    font-size: 16px;
    font-weight: 800;
    color: {TEXT_2};
    padding-left: 12px;
    padding-top: 6px;
}}

/* ---- 普通列表 ---- */
QListWidget {{
    background: rgba(10,14,22,0.55);
    border: 1px solid {BORDER_LIGHT};
    border-radius: 8px;
    color: {TEXT};
    font-size: 13px;
    padding: 4px;
    outline: none;
}}
QListWidget::item {{
    border-radius: 6px;
    padding: 6px 8px;
    margin: 1px;
}}
QListWidget::item:hover {{
    background: rgba(255,255,255,0.05);
}}
QListWidget::item:selected {{
    background: {ACCENT_SOFT};
    color: white;
}}

/* ---- 标题栏 ---- */
QFrame#titlebar {{
    background: rgba(10,13,20,0.72);
    border-bottom: 1px solid {BORDER_LIGHT};
    border-top-left-radius: {WINDOW_RADIUS}px;
    border-top-right-radius: {WINDOW_RADIUS}px;
}}
QFrame#titlebar[corner="square"] {{
    border-top-left-radius: 0px;
    border-top-right-radius: 0px;
}}
QLabel#appTitle {{
    font-size: 14px;
    font-weight: 600;
    color: {TEXT};
    letter-spacing: 0.5px;
}}
QLabel#appSub {{
    font-size: 11px;
    color: {TEXT_3};
}}

/* ---- Toast ---- */
QLabel#toast {{
    background: rgba(19,26,40,0.92);
    color: {TEXT};
    border: 1px solid {BORDER_STRONG};
    border-radius: 16px;
    padding: 8px 18px;
    font-size: 13px;
}}

/* ---- 日志等只读文本框 ---- */
QPlainTextEdit {{
    selection-background-color: {ACCENT};
}}
"""


def build_qss(theme_key: str = "glass", glass: str = "default", accent: str = "default") -> str:
    """按当前 UI 主题生成全局 QSS。玻璃主题走原 QSS（accent 选强调色），瑞士极简走扁平浅色 QSS。"""
    key = (theme_key, glass, accent, UI_STYLE, UI_LAYOUT)
    cached = _QSS_CACHE.get(key)
    if cached is not None:
        return cached
    if UI_STYLE == "terminal":
        text = _build_qss_terminal(accent)
        _QSS_CACHE[key] = text
        return text
    if UI_STYLE == "swiss":
        text = _build_qss_swiss(accent)
        _QSS_CACHE[key] = text
        return text
    saved = {k: globals()[k] for k in TOKEN_KEYS}
    try:
        color_cfg = THEMES.get(accent, THEMES["default"])
        for k in TOKEN_KEYS:
            if k in color_cfg:
                globals()[k] = color_cfg[k]
        glass_cfg = GLASS.get(glass, GLASS["default"])
        for k in TOKEN_KEYS:
            if k in glass_cfg:
                globals()[k] = glass_cfg[k]
        text = _build_qss_inner()
        _QSS_CACHE[key] = text
        return text
    finally:
        for k, val in saved.items():
            globals()[k] = val


def _build_qss_swiss(accent: str = "default") -> str:
    """瑞士极简：浅色底、细线边框、无圆角无阴影；强调色跟随当前皮肤。"""
    cfg = THEMES.get(accent, THEMES["default"])
    swiss_accent = cfg["ACCENT"]
    swiss_accent_hover = cfg["ACCENT_HOVER"]
    swiss_accent_active = cfg["ACCENT_ACTIVE"]
    return f"""
* {{ font-family: {FONT_FAMILY}; outline: none; }}
QWidget {{ background: transparent; color: #111111; }}
QMainWindow, QWidget#mainRoot {{ background: #F7F7F5; }}
QLabel {{ background: transparent; color: #111111; }}
QLabel#pageTitle {{ font-size: 22px; font-weight: 700; color: #111111; letter-spacing: 0.5px; }}
QLabel#pageSub {{ font-size: 13px; color: #6B6B67; }}
QLabel#sectionTitle {{ font-size: 15px; font-weight: 700; color: #111111; }}
QLabel#caption {{ font-size: 12px; color: #6B6B67; }}
QLabel#value {{ font-size: 14px; font-weight: 700; color: #111111; }}
QLabel#sidebarGroupTitle {{ font-size: 16px; font-weight: 800; color: #6B6B67; letter-spacing: 1px; padding-left: 10px; padding-top: 6px; }}
QFrame#titlebar {{
    background: #FFFFFF;
    border-bottom: 1px solid #D9D9D6;
    border-top-left-radius: {WINDOW_RADIUS}px;
    border-top-right-radius: {WINDOW_RADIUS}px;
}}
QFrame#titlebar[corner="square"] {{
    border-top-left-radius: 0px;
    border-top-right-radius: 0px;
}}
QLabel#appTitle {{ font-size: 14px; font-weight: 700; color: #111111; }}
QLabel#appSub {{ font-size: 11px; color: #6B6B67; }}
QPushButton#winMin, QPushButton#winMax, QPushButton#winClose {{
    background: transparent; border: none; color: #444444; font-size: 13px; border-radius: 0;
}}
QPushButton#winMin:hover, QPushButton#winMax:hover {{ background: #EFEFEC; color: #111111; }}
QPushButton#winClose:hover {{ background: #E30613; color: #FFFFFF; }}
QPushButton {{ background: #FFFFFF; border: 1px solid #C9C9C5; border-radius: 0; color: #111111; padding: 8px 16px; font-size: 13px; }}
QPushButton:hover {{ background: #EFEFEC; border-color: #A9A9A4; }}
QPushButton:pressed {{ background: #E4E4E0; }}
QPushButton:disabled {{ color: #A5A5A1; background: #F1F1EE; border-color: #E0E0DC; }}
QPushButton#primary {{ background: {swiss_accent}; border: 1px solid {swiss_accent}; color: #FFFFFF; font-weight: 700; }}
QPushButton#primary:hover {{ background: {swiss_accent_hover}; }}
QPushButton#primary:pressed {{ background: {swiss_accent_active}; }}
QPushButton#danger {{ background: #FFFFFF; border: 1px solid #E30613; color: #E30613; }}
QPushButton#danger:hover {{ background: #E30613; color: #FFFFFF; }}
QPushButton#ghost {{ background: transparent; border: 1px solid #C9C9C5; }}
QPushButton#topnavItem {{
    background: transparent; border: none; border-bottom: 2px solid transparent;
    color: #444444; font-size: 13px; font-weight: 600; padding: 0 16px; border-radius: 0;
}}
QPushButton#topnavItem:hover {{ color: #111111; }}
QPushButton#topnavItem:checked {{ color: #111111; border-bottom: 2px solid {swiss_accent}; }}
QFrame#glass, QFrame#glassStrong {{ background: transparent; border: none; }}
QListWidget#sidebar {{ background: transparent; border: none; font-size: 14px; color: #333333; }}
QListWidget#sidebar::item {{ padding: 10px 14px; border-radius: 0; margin: 0; border-bottom: 1px solid rgba(0,0,0,0.05); }}
QListWidget#sidebar::item:hover {{ background: #EFEFEC; }}
QListWidget#sidebar::item:selected {{ background: #111111; color: #FFFFFF; }}
QListWidget {{ background: #FFFFFF; border: 1px solid #D9D9D6; border-radius: 0; color: #111111; font-size: 13px; }}
QListWidget::item {{ padding: 6px 8px; }}
QListWidget::item:selected {{ background: #111111; color: #FFFFFF; }}
QLineEdit, QComboBox {{ background: #FFFFFF; border: 1px solid #C9C9C5; border-radius: 0; color: #111111; padding: 6px 8px; font-size: 13px; }}
QSlider::groove:horizontal {{ height: 2px; background: #C9C9C5; }}
QSlider::handle:horizontal {{ width: 14px; margin: -6px 0; background: #111111; border-radius: 0; }}
QPlainTextEdit {{ background: #FFFFFF; border: 1px solid #D9D9D6; color: #111111; font-family: {MONO_FAMILY}; font-size: 12px; }}
QLabel#toast {{ background: #111111; color: #FFFFFF; border-radius: 0; padding: 10px 20px; font-size: 13px; }}
QProgressBar {{ border: 1px solid #C9C9C5; border-radius: 0; background: #FFFFFF; }}
QProgressBar::chunk {{ background: {swiss_accent}; }}
QDialog, QMessageBox {{ background: #FFFFFF; color: #111111; }}
QMessageBox QLabel {{ color: #111111; background: transparent; }}
QMenu {{ background: #FFFFFF; color: #111111; border: 1px solid #C9C9C5; }}
QMenu::item:selected {{ background: #111111; color: #FFFFFF; }}
QToolTip {{ background: #111111; color: #FFFFFF; border: 1px solid #444444; }}
"""


def _build_qss_terminal(accent: str = "default") -> str:
    """深空终端：近黑底、等宽字体、细线边框、单一荧光强调色、小圆角、无玻璃无阴影。"""
    cfg = THEMES.get(accent, THEMES["default"])
    term_accent = cfg["ACCENT"]
    term_accent_hover = cfg["ACCENT_HOVER"]
    term_accent_active = cfg["ACCENT_ACTIVE"]
    return f"""
* {{
    font-family: "Cascadia Mono", "Microsoft YaHei UI", Consolas, "Segoe UI", sans-serif;
    outline: none;
}}
QWidget {{ background: transparent; color: #E6EDF3; }}
QMainWindow, QWidget#mainRoot {{ background: #0A0D10; }}
QLabel {{ background: transparent; color: #E6EDF3; }}
QLabel#pageTitle {{ font-size: 21px; font-weight: 700; color: #E6EDF3; letter-spacing: 1px; }}
QLabel#pageSub {{ font-size: 12px; color: #9BA7B4; }}
QLabel#sectionTitle {{ font-size: 14px; font-weight: 700; color: #E6EDF3; letter-spacing: 0.5px; }}
QLabel#caption {{ font-size: 11px; color: #7E8A9C; }}
QLabel#value {{ font-size: 13px; font-weight: 700; color: #E6EDF3; }}
QLabel#sidebarGroupTitle {{ font-size: 12px; font-weight: 700; color: {term_accent}; letter-spacing: 2px; padding-left: 14px; padding-top: 8px; }}

QFrame#glass, QFrame#glassStrong {{
    background: #11151A;
    border: 1px solid rgba(255,255,255,0.10);
    border-radius: 6px;
}}

QPushButton {{
    background: rgba(255,255,255,0.05);
    border: 1px solid rgba(255,255,255,0.14);
    border-radius: 4px;
    color: #E6EDF3;
    padding: 6px 13px;
    font-size: 12px;
}}
QPushButton:hover {{ background: rgba(255,255,255,0.09); border-color: rgba(255,255,255,0.24); }}
QPushButton:pressed {{ background: rgba(255,255,255,0.03); }}
QPushButton:focus {{ border-color: {term_accent}; }}
QPushButton:disabled {{ color: #5C6672; background: rgba(255,255,255,0.02); border-color: rgba(255,255,255,0.05); }}
QPushButton#primary {{ background: {term_accent}; border: 1px solid {term_accent}; color: #05070A; font-weight: 700; }}
QPushButton#primary:hover {{ background: {term_accent_hover}; border-color: {term_accent_hover}; }}
QPushButton#primary:pressed {{ background: {term_accent_active}; }}
QPushButton#primary:disabled {{ background: {rgba(term_accent, 0.35)}; border-color: {rgba(term_accent, 0.35)}; color: rgba(5,7,10,0.6); }}
QPushButton#danger {{ background: rgba(248,113,113,0.10); border: 1px solid rgba(248,113,113,0.40); color: #FCA5A5; }}
QPushButton#danger:hover {{ background: rgba(248,113,113,0.20); }}
QPushButton#ghost {{ background: transparent; border: 1px solid rgba(255,255,255,0.14); }}
QPushButton#ghost:hover {{ background: rgba(255,255,255,0.06); }}
QPushButton.winbtn {{ background: transparent; border: none; color: #9BA7B4; font-size: 13px; padding: 0 14px; min-width: 40px; min-height: 36px; }}
QPushButton.winbtn:hover {{ background: rgba(255,255,255,0.08); color: #E6EDF3; }}
QPushButton.winbtn#winClose:hover {{ background: #E81123; color: white; }}

QLineEdit, QComboBox {{
    background: #0B0F14;
    border: 1px solid rgba(255,255,255,0.12);
    border-radius: 4px;
    color: #E6EDF3;
    padding: 6px 9px;
    font-size: 12px;
    selection-background-color: {term_accent};
    selection-color: #05070A;
}}
QLineEdit:focus, QComboBox:focus {{ border-color: {term_accent}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox::down-arrow {{
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid #9BA7B4;
    margin-right: 8px;
}}
QComboBox QAbstractItemView {{ background: #0E1217; border: 1px solid rgba(255,255,255,0.12); color: #E6EDF3; selection-background-color: {rgba(term_accent, 0.18)}; }}

QProgressBar {{
    background: rgba(255,255,255,0.07);
    border: none;
    border-radius: 3px;
    min-height: 6px;
    max-height: 6px;
    text-align: center;
}}
QProgressBar::chunk {{ background: {term_accent}; border-radius: 3px; }}

QListWidget#sidebar {{
    background: transparent;
    border: none;
    padding: 10px 6px;
    font-size: 13px;
    color: #9BA7B4;
    outline: none;
}}
QListWidget#sidebar::item {{
    border-left: 3px solid transparent;
    border-radius: 0;
    padding: 8px 14px;
    margin: 1px 0;
}}
QListWidget#sidebar::item:hover {{ background: rgba(255,255,255,0.05); color: #E6EDF3; }}
QListWidget#sidebar::item:selected {{ background: {rgba(term_accent, 0.12)}; color: {term_accent}; border-left: 3px solid {term_accent}; font-weight: 700; }}

QListWidget#rail {{
    background: transparent;
    border: none;
    border-right: 1px solid rgba(255,255,255,0.08);
    padding: 8px 0;
    outline: none;
}}
QListWidget#rail::item {{
    border-left: 2px solid transparent;
    margin: 2px 0;
    padding: 0;
    height: 44px;
}}
QListWidget#rail::item:hover {{ background: rgba(255,255,255,0.05); }}
QListWidget#rail::item:selected {{ background: {rgba(term_accent, 0.12)}; border-left: 2px solid {term_accent}; }}

QListWidget {{
    background: #0B0F14;
    border: 1px solid rgba(255,255,255,0.10);
    border-radius: 4px;
    color: #E6EDF3;
    font-size: 12px;
    padding: 3px;
    outline: none;
}}
QListWidget:focus {{ border-color: {term_accent}; }}
QListWidget::item {{ border-radius: 3px; padding: 5px 8px; margin: 1px; }}
QListWidget::item:hover {{ background: rgba(255,255,255,0.05); }}
QListWidget::item:selected {{ background: {rgba(term_accent, 0.16)}; color: #E6EDF3; }}

QPlainTextEdit, QPlainTextEdit#logView {{
    background: #07090C;
    border: 1px solid rgba(255,255,255,0.10);
    border-radius: 4px;
    color: #C9D4E4;
    font-family: "Cascadia Mono", Consolas, monospace;
    font-size: 12px;
    padding: 6px;
    selection-background-color: {rgba(term_accent, 0.4)};
}}

QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: rgba(255,255,255,0.14); border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {rgba(term_accent, 0.55)}; }}
QScrollBar:horizontal {{ background: transparent; height: 8px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: rgba(255,255,255,0.14); border-radius: 4px; min-width: 30px; }}
QScrollBar::handle:horizontal:hover {{ background: {rgba(term_accent, 0.55)}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QCheckBox {{ color: #9BA7B4; font-size: 12px; spacing: 8px; }}
QCheckBox::indicator {{ width: 15px; height: 15px; border-radius: 2px; border: 1px solid rgba(255,255,255,0.22); background: #0B0F14; }}
QCheckBox::indicator:checked {{ background: {term_accent}; border-color: {term_accent}; }}
QCheckBox:focus::indicator {{ border-color: {term_accent}; }}

QSlider::groove:horizontal {{ height: 3px; background: rgba(255,255,255,0.10); border-radius: 2px; }}
QSlider::handle:horizontal {{ width: 12px; height: 12px; margin: -5px 0; border-radius: 6px; background: {term_accent}; border: 2px solid #0A0D10; }}

QFrame#titlebar {{
    background: #0C1015;
    border-bottom: 1px solid rgba(255,255,255,0.08);
    border-top-left-radius: {WINDOW_RADIUS}px;
    border-top-right-radius: {WINDOW_RADIUS}px;
}}
QFrame#titlebar[corner="square"] {{ border-top-left-radius: 0px; border-top-right-radius: 0px; }}
QLabel#appTitle {{ font-size: 13px; font-weight: 700; color: #E6EDF3; letter-spacing: 1px; }}
QLabel#appSub {{ font-size: 10px; color: #7E8A9C; }}

QLabel#toast {{ background: #11151A; color: #E6EDF3; border: 1px solid {rgba(term_accent, 0.45)}; border-radius: 4px; padding: 8px 16px; font-size: 12px; }}
QToolTip {{ background: #0E1217; color: #E6EDF3; border: 1px solid {rgba(term_accent, 0.4)}; border-radius: 4px; padding: 5px 8px; }}
QMenu {{ background: #0E1217; color: #E6EDF3; border: 1px solid rgba(255,255,255,0.14); border-radius: 4px; }}
QMenu::item:selected {{ background: {rgba(term_accent, 0.16)}; }}
QDialog, QMessageBox {{ background: #0E1217; color: #E6EDF3; }}
QMessageBox QLabel {{ color: #E6EDF3; background: transparent; }}
"""
