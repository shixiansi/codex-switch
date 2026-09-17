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
            deadline = time.time() + 2.0
            while time.time() < deadline:
                if "hello" in store["last"].written():
                    break
                time.sleep(0.02)
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

    def test_missing_command_reports_error_instead_of_silence(self) -> None:
        """启动不存在的命令必须报错，而不是"点了没反应"。"""
        ctrl = _StubController()
        vm = TerminalViewModel(ctrl)
        errors: list[str] = []
        vm.errorRaised.connect(errors.append)
        try:
            vm.createSession("bad", "definitely_not_a_real_command_xyz_123", "")
            self.assertEqual(vm.sessions, [])
            self.assertTrue(errors, "缺少命令时必须通过错误通道报告")
            self.assertIn("找不到命令", errors[0])
        finally:
            vm.dispose()

    def test_create_project_session_without_project_reports_error(self) -> None:
        ctrl = _StubController()
        vm = TerminalViewModel(ctrl)
        errors: list[str] = []
        vm.errorRaised.connect(errors.append)
        try:
            vm.createProjectSession("", "codex")
            self.assertTrue(errors)
            self.assertIn("项目", errors[0])
        finally:
            vm.dispose()

    def test_stop_session_removes_it_from_list(self) -> None:
        """回归：旧实现只杀进程不摘除登记，会话永远留在列表里清不掉。"""
        store: dict[str, _FakeBackend] = {}
        ctrl = _StubController()
        vm = TerminalViewModel(ctrl)
        try:
            sid = vm._manager.create_session("t", "codex", "", backend_factory=self._factory(store))
            vm._refresh_sessions()
            vm.focus(sid)
            self.assertEqual(len(vm.sessions), 1)

            vm.stopSession(sid)

            self.assertEqual(vm.sessions, [], "停止后会话必须从列表移除")
            self.assertEqual(vm.activeId, "", "停止当前会话后应清空选中")
            self.assertTrue(any("已停止" in m for m, _ in ctrl.toasts))
        finally:
            vm.dispose()

    def test_remove_session_clears_zoom_view(self) -> None:
        store: dict[str, _FakeBackend] = {}
        ctrl = _StubController()
        vm = TerminalViewModel(ctrl)
        try:
            sid = vm._manager.create_session("t", "codex", "", backend_factory=self._factory(store))
            vm._refresh_sessions()
            vm.zoom(sid)
            self.assertEqual(vm.zoomedId, sid)

            vm.removeSession(sid)

            self.assertEqual(vm.zoomedId, "", "清除会话时放大视图也要关闭")
            self.assertEqual(vm.sessions, [])
        finally:
            vm.dispose()

    def test_clear_finished_only_removes_non_running(self) -> None:
        store: dict[str, _FakeBackend] = {}
        ctrl = _StubController()
        vm = TerminalViewModel(ctrl)
        try:
            from codex_switch.ui_v2.terminal.pty_session import PtySession, SessionStatus

            running_id = vm._manager.create_session(
                "running", "codex", "", backend_factory=self._factory(store)
            )
            done = PtySession(
                session_id="done", title="done", command="codex", cwd="", env={},
                status=SessionStatus.COMPLETED,
            )
            vm._manager._sessions["done"] = done
            vm._refresh_sessions()
            self.assertEqual(len(vm.sessions), 2)

            vm.clearFinished()

            remaining = [row["sessionId"] for row in vm.sessions]
            self.assertEqual(remaining, [running_id], "只应清除已结束的会话")
        finally:
            vm.dispose()


class InputAssistViewModelTests(unittest.TestCase):
    """输入辅助在 view model 层的接线。

    逻辑本身在 terminal/input_assist.py 里单测过；这里验证的是
    "界面能调到"：槽注册、按会话取历史、候选随输入变化。
    """

    def _vm(self):
        vm = TerminalViewModel(_StubController())
        self.addCleanup(vm.dispose)
        return vm

    def test_hint_slots_are_registered_for_qml(self) -> None:
        """槽没注册进元对象时，QML 调用会静默失效。"""
        vm = self._vm()
        meta = vm.metaObject()
        names = {bytes(meta.method(i).name()).decode() for i in range(meta.methodCount())}
        for slot in (
            "updateInputHints",
            "historyPrevious",
            "historyNext",
            "resetHistoryCursor",
            "applyHint",
            "selectHint",
            "hideHints",
            "zoomHistoryPrevious",
            "zoomHistoryNext",
        ):
            with self.subTest(slot=slot):
                self.assertIn(slot, names, f"{slot} 没有注册，QML 调不到")

    def test_history_slots_declare_correct_arguments(self) -> None:
        """签名写错会导致 QML 调用被 Qt 丢弃。"""
        vm = self._vm()
        meta = vm.metaObject()
        signatures = {}
        for i in range(meta.methodCount()):
            method = meta.method(i)
            signatures[bytes(method.name()).decode()] = method.methodSignature().data().decode()

        self.assertEqual(signatures.get("historyPrevious"), "historyPrevious(QString)")
        self.assertEqual(signatures.get("historyNext"), "historyNext()")
        self.assertEqual(signatures.get("applyHint"), "applyHint(int)")
        self.assertEqual(signatures.get("zoomHistoryPrevious"), "zoomHistoryPrevious(QString)")

    def test_hints_track_the_input(self) -> None:
        vm = self._vm()
        vm.updateInputHints("/")
        self.assertTrue(vm.hintVisible)
        self.assertGreater(len(vm.hintItems), 3)

        vm.updateInputHints("/mo")
        self.assertEqual([item["name"] for item in vm.hintItems], ["/model"])

        vm.updateInputHints("普通文字")
        self.assertFalse(vm.hintVisible)

    def test_apply_hint_returns_the_command(self) -> None:
        vm = self._vm()
        vm.updateInputHints("/")
        self.assertEqual(vm.applyHint(0), "/model")
        self.assertEqual(vm.applyHint(999), "", "越界应返回空而不是抛错")

    def test_select_hint_wraps_around(self) -> None:
        vm = self._vm()
        vm.updateInputHints("/")
        count = len(vm.hintItems)
        vm.selectHint(count + 1)
        self.assertEqual(vm.hintSelected, 1)

    def test_history_is_per_session(self) -> None:
        """放大窗口必须用被放大会话的历史，否则会翻出别的会话的消息。"""
        store: dict[str, _FakeBackend] = {}

        def make(command, cwd, env):
            backend = _FakeBackend(command, cwd, env)
            store.setdefault("last", backend)
            return backend

        vm = self._vm()
        a = vm._manager.create_session("a", "codex", "", backend_factory=make)
        b = vm._manager.create_session("b", "codex", "", backend_factory=make)

        vm.focus(a)
        vm.sendInput("给 A 的消息")
        vm.zoom(b)
        vm.sendZoomInput("给 B 的消息")

        self.assertEqual(vm.historyPrevious(""), "给 A 的消息",
                         "主视图的历史应来自 activeId")
        self.assertEqual(vm.zoomHistoryPrevious(""), "给 B 的消息",
                         "放大视图的历史应来自 zoomedId")

    def test_history_previous_returns_empty_without_session(self) -> None:
        vm = self._vm()
        self.assertEqual(vm.historyPrevious("草稿"), "")
        self.assertEqual(vm.historyNext(), "")


if __name__ == "__main__":
    unittest.main()
