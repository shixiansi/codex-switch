"""TerminalViewModel 行为测试（无真实 PySide6 时走 qt_compat 兜底路径）。

覆盖：聚焦/放大书签刷新、放大视图独立输入、清理残留计数。
"""

from __future__ import annotations

import os
import sys
import time
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
for _p in (_SRC, _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

os.environ.setdefault("CODEX_SWITCH_DISABLE_OPEN_URL", "1")

# 复用业务层测试里的假后端，避免重复定义。
from tests.test_terminal import _FakeBackend  # noqa: E402
from codex_switch.ui_v2.viewmodels.terminal import TerminalViewModel  # noqa: E402


class _StubController:
    def __init__(self) -> None:
        self.toasts: list[tuple[str, str]] = []

    def showToast(self, message: str, level: str = "info") -> None:
        self.toasts.append((str(message), str(level)))


class ViewModelTests(unittest.TestCase):
    def _factory(self, store: dict[str, _FakeBackend]):
        def make(command, cwd, env):
            backend = _FakeBackend(command, cwd, env)
            store.setdefault("last", backend)
            return backend
        return make

    def test_zoom_keeps_independent_view(self) -> None:
        store: dict[str, _FakeBackend] = {}
        ctrl = _StubController()
        vm = TerminalViewModel(ctrl)
        # 让跨线程事件（QTimer.singleShot）在事件循环里真正执行。
        try:
            from PySide6.QtCore import QEventLoop
            from PySide6.QtGui import QGuiApplication

            app = QGuiApplication.instance() or QGuiApplication([])
            loop = QEventLoop()

            def pump(secs: float = 0.5) -> None:
                end = time.monotonic() + secs
                while time.monotonic() < end:
                    app.processEvents()
                    time.sleep(0.02)
        except Exception:  # pragma: no cover - 无 PySide6 时退化为短暂等待
            def pump(secs: float = 0.5) -> None:  # type: ignore[assignment]
                time.sleep(secs)
        try:
            sid = vm._manager.create_session("t", "codex", "", backend_factory=self._factory(store))
            vm.focus(sid)
            vm.zoom(sid)
            self.assertEqual(vm.zoomedId, sid)
            store["last"].push(b"zoomed output\n")
            pump(0.5)
            self.assertIn("zoomed output", vm.zoomedScreen)
            # 放大视图独立输入
            vm.sendZoomInput("hello")
            self.assertIn("hello", store["last"].written())
        finally:
            vm.dispose()

    def test_cleanup_orphans_reports_via_toast(self) -> None:
        ctrl = _StubController()
        vm = TerminalViewModel(ctrl)
        try:
            # 注入一个已结束但带子进程的会话摘要
            from codex_switch.ui_v2.terminal.pty_session import (
                PtySession,
                SessionStatus,
            )
            s = PtySession(
                session_id="z", title="z", command="codex", cwd="", env={},
                status=SessionStatus.COMPLETED,
            )
            s.child_pids = {999998}
            vm._manager._sessions["z"] = s
            vm.cleanupOrphans()
            self.assertTrue(any("残留" in m for m, _ in ctrl.toasts))
        finally:
            vm.dispose()


if __name__ == "__main__":
    unittest.main()
