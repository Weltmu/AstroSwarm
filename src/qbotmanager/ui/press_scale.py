# -*- coding: utf-8 -*-
"""全局按钮按压缩放反馈。

对 QPushButton 打一次性补丁（模块导入时生效）：鼠标左键按住时按钮整体
轻微缩小（PRESS_SCALE），松开后带一点弹性回弹到原尺寸；键盘空格/回车
触发同样反馈。覆盖程序内所有标准按钮（primary/ghost/danger/winbtn/
topnavItem 等），无需逐个替换按钮类。
"""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, Qt, QVariantAnimation
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QPushButton, QStyle, QStyleOptionButton

PRESS_SCALE = 0.96
PRESS_MS = 90
RELEASE_MS = 170

_ORIG_PAINT = QPushButton.paintEvent
_ORIG_MOUSE_PRESS = QPushButton.mousePressEvent
_ORIG_MOUSE_RELEASE = QPushButton.mouseReleaseEvent
_ORIG_KEY_PRESS = QPushButton.keyPressEvent
_ORIG_KEY_RELEASE = QPushButton.keyReleaseEvent

_ACTIVATE_KEYS = {Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter}


def _ensure_anim(btn: QPushButton) -> None:
    if getattr(btn, "_press_scale_anim", None) is not None:
        return
    btn._press_scale = 1.0
    anim = QVariantAnimation(btn)
    anim.valueChanged.connect(lambda v: _apply_scale(btn, float(v)))
    btn._press_scale_anim = anim


def _apply_scale(btn: QPushButton, scale: float) -> None:
    btn._press_scale = scale
    btn.update()


def _animate_to(btn: QPushButton, target: float) -> None:
    _ensure_anim(btn)
    anim = btn._press_scale_anim
    current = getattr(btn, "_press_scale", 1.0)
    anim.stop()
    anim.setDuration(PRESS_MS if target < current else RELEASE_MS)
    anim.setEasingCurve(
        QEasingCurve.OutCubic if target < current else QEasingCurve.OutBack
    )
    anim.setStartValue(current)
    anim.setEndValue(target)
    anim.start()


def _paint(self: QPushButton, event) -> None:
    scale = getattr(self, "_press_scale", 1.0)
    if scale == 1.0:
        _ORIG_PAINT(self, event)
        return
    painter = QPainter(self)
    painter.setRenderHint(QPainter.Antialiasing)
    center = self.rect().center()
    painter.translate(center)
    painter.scale(scale, scale)
    painter.translate(-center)
    opt = QStyleOptionButton()
    self.initStyleOption(opt)
    self.style().drawControl(QStyle.CE_PushButton, opt, painter, self)
    painter.end()


def _mouse_press(self: QPushButton, e) -> None:
    if e.button() == Qt.LeftButton and self.isEnabled():
        _animate_to(self, PRESS_SCALE)
    _ORIG_MOUSE_PRESS(self, e)


def _mouse_release(self: QPushButton, e) -> None:
    if e.button() == Qt.LeftButton:
        _animate_to(self, 1.0)
    _ORIG_MOUSE_RELEASE(self, e)


def _key_press(self: QPushButton, e) -> None:
    if self.isEnabled() and e.key() in _ACTIVATE_KEYS:
        _animate_to(self, PRESS_SCALE)
    _ORIG_KEY_PRESS(self, e)


def _key_release(self: QPushButton, e) -> None:
    if e.key() in _ACTIVATE_KEYS:
        _animate_to(self, 1.0)
    _ORIG_KEY_RELEASE(self, e)


QPushButton.paintEvent = _paint
QPushButton.mousePressEvent = _mouse_press
QPushButton.mouseReleaseEvent = _mouse_release
QPushButton.keyPressEvent = _key_press
QPushButton.keyReleaseEvent = _key_release
