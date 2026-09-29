# -*- coding: utf-8 -*-
"""动态视频背景层（GPU 路径）：QQuickWidget + QML VideoOutput。

层级：本控件（静态渐变兜底）-> QQuickWidget(QML MediaPlayer + VideoOutput) -> 亮度层 -> 暗色遮罩 -> 上层 UI。

技术要点：
- 不使用 QVideoWidget：无边框窗口下它是原生子窗口，会被系统提升为独立顶层窗口。
- 不使用 QVideoFrame -> toImage -> QPainter：每帧显存到内存回读会让 4K 拖垮整机。
- MediaPlayer 与 VideoOutput 都在 QML 内（标准写法），Python 通过 setProperty / invokeMethod 控制。
  （PySide6 6.11 中 Python 侧 QMediaPlayer + VideoOutput.source 跨边界绑定不投递帧，故必须在 QML 内建播放器。）
- 注意：QML MediaPlayer 的 playbackState / mediaStatus 枚举属性从 Python 读取会抛
  "Can't find converter" 错误，因此播放状态由本层自行维护（_playing 标志 + position 轮询）。
"""
import sys
import time
from pathlib import Path

from PySide6.QtCore import QMetaObject, QObject, QRectF, QTimer, QUrl, Qt, Signal
from PySide6.QtGui import (
    QColor, QLinearGradient, QPainter, QPainterPath, QPixmap, QRadialGradient,
)
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import QLabel, QWidget

from ..core.video_caps import SOFTWARE_BACKENDS, backend_name, query_gpu, query_ram
from .theme import BG_0, BG_1

MASK_BASE = (0.10, 0.30, 0.50, 0.66)

MONITOR_INTERVAL_MS = 2000
# QML 离屏渲染缩放：FFmpeg 后端已走 GPU 纹理直通，保持 1:1 画质；
# 若未来换回软解后端可调大此值降负载。
RENDER_SCALE = 1


def _qml_path():
    """定位 bg.qml：开发环境在源码目录；PyInstaller 环境在 _MEIPASS / exe 旁。"""
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        for cand in (base / "qbotmanager/ui/bg.qml", base / "bg.qml",
                     Path(sys.executable).parent / "bg.qml",
                     Path(sys.executable).parent / "qbotmanager/ui/bg.qml"):
            if cand.exists():
                return cand
    p = Path(__file__).resolve().parent / "bg.qml"
    return p if p.exists() else None


