"""PySide6 + QML user interface for Codex Switch.

The package is deliberately isolated from the legacy Tk UI and must stay
importable without Qt installed (see ``qt_compat``). Business modules remain the
source of truth; view models expose immutable, QML-friendly snapshots, and all
slow work runs on the Qt thread pool.

Layout:
* ``app``         – QApplication/QQmlApplicationEngine bootstrap
* ``controller``  – the single QML boundary (signals, threading, drawers)
* ``workspace``   – Qt-free business orchestration
* ``viewmodels``  – one model per functional area
* ``workers``     – background task primitives
* ``qml``         – AppShell, components, pages and theme tokens
"""

from .app import run_app
from .controller import AppController
from .errors import FormError, WorkspaceError
from .workspace import Workspace

__all__ = ["AppController", "FormError", "Workspace", "WorkspaceError", "run_app"]
