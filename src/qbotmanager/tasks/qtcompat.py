"""Qt 兼容层：桌面端用真实 PySide6，无头 Linux 用线程/空信号垫片。"""
try:
    from PySide6.QtCore import QObject, QThread, Qt, QTimer, Signal, Slot

    HAS_QT = True
except Exception:  # noqa: BLE001
    HAS_QT = False

    class QObject:
        def __init__(self, *args, **kwargs):
            pass

    class _NullSignal:
        def connect(self, *args, **kwargs):
            return None

        def disconnect(self, *args, **kwargs):
            return None

        def emit(self, *args, **kwargs):
            return None

    def Signal(*types, **kwargs):
        return _NullSignal()

    class QThread:
        def __init__(self, *args, **kwargs):
            self._thread = None

        def start(self, *args, **kwargs):
            import threading

            self._thread = threading.Thread(target=self.run, daemon=True)
            self._thread.start()

        def wait(self, timeout=None):
            if self._thread is not None:
                self._thread.join(timeout)
            return True

        def isRunning(self):
            return self._thread is not None and self._thread.is_alive()

        def requestInterruption(self):
            return None

        def isInterruptionRequested(self):
            return False

        def setParent(self, *args, **kwargs):
            return None

        def run(self):
            raise NotImplementedError

    class QTimer:
        def __init__(self, *args, **kwargs):
            pass

        def start(self, *args, **kwargs):
            return None

        def stop(self):
            return None

        def setInterval(self, *args, **kwargs):
            return None

        def setSingleShot(self, *args, **kwargs):
            return None

        def timeout(self, *args, **kwargs):
            return None

        @staticmethod
        def singleShot(*args, **kwargs):
            return None

    class Qt:
        class AlignmentFlag:
            pass

        class ItemDataRole:
            pass

    def Slot(*args, **kwargs):
        def deco(fn):
            return fn

        return deco
