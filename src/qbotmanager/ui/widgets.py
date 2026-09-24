"""可复用 UI 控件：玻璃面板、状态徽章、平滑进度条、空状态。"""
import random

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, Qt, QTimer, QVariantAnimation
from PySide6.QtGui import (
    QColor, QImage, QLinearGradient, QPainter, QPainterPath, QPalette, QPen,
    QPixmap, QRadialGradient,
)
from PySide6.QtWidgets import (
    QCheckBox, QFrame, QHBoxLayout, QLabel, QProgressBar, QVBoxLayout, QWidget,
)

from . import theme as _theme
from .theme import RADIUS, TEXT_2, TEXT_3, status_color


_NOISE_PIX: QPixmap | None = None


class ToggleSwitch(QCheckBox):
    """椭圆滑块开关：椭圆轨道 + 圆形滑块，点击即时切换。"""

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(24)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(self.palette().color(QPalette.WindowText))
        font = self.font()
        font.setPixelSize(13)
        p.setFont(font)
        text_rect = QRectF(0, 0, max(0, self.width() - 56), self.height())
        p.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, self.text())
        pill = QRectF(self.width() - 48, (self.height() - 20) / 2.0, 40, 20)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(_theme.ACCENT if self.isChecked() else "#3A4354"))
        p.drawRoundedRect(pill, 10, 10)
        knob = 14.0
        kx = pill.right() - knob - 3 if self.isChecked() else pill.left() + 3
        p.setBrush(QColor("#FFFFFF"))
        p.drawEllipse(QRectF(kx, (self.height() - knob) / 2.0, knob, knob))
        p.end()

    def hitButton(self, pos):
        """整块控件都可点击（默认 QCheckBox 只认左侧小方框）。

        滑块画在右侧，若不重写 hitButton，用户点滑块/文字都会“没反应”，
        只剩左侧隐藏的小方框能切换——这是小白模式按钮反复“不好使”的根因。
        """
        return self.rect().contains(pos)


def _noise_pixmap() -> QPixmap:
    """生成颗粒噪声贴图（128x128，低透明度灰色颗粒）。"""
    global _NOISE_PIX
    if _NOISE_PIX is None:
        img = QImage(128, 128, QImage.Format_ARGB32)
        img.fill(QColor(0, 0, 0, 0))
        rnd = random.Random(7)
        for y in range(128):
            for x in range(128):
                v = rnd.randint(120, 225)
                a = rnd.randint(5, 14)
                img.setPixelColor(x, y, QColor(v, v, v, a))
        _NOISE_PIX = QPixmap.fromImage(img)
    return _NOISE_PIX


