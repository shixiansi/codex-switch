"""QML application bootstrap.

QML is loaded from the package directory; under PyInstaller the same tree is
bundled through ``datas``, so this single code path works in both cases.
"""

from __future__ import annotations

from pathlib import Path
import os
import sys

from .controller import AppController
from .qt_compat import (
    QT_AVAILABLE,
    QApplication,
    QGuiApplication,
    QQmlApplicationEngine,
    QQuickStyle,
    QTimer,
    QUrl,
)
from .single_instance import acquire_single_instance, release_single_instance

QML_ROOT = Path(__file__).with_name("qml")
QML_ENTRYPOINT = QML_ROOT / "AppShell.qml"

QML_IMPORT_PATHS = (QML_ROOT, QML_ROOT.parent)

# The native Windows style refuses QML customisation of background/contentItem,
# so the cross-platform Basic style is required for a fully themed UI.
QML_STYLE = "Basic"


def build_application(argv: list[str]):
    """Create the application object, preferring ``QApplication``.

    Why not ``QGuiApplication``: ``QSystemTrayIcon.showMessage`` — used for the
    terminal's risk-review notifications — is a QtWidgets API. Under a plain
    ``QGuiApplication`` it does not raise, it **crashes the process** with an
    access violation on Windows. Since system notifications are a product
    requirement, the app is created as a ``QApplication`` (a strict subclass of
    ``QGuiApplication``, so nothing else changes).

    Falls back to ``QGuiApplication`` when QtWidgets is unavailable; the
    notifier detects that case and degrades to in-app toasts.
    """
    if QApplication is not None:
        existing = QApplication.instance()
        if existing is not None:
            return existing
        try:
            return QApplication(argv)
        except Exception:  # noqa: BLE001 - fall back to the GUI-only base class
            pass
    return QGuiApplication.instance() or QGuiApplication(argv)


def configure_style() -> None:
    """Select the non-native Qt Quick Controls style (call before QML loads)."""
    if QQuickStyle is None:
        return
    try:
        QQuickStyle.setStyle(QML_STYLE)
    except Exception:  # noqa: BLE001 - fall back to the default style
        pass


def _configure_environment() -> None:
    """Set Qt defaults before the application object is created."""
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", QML_STYLE)


def build_engine(controller: AppController) -> QQmlApplicationEngine:
    """Create an engine with the controller wired into the root context."""
    engine = QQmlApplicationEngine()
    for path in reversed(QML_IMPORT_PATHS):
        engine.addImportPath(str(path))
    context = engine.rootContext()
    context.setContextProperty("app", controller)
    context.setContextProperty("appController", controller)
    context.setContextProperty("theme", controller.theme)
    context.setContextProperty("dashboardModel", controller.dashboard)
    context.setContextProperty("profilesModel", controller.profiles)
    context.setContextProperty("projectsModel", controller.projects)
    context.setContextProperty("proxyModel", controller.proxy)
    context.setContextProperty("toolsModel", controller.tools)
    context.setContextProperty("settingsModel", controller.settings)
    context.setContextProperty("scriptsModel", controller.scripts)
    context.setContextProperty("terminalModel", controller.terminal)
    context.setContextProperty("pluginsModel", controller.plugins)
    return engine


def load_qml(engine: QQmlApplicationEngine, entrypoint: Path | None = None) -> bool:
    target = Path(entrypoint or QML_ENTRYPOINT)
    if not target.exists():
        raise RuntimeError(f"未找到 QML 入口文件：{target}")
    engine.load(QUrl.fromLocalFile(str(target)))
    return bool(engine.rootObjects())


def run_app(argv: list[str] | None = None, *, workspace=None, entrypoint: Path | None = None) -> int:
    """Start the QML application and return Qt's exit code."""
    if not QT_AVAILABLE:
        raise RuntimeError("PySide6 未安装，无法启动新的 QML 界面。请先安装 requirements.txt。")

    # Two instances would race on profiles.json and on the proxy port.
    if not acquire_single_instance():
        return 0

    try:
        _configure_environment()
        app = build_application(argv if argv is not None else sys.argv)
        configure_style()
        app.setOrganizationName("Codex Switch")
        app.setApplicationName("Codex Switch")
        app.setApplicationDisplayName("Codex Switch")

        controller = AppController(workspace=workspace)
        engine = build_engine(controller)
        if not load_qml(engine, entrypoint):
            raise RuntimeError(f"QML 加载失败：{Path(entrypoint or QML_ENTRYPOINT)}")

        # Keep strong references: the engine only holds weak context properties
        # for Python objects, so a local-only controller could be collected.
        app._codex_switch_controller = controller  # type: ignore[attr-defined]
        app._codex_switch_engine = engine  # type: ignore[attr-defined]

        # Plugins load after the window is up: a slow or broken plugin then
        # delays nothing the user is waiting on, and its failure lands in the
        # plugin centre rather than blocking startup.
        QTimer.singleShot(0, controller.load_plugins)

        app.aboutToQuit.connect(controller.shutdownPlugins)
        app.aboutToQuit.connect(controller.shutdownNotifier)
        app.aboutToQuit.connect(controller.shutdown)
        return app.exec()
    finally:
        release_single_instance()


__all__ = [
    "QML_ENTRYPOINT",
    "QML_IMPORT_PATHS",
    "QML_ROOT",
    "build_application",
    "build_engine",
    "configure_style",
    "load_qml",
    "run_app",
]
