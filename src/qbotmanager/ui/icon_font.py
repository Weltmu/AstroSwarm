# -*- coding: utf-8 -*-
"""线性图标：用 Phosphor 图标字体把字形渲染成 QIcon（统一线宽，避免 emoji 当图标）。"""
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QPainter, QPixmap

_FAMILY = "Phosphor"
_FONT_LOADED = False

ICONS = {
    "home": 0xE2C2,
    "chat-circle": 0xE168,
    "chat-circle-dots": 0xE16C,
    "paper-plane": 0xE394,
    "paper-plane-tilt": 0xE398,
    "brain": 0xE74E,
    "chat-centered": 0xE160,
    "puzzle-piece": 0xE596,
    "package": 0xE390,
    "terminal-window": 0xEAE8,
    "gear-six": 0xE272,
    "gear": 0xE270,
    "warning-circle": 0xE4E2,
    "check-circle": 0xE184,
    "arrow-right": 0xE06C,
    "lifebuoy": 0xE63A,
    "sparkle": 0xE6A2,
    "robot": 0xE762,
}


def _ensure_font() -> bool:
    global _FONT_LOADED
    if _FONT_LOADED:
        return True
    candidates = [
        Path(__file__).resolve().parent.parent / "assets" / "fonts" / "Phosphor.ttf",
        Path(__file__).resolve().parent / "Phosphor.ttf",
    ]
    for path in candidates:
        if path.exists():
            fid = QFontDatabase.addApplicationFont(str(path))
            if fid >= 0:
                families = QFontDatabase.applicationFontFamilies(fid)
                if families:
                    _FONT_LOADED = True
                    return True
    return False


def render_pixmap(name: str, color: str = "#A7B1C2", size: int = 16,
                  dpr: float = 2.0) -> QPixmap:
    """把 Phosphor 字形渲染成带 DPR 的 QPixmap（逻辑尺寸 = size，物理 = size*dpr）。

    供 QIcon 与直接 setPixmap 使用，高分屏下保持清晰。
    """
    cp = ICONS.get(name)
    if cp is None or not _ensure_font():
        return QPixmap()
    pm = QPixmap(round(size * dpr), round(size * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    font = QFont(_FAMILY)
    font.setPixelSize(size)
    p.setFont(font)
    p.setPen(QColor(color))
    rect = QRectF(0, 0, size, size)
    p.drawText(rect, Qt.AlignCenter, chr(cp))
    p.end()
    return pm


def make_icon(name: str, color: str = "#A7B1C2", size: int = 16) -> QIcon:
    pm = render_pixmap(name, color, size)
    if pm.isNull():
        return QIcon()
    return QIcon(pm)