def _fast_blur(pm: QPixmap, factor: int = 5) -> QPixmap:
    """快速近似高斯模糊：先缩小再平滑放大（成本低，观感接近高斯）。"""
    w, h = pm.width(), pm.height()
    if w <= 0 or h <= 0:
        return pm
    small = pm.toImage().scaled(
        max(1, w // factor), max(1, h // factor),
        Qt.IgnoreAspectRatio, Qt.SmoothTransformation,
    )
    big = small.scaled(w, h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    return QPixmap.fromImage(big)


class GlassPanel(QFrame):
    """玻璃容器：支持 默认 / 液态玻璃（鼠标反光）/ 颗粒磨砂（噪声贴图）三种质感。

    由 theme.CURRENT_GLASS 决定绘制方式；液态模式下鼠标所到之处会泛出高光。
    """

    def __init__(self, parent=None, strong=False):
        super().__init__(parent)
        self.setObjectName("glassStrong" if strong else "glass")
        self._strong = strong
        self._hover = QPointF(-1, -1)
        self._backdrop: QPixmap | None = None
        self._refreshing = False
        self.setMouseTracking(True)

    def showEvent(self, event):
        super().showEvent(event)
        if not self._refreshing and not _theme.SUPPRESS_BACKDROP_REFRESH:
            # 等布局稳定后再抓一次背景（避免抓到空窗口）
            QTimer.singleShot(120, self, self._refresh_backdrop)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._backdrop = None
        # 拖动过程中不反复抓取，停 250ms 后再刷新一次，避免累积变亮/变暗
        QTimer.singleShot(250, self, self._refresh_backdrop)

    def _refresh_backdrop(self):
        """抓取面板下方的窗口内容并模糊，作为液态/磨砂玻璃的背景。

        抓取时临时隐藏面板自身，避免把上一帧的玻璃效果也抓进去导致
        反复叠加（液态越变越亮、磨砂越变越暗）。
        """
        if _theme.SUPPRESS_BACKDROP_REFRESH:
            return
        mode = _theme.CURRENT_GLASS
        if mode not in ("liquid", "frosted"):
            # 实体质感（default / terminal）：不抓背景，避免残留上一套玻璃的旧截图
            if self._backdrop is not None:
                self._backdrop = None
                self.update()
            return
        if not self.isVisible():
            return
        win = self.window()
        size = self.size()
        if win is None or size.isEmpty():
            return
        # 视频背景是动态画面：抓屏+模糊会与面板外实时视频割裂、卡顿、发糊，
        # 此时退回半透明渐变（液态/磨砂高光仍在，画面能透出来且流畅）。
        bg = getattr(win, "bg", None)
        if bg is not None and getattr(bg, "_enabled", False) and bg.isVisible():
            self._backdrop = None
            self.update()
            return
        if getattr(win, "isMinimized", lambda: False)():
            return
        rect = QRect(self.mapTo(win, QPoint(0, 0)), size)
        self._refreshing = True
        try:
            self.hide()
            pm = win.grab(rect)
        except Exception:  # noqa: BLE001
            pm = None
        finally:
            self.show()
            self._refreshing = False
        if pm is None or pm.isNull():
            return
        self._backdrop = _fast_blur(pm, 4 if mode == "frosted" else 5)
        self.update()

    def refresh_now(self):
        """主题切换完成后统一刷新一次背景（合并多次抓屏）。"""
        self._refresh_backdrop()

    def childEvent(self, event):
        if event.type() == QEvent.ChildAdded and event.child() is not None:
            child = event.child()
            if isinstance(child, QWidget):
                child.installEventFilter(self)
        super().childEvent(event)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.MouseMove:
            pos = obj.mapToGlobal(event.position().toPoint())
            self._hover = QPointF(self.mapFromGlobal(pos))
            self.update()
        elif event.type() in (QEvent.Leave, QEvent.HoverLeave):
            self._hover = QPointF(-1, -1)
            self.update()
        return super().eventFilter(obj, event)

    def mouseMoveEvent(self, event):
        self._hover = QPointF(event.position())
        self.update()

    def leaveEvent(self, event):
        self._hover = QPointF(-1, -1)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        if _theme.UI_STYLE == "terminal":
            rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
            path = QPainterPath()
            path.addRoundedRect(rect, 6, 6)
            painter.fillPath(path, QColor("#11151A"))
            painter.setPen(QPen(QColor(255, 255, 255, 26), 1))
            painter.drawPath(path)
            painter.end()
            return
        if _theme.UI_STYLE == "swiss":
            # 瑞士极简：可自定义颜色/透明度的扁平卡片 + 细黑描边，无阴影无圆角
            op = max(0.05, min(1.0, float(_theme.UI_OPACITY)))
            color = QColor(_theme.UI_FRAME_COLOR)
            color.setAlpha(int(255 * op))
            rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
            painter.fillRect(self.rect(), color)
            painter.setPen(QPen(QColor(17, 17, 17), 1))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(rect)
            painter.end()
            return
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, RADIUS, RADIUS)
        painter.setClipPath(path)
        strong = self._strong
        mode = _theme.CURRENT_GLASS

        if mode == "liquid":
            if self._backdrop is not None:
                painter.drawPixmap(0, 0, self._backdrop)
            else:
                grad = QLinearGradient(0, 0, 0, self.height())
                grad.setColorAt(0, QColor(255, 255, 255, 36))
                grad.setColorAt(0.45, QColor(17, 22, 34, 107))
                grad.setColorAt(1, QColor(10, 14, 22, 153))
                painter.fillPath(path, grad)
            # 白色透光 tint（自上而下减弱）
            tint = QLinearGradient(0, 0, 0, self.height())
            tint.setColorAt(0, QColor(255, 255, 255, 34 if strong else 26))
            tint.setColorAt(0.45, QColor(255, 255, 255, 8))
            tint.setColorAt(1, QColor(255, 255, 255, 0))
            painter.fillPath(path, tint)
            # 静态斜向高光（苹果液态玻璃的镜面反光）
            sheen = QLinearGradient(0, 0, self.width(), self.height())
            sheen.setColorAt(0, QColor(255, 255, 255, 42 if strong else 32))
            sheen.setColorAt(0.35, QColor(255, 255, 255, 8))
            sheen.setColorAt(0.6, QColor(255, 255, 255, 0))
            sheen.setColorAt(1, QColor(255, 255, 255, 6))
            painter.fillPath(path, sheen)
            # 鼠标柔光：大范围低光 + 小范围高光
            if self._hover.x() >= 0:
                glow = QRadialGradient(self._hover, 110)
                glow.setColorAt(0, QColor(255, 255, 255, 30))
                glow.setColorAt(0.5, QColor(255, 255, 255, 10))
                glow.setColorAt(1, QColor(255, 255, 255, 0))
                painter.fillPath(path, glow)
                core = QRadialGradient(self._hover, 34)
                core.setColorAt(0, QColor(255, 255, 255, 26))
                core.setColorAt(1, QColor(255, 255, 255, 0))
                painter.fillPath(path, core)
        elif mode == "frosted":
            if self._backdrop is not None:
                painter.drawPixmap(0, 0, self._backdrop)
            painter.fillPath(path, QColor(19, 26, 40, 128 if strong else 112))
            painter.drawTiledPixmap(self.rect(), _noise_pixmap())
            haze = QLinearGradient(0, 0, 0, self.height())
            haze.setColorAt(0, QColor(255, 255, 255, 18 if strong else 12))
            haze.setColorAt(1, QColor(255, 255, 255, 0))
            painter.fillPath(path, haze)
        else:
            painter.fillPath(path, QColor(19, 26, 40, 199 if strong else 158))

        painter.setClipping(False)
        border_alpha = 82 if mode == "liquid" else (41 if strong else 20)
        painter.setPen(QPen(QColor(255, 255, 255, border_alpha)))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)
        painter.end()


