# -*- coding: utf-8 -*-
"""静态图片背景：封面式缩放填充，不参与交互。"""
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QWidget


class ImageBackground(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap: QPixmap | None = None
        self._radius = 0
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground)

    def set_corner_radius(self, radius: int):
        radius = max(0, int(radius))
        if radius != self._radius:
            self._radius = radius
            self.update()

    def set_image(self, path: str):
        if not path:
            self._pixmap = None
            self.update()
            return
        pm = QPixmap(path)
        self._pixmap = pm if not pm.isNull() else None
        self.update()

    def has_image(self) -> bool:
        return self._pixmap is not None

    def paintEvent(self, event):
        if self._pixmap is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        if self._radius:
            path = QPainterPath()
            path.addRoundedRect(
                QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5),
                self._radius, self._radius)
            painter.setClipPath(path)
        pm = self._pixmap
        scaled = pm.scaled(
            self.size(),
            Qt.KeepAspectRatioByExpanding,
            Qt.SmoothTransformation,
        )
        x = (self.width() - scaled.width()) // 2
        y = (self.height() - scaled.height()) // 2
        painter.drawPixmap(x, y, scaled)
        painter.end()