class VideoBackground(QWidget):
    stateChanged = Signal(str)
    loadFailed = Signal(str)
    fallbackNotice = Signal(str)
    playbackRequested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._enabled = False
        self._path: Path | None = None
        self._mask_strength = 0.68
        self._brightness = 0
        self._autoplay = True
        self._loop = True
        self._user_paused = False
        self._window_active = True
        self._playing = False
        self._fallback = True
        self._render_scale = RENDER_SCALE
        self._mask_pixmap = None
        self._mask_size = None
        self._source_loaded = False
        self._radius = 0

        self.current_file: Path | None = None
        self.static_reason: str = ""

        # GPU 视频层：QQuickWidget + QML MediaPlayer/VideoOutput
        self.quick = QQuickWidget(self)
        self.quick.setResizeMode(QQuickWidget.SizeRootObjectToView)
        self.quick.setClearColor(QColor(Qt.transparent))
        self.quick.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.quick.setFocusPolicy(Qt.NoFocus)
        qml = _qml_path()
        self.qml_ok = qml is not None
        if qml is None:
            self.loadFailed.emit("缺少 bg.qml 资源，动态背景不可用")
        else:
            self.quick.setSource(QUrl.fromLocalFile(str(qml)))
        root = self.quick.rootObject()
        self.root = root
        self.player = None
        self.video_item = None
        if root is not None:
            self.player = root.findChild(QObject, "mp")
            self.video_item = root.findChild(QObject, "video")
            try:
                root.setProperty("renderScale", self._render_scale)
            except Exception:  # noqa: BLE001
                pass
            try:
                root.errorHappened.connect(self._on_qml_error)
            except Exception:  # noqa: BLE001
                pass
        self.quick.hide()

        # 亮度覆盖层（夹在视频与遮罩之间）
        self.brightness_layer = QLabel(self)
        self.brightness_layer.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.brightness_layer.hide()

        # 暗色遮罩层（盖在视频之上）
        self.mask = QLabel(self)
        self.mask.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.mask.hide()

        # 能力探测（一次性，轻量）
        self.backend = backend_name(self.quick)
        self.gpu = query_gpu()
        self.ram = query_ram()

        # 监控定时器（低频，不接触视频帧）
        self.monitor = QTimer(self)
        self.monitor.setInterval(MONITOR_INTERVAL_MS)
        self.monitor.timeout.connect(self._on_monitor_tick)
        self.monitor.start()
        self._monitor_last = None

    # ------------------------------------------------------------ 配置
    def set_enabled(self, enabled: bool):
        enabled = bool(enabled)
        if enabled == self._enabled:
            return
        self._enabled = enabled
        if not enabled:
            self._enter_static("已停用动态背景")
        elif self._path:
            self._request_playback()

    def set_video(self, path):
        self._path = Path(path) if path else None
        if self._enabled and self._path and self._path.exists():
            self._request_playback()
        else:
            self._enter_static("未设置背景视频")

    def set_mask_strength(self, strength: float):
        try:
            strength = max(0.30, min(0.95, float(strength)))
        except (TypeError, ValueError):
            strength = 0.68
        if abs(strength - self._mask_strength) < 0.001:
            return
        self._mask_strength = strength
        self._mask_pixmap = None
        self._render_mask()

    def set_brightness(self, value: int):
        """视频亮度 -100 ~ 100（0 = 原样）。"""
        try:
            value = max(-100, min(100, int(value)))
        except (TypeError, ValueError):
            value = 0
        if value == self._brightness:
            return
        self._brightness = value
        self._render_brightness()

    def set_autoplay(self, enabled: bool):
        self._autoplay = bool(enabled)
        if self._enabled and self._path and self._autoplay and not self._fallback:
            self._start_playing()

    def set_loop(self, enabled: bool):
        self._loop = bool(enabled)
        if self.player is not None:
            self.player.setProperty("loops", -1 if self._loop else 1)

    def set_window_active(self, active: bool):
        """窗口最小化/恢复时暂停/恢复播放，避免不可见时仍满负荷解码。"""
        active = bool(active)
        if active == self._window_active:
            return
        self._window_active = active
        if active:
            if self._enabled and self._path and self._autoplay and not self._user_paused:
                self._start_playing()
        else:
            if self._playing:
                self._invoke("pause")
                self._playing = False
                self.stateChanged.emit("paused")

    def set_corner_radius(self, radius: int):
        """窗口圆角半径：同步亮度层与暗色遮罩（遮罩内含四角盖板）。"""
        radius = max(0, int(radius))
        if radius == self._radius:
            return
        self._radius = radius
        if self.root is not None:
            try:
                self.root.setProperty("cornerRadius", radius)
            except Exception:  # noqa: BLE001
                pass
        self._render_brightness()
        self._render_mask()
        self.update()

    # ------------------------------------------------------------ 播放
    def play_file(self, path):
        """直接播放指定的原视频文件（不做任何转码/分档）。"""
        path = Path(path)
        if not path.exists():
            self.loadFailed.emit(f"背景视频文件不存在: {path}")
            self._enter_static("背景视频文件不存在")
            return
        if self.player is None:
            self.loadFailed.emit("QML 播放器未就绪")
            self._enter_static("QML 播放器未就绪")
            return
        self.current_file = path
        self._fallback = False
        self.mask.show()
        self.quick.show()
        self._render_brightness()
        self.player.setProperty("loops", -1 if self._loop else 1)
        src = QUrl.fromLocalFile(str(path))
        if not self._source_loaded or str(self.player.property("source")) != src.toString():
            self.player.setProperty("source", src)
            self._source_loaded = True
        self._monitor_last = time.monotonic()
        self._start_playing()

    def enter_static(self, reason: str):
        self._enter_static(reason)

    def capability(self) -> dict:
        return {
            "backend": self.backend,
            "software": self.backend in SOFTWARE_BACKENDS,
            "gpu": self.gpu,
            "ram": self.ram,
            "static": self._fallback,
            "static_reason": self.static_reason,
            "path": str(self._path) if self._path else "",
        }

    # ------------------------------------------------------------ 生命周期
    def pause(self):
        self._user_paused = True
        if self._playing:
            self._invoke("pause")
            self._playing = False
            self.stateChanged.emit("paused")

    def resume(self):
        self._user_paused = False
        if self._enabled and self._path and self._autoplay:
            self._start_playing()

    def shutdown(self):
        try:
            self.monitor.stop()
            if self.player is not None:
                self._invoke("stop")
                self.player.setProperty("source", "")
            self.quick.deleteLater()
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------ 内部
    def _invoke(self, method: str):
        if self.player is not None:
            try:
                QMetaObject.invokeMethod(self.player, method)
            except Exception:  # noqa: BLE001
                pass

    def _request_playback(self):
        if self._path and self._path.exists():
            self.playbackRequested.emit(str(self._path))

    def _start_playing(self):
        if not self._window_active or self._user_paused:
            return
        if self.player is None:
            return
        if not self._playing:
            self._invoke("play")
            self._playing = True
            self.stateChanged.emit("playing")

    def _enter_static(self, reason: str):
        self._fallback = True
        self.static_reason = reason
        self._playing = False
        self._invoke("stop")
        self.quick.hide()
        self.brightness_layer.hide()
        self.mask.hide()
        self.stateChanged.emit("static")
        if reason:
            self.fallbackNotice.emit(reason)
        self.update()

    def _on_qml_error(self, code, msg):
        self._playing = False
        self.stateChanged.emit("error")
        self.loadFailed.emit(str(msg))

    # ------------------------------------------------------------ 监控
    def _on_monitor_tick(self):
        now = time.monotonic()
        if self._monitor_last is None:
            self._monitor_last = now
            return
        self._monitor_last = now

        if self._fallback or not self._playing or self.player is None:
            return

        pos = int(self.player.property("position") or 0)
        dur = int(self.player.property("duration") or 0)

        # 非循环模式播完后自动重播（背景场景）
        if not self._loop and dur > 0 and pos >= dur - 100:
            try:
                QMetaObject.invokeMethod(self.player, "setPosition",
                                         Qt.DirectConnection,
                                         self._qarg_int(0))
            except Exception:  # noqa: BLE001
                pass
            self._invoke("play")
            self._monitor_last = time.monotonic()

    def _qarg_int(self, value: int):
        from PySide6.QtCore import Q_ARG
        return Q_ARG(int, value)

    # ------------------------------------------------------------ 亮度/遮罩/绘制
    def _render_brightness(self):
        if self._brightness == 0:
            self.brightness_layer.hide()
            return
        self.brightness_layer.show()
        alpha = min(200, abs(self._brightness) * 2)
        if self._brightness > 0:
            color = f"rgba(255,255,255,{alpha})"
        else:
            color = f"rgba(0,0,0,{alpha})"
        self.brightness_layer.setStyleSheet(
            f"background: {color}; border-radius: {self._radius}px;")

    def _render_mask(self):
        w, h = self.width(), self.height()
        if w <= 1 or h <= 1:
            return
        if self._mask_size == (w, h) and self._mask_pixmap is not None:
            return
        self._mask_size = (w, h)
        scale = self._mask_strength / 0.68
        a0, a1, a2, a3 = [max(0.0, min(1.0, x * scale)) for x in MASK_BASE]
        pm = QPixmap(w, h)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        inner = QPainterPath()
        if self._radius:
            inner.addRoundedRect(
                QRectF(0, 0, w, h).adjusted(0.5, 0.5, -0.5, -0.5),
                self._radius, self._radius)
            # 圆角外四角：窗口背景渐变盖住（不透明），视频方角不外露。
            # 与圆角内遮罩合成在同一张纹理，省掉一层全屏覆盖。
            bg = QLinearGradient(0, 0, 0, h)
            bg.setColorAt(0.0, QColor(BG_0))
            bg.setColorAt(1.0, QColor(BG_1))
            p.fillRect(0, 0, w, h, bg)
            p.setCompositionMode(QPainter.CompositionMode_Clear)
            p.fillPath(inner, Qt.transparent)
            p.setCompositionMode(QPainter.CompositionMode_SourceOver)
            p.setClipPath(inner)
        # 圆角内：暗色遮罩渐变（半透明，视频透出）
        grad = QLinearGradient(0, 0, 0, h)
        grad.setColorAt(0.0, QColor(0, 0, 0, int(a0 * 255)))
        grad.setColorAt(0.45, QColor(3, 6, 14, int(a1 * 255)))
        grad.setColorAt(0.78, QColor(2, 4, 10, int(a2 * 255)))
        grad.setColorAt(1.0, QColor(0, 0, 6, int(a3 * 255)))
        p.fillRect(0, 0, w, h, grad)
        vg = QRadialGradient(w / 2, h / 2, max(w, h) * 0.72)
        vg.setColorAt(0.0, QColor(0, 0, 0, 0))
        vg.setColorAt(1.0, QColor(0, 0, 0, int(120 * scale)))
        p.fillRect(0, 0, w, h, vg)
        p.end()
        self._mask_pixmap = pm
        self.mask.setPixmap(pm)
        self.mask.setScaledContents(True)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        w, h = self.width(), self.height()
        self.quick.setGeometry(0, 0, max(1, (w + 1) // self._render_scale),
                               max(1, (h + 1) // self._render_scale))
        self.brightness_layer.setGeometry(self.rect())
        self.mask.setGeometry(self.rect())
        self._render_mask()

    def paintEvent(self, event):
        """静态渐变背景：视频未启用/降级时可见。"""
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if self._radius:
            path = QPainterPath()
            path.addRoundedRect(
                QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5),
                self._radius, self._radius)
            p.setClipPath(path)
        grad = QLinearGradient(0, 0, 0, self.height())
        grad.setColorAt(0.0, QColor(BG_0))
        grad.setColorAt(1.0, QColor(BG_1))
        p.fillRect(self.rect(), grad)
        p.end()