class StatusBadge(QWidget):
    """状态徽章：色点 + 文字。set_status(key) 自动配色。"""

    def __init__(self, text="未知", color_key="unknown", parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 5, 12, 5)
        lay.setSpacing(7)
        self.dot = QLabel()
        self.dot.setFixedSize(9, 9)
        self.label = QLabel(text)
        self.label.setStyleSheet(f"color: {TEXT_2}; font-size: 13px; font-weight: 600;")
        lay.addWidget(self.dot)
        lay.addWidget(self.label)
        self.set_status(color_key, text)

    def set_status(self, color_key, text=None):
        if text is not None:
            self.label.setText(text)
        color = status_color(color_key)
        self.dot.setStyleSheet(
            f"background: {color}; border-radius: 4px;"
            "min-width: 9px; max-width: 9px; min-height: 9px; max-height: 9px;"
            f"box-shadow: 0 0 6px {color};"
        )
        self.label.setStyleSheet(f"color: {TEXT_2}; font-size: 13px; font-weight: 600;")


class TaskProgressBar(QProgressBar):
    """平滑过渡进度条：值变化自动动画，-1 显示忙碌不确定态。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setRange(0, 100)
        self.setValue(0)
        self.setTextVisible(False)
        self.setFixedHeight(8)
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(220)
        self._anim.valueChanged.connect(self._apply)

    def _apply(self, v):
        self.setValue(int(v))

    def set_smooth(self, value: int):
        value = max(-1, min(100, int(value)))
        self._anim.stop()
        if value == -1:
            self._anim.setStartValue(0)
            self._anim.setEndValue(28)
            self._anim.setLoopCount(-1)
            self._anim.start()
        else:
            self._anim.setLoopCount(1)
            self._anim.setStartValue(self.value())
            self._anim.setEndValue(value)
            self._anim.start()


class EmptyState(QWidget):
    """空状态：居中标题 + 提示，避免页面空白。"""

    def __init__(self, title="暂无内容", hint="", parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignCenter)
        self.title = QLabel(title)
        self.title.setAlignment(Qt.AlignCenter)
        self.title.setStyleSheet(
            f"color: {TEXT_2}; font-size: 15px; font-weight: 600; background: transparent;")
        self.hint = QLabel(hint)
        self.hint.setAlignment(Qt.AlignCenter)
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet(f"color: {TEXT_3}; font-size: 12px; background: transparent;")
        lay.addWidget(self.title)
        lay.addWidget(self.hint)

    def set_content(self, title=None, hint=None):
        if title is not None:
            self.title.setText(title)
        if hint is not None:
            self.hint.setText(hint)
