"""Small compatibility layer so view-models remain importable without Qt."""

from __future__ import annotations


try:  # pragma: no cover - exercised only when PySide6 is installed
    from PySide6.QtCore import Property, QObject, QRunnable, QThreadPool, QTimer, Qt, QUrl, Signal, Slot  # type: ignore
    from PySide6.QtGui import QDesktopServices, QGuiApplication, QIcon  # type: ignore
    from PySide6.QtQml import QQmlApplicationEngine  # type: ignore

    # QApplication is imported eagerly and deliberately: the terminal's system
    # notifications go through QSystemTrayIcon (a QtWidgets class) which crashes
    # the process under a plain QGuiApplication. See ui_v2/app.py.
    try:
        from PySide6.QtWidgets import QApplication, QFileDialog  # type: ignore
    except ImportError:  # pragma: no cover - widgets-less Qt build
        QApplication = None  # type: ignore[assignment]

        class QFileDialog:  # type: ignore[no-redef]
            @staticmethod
            def getExistingDirectory(*args, **kwargs):
                return ""

            @staticmethod
            def getOpenFileName(*args, **kwargs):
                return "", ""

    try:
        from PySide6.QtQuickControls2 import QQuickStyle  # type: ignore
    except ImportError:  # pragma: no cover
        QQuickStyle = None  # type: ignore[assignment]
    QT_AVAILABLE = True
except ImportError:  # pragma: no cover - deterministic fallback
    QT_AVAILABLE = False

    class _BoundSignal:
        def __init__(self) -> None:
            self._callbacks: list = []

        def connect(self, callback, *args, **kwargs):
            self._callbacks.append(callback)
            return callback

        def emit(self, *args, **kwargs):
            for callback in tuple(self._callbacks):
                callback(*args, **kwargs)

    class Signal:
        def __init__(self, *args, **kwargs) -> None:
            self._name = ""

        def __set_name__(self, owner, name):
            self._name = f"__signal_{name}"

        def __get__(self, instance, owner=None):
            if instance is None:
                return self
            signal = instance.__dict__.get(self._name)
            if signal is None:
                signal = _BoundSignal()
                instance.__dict__[self._name] = signal
            return signal

    def Slot(*types, **kwargs):
        def decorator(function):
            return function

        return decorator

    def Property(type_, fget=None, fset=None, notify=None, constant=False):
        if fget is not None:
            return property(fget, fset)

        def decorator(func):
            return property(func, fset)

        return decorator

    class QObject:
        def __init__(self, parent=None) -> None:
            self._parent = parent

    class QRunnable:
        def run(self) -> None:
            raise NotImplementedError

    class QThreadPool:
        _instance = None

        @classmethod
        def globalInstance(cls):
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

        def start(self, runnable):
            runnable.run()

    class QTimer:
        @staticmethod
        def singleShot(_msecs, callback):
            callback()

    class Qt:
        class ConnectionType:
            QueuedConnection = 0
            AutoConnection = 0

        QueuedConnection = 0
        AutoConnection = 0

    class QUrl:
        def __init__(self, value=""):
            self._value = value

        @classmethod
        def fromLocalFile(cls, path):
            return cls(str(path))

        def toString(self):
            return str(self._value)

    class QGuiApplication:
        def __init__(self, _args=None):
            self._args = _args or []

        def exec(self):
            return 0

        def aboutToQuit(self):
            return Signal()

    class QApplicationFallback(QGuiApplication):
        pass

    # When QtWidgets is missing there is no usable QApplication; expose a
    # QGuiApplication subclass so callers can keep a single code path.
    QApplication = QApplicationFallback  # type: ignore[assignment]

    class QQmlApplicationEngine:
        def __init__(self):
            self._root = []

        def rootObjects(self):
            return self._root

        def rootContext(self):
            return self

        def setContextProperty(self, _name, _value):
            return None

        def addImportPath(self, _path):
            return None

        def load(self, _path):
            return None

    class QFileDialog:
        @staticmethod
        def getExistingDirectory(*args, **kwargs):
            return ""

        @staticmethod
        def getOpenFileName(*args, **kwargs):
            return "", ""

    class QDesktopServices:
        @staticmethod
        def openUrl(_url):
            return False

    class QIcon:
        def __init__(self, *_args, **_kwargs):
            return None

    QQuickStyle = None


__all__ = [
    "Property",
    "QApplication",
    "QDesktopServices",
    "QFileDialog",
    "QGuiApplication",
    "QIcon",
    "QObject",
    "QQmlApplicationEngine",
    "QQuickStyle",
    "QRunnable",
    "QThreadPool",
    "QTimer",
    "QUrl",
    "Qt",
    "Signal",
    "Slot",
    "QT_AVAILABLE",
]
