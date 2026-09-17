"""终端风险审查的通知、提示音与界面接线测试。

分三层：

* **通知/提示音模块**：无 Qt 环境、托盘不可用、发声失败时都必须**安全降级**，
  不能抛异常也不能让进程崩溃；
* **controller 桥**：授权弹窗的规格内容、取消等于拒绝；
* **view model 队列**：多个会话同时要求授权时串行展示、先入先出。

这些测试不依赖真实托盘/声卡：能在无头环境下跑，断言的是"降级路径正确"，
而不是"真的弹出了气泡"。
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
# 无头运行，避免测试环境里真的弹窗；同时这也是"托盘不可用"的真实降级路径。
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tests.helpers import workspace_tempdir  # noqa: E402
from tests.test_terminal import _FakeBackend  # noqa: E402

from codex_switch.ui_v2.terminal.notifier import SystemNotifier, icon_path  # noqa: E402
from codex_switch.ui_v2.terminal.sound import SoundPlayer, is_supported  # noqa: E402


class NotifierTests(unittest.TestCase):
    def test_notify_without_application_is_safe(self) -> None:
        """没有 QApplication 时不能崩。

        这条是**崩溃回归测试**：``QSystemTrayIcon`` 在没有应用实例时被构造或
        查询，在 Windows 上是**访问违例**（进程直接退出），而不是抛异常——
        try/except 兜不住，因此必须靠显式的前置检查。子进程里验证。
        """
        import subprocess

        code = (
            "import sys; sys.path.insert(0, 'src')\n"
            "from codex_switch.ui_v2.terminal.notifier import SystemNotifier\n"
            "n = SystemNotifier()\n"
            "assert n.is_available() is False\n"
            "assert n.notify('t', 'b') is False\n"
            "n.hide()\n"
            "print('SAFE')\n"
        )
        proc = subprocess.run(
            [sys.executable, "-c", code],
            cwd=str(_ROOT),
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(proc.returncode, 0, f"进程异常退出：{proc.stderr[-400:]}")
        self.assertIn("SAFE", proc.stdout)

    def test_unavailable_notifier_reports_reason(self) -> None:
        notifier = SystemNotifier()
        self.assertFalse(notifier.is_available())
        self.assertTrue(notifier.unavailable_reason, "应说明不可用的原因")

    def test_icon_asset_exists(self) -> None:
        """托盘图标必须真的存在，否则气泡会没图标。"""
        self.assertTrue(icon_path().exists(), f"缺少图标：{icon_path()}")

    def test_click_callback_is_optional(self) -> None:
        notifier = SystemNotifier()
        notifier.set_click_callback(None)
        notifier.hide()  # 不应抛异常


class SoundTests(unittest.TestCase):
    def test_disabled_sound_is_silent(self) -> None:
        player = SoundPlayer(enabled=False)
        self.assertFalse(player.play(urgent=True))
        self.assertEqual(player.play_count, 0)

    def test_cooldown_suppresses_repeats(self) -> None:
        """一串菜单同时冒出来时不该连珠炮响。"""
        player = SoundPlayer(cooldown_seconds=5.0, enabled=True)
        now = 1000.0
        # 直接给定时刻，避免依赖真实时间。
        self.assertTrue(player.play(urgent=True, now=now))
        self.assertFalse(player.play(urgent=True, now=now + 1.0))
        self.assertTrue(player.play(urgent=True, now=now + 6.0))
        self.assertEqual(player.play_count, 2)

    def test_configure_can_disable(self) -> None:
        player = SoundPlayer(enabled=True)
        player.configure(enabled=False)
        self.assertFalse(player.play(urgent=True))

    def test_play_is_safe_on_any_platform(self) -> None:
        """即使平台不支持发声也必须安全返回，不能抛异常。"""
        player = SoundPlayer(cooldown_seconds=0.0)
        player.configure(strong=True)
        result = player.play(urgent=True)
        if is_supported():
            self.assertIn(result, (True, False))
        else:
            self.assertFalse(result)


class _StubController:
    """最小 controller 替身：只实现 view model 会用到的那几个方法。"""

    def __init__(self) -> None:
        self.toasts: list[tuple[str, str]] = []
        self.notifications: list[tuple[str, str, bool]] = []
        self.presented: list[dict] = []
        self.policy_payloads: list[dict] = []

    def showToast(self, message: str, level: str = "info") -> None:
        self.toasts.append((str(message), str(level)))

    def notifyTerminalReview(self, title: str, body: str, urgent: bool) -> None:
        self.notifications.append((str(title), str(body), bool(urgent)))

    def pendingTerminalReview(self) -> dict:
        return dict(self.presented[0]) if self.presented else {}

    def presentTerminalReview(self, review) -> None:
        self.presented = [dict(review)]

    def clearTerminalReview(self) -> None:
        self.presented = []

    def applyTerminalAudioPolicy(self, payload) -> None:
        self.policy_payloads.append(dict(payload or {}))


class _ViewModelHarness(unittest.TestCase):
    def _pump(self, app, seconds: float) -> None:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            app.processEvents()
            time.sleep(0.02)

    def _make_vm(self, controller):
        """构造 view model；没有 PySide6 时退化为直接等待。"""
        from codex_switch.ui_v2.viewmodels.terminal import TerminalViewModel

        try:
            from PySide6.QtWidgets import QApplication

            app = QApplication.instance() or QApplication([])
        except Exception:  # pragma: no cover - 无 Qt 环境
            app = None
        vm = TerminalViewModel(controller)
        self.addCleanup(vm.dispose)
        return vm, app

    def _start(self, vm, controller, menu: bytes, *, timeout: float = 4.0) -> tuple[str, _FakeBackend]:
        store: dict[str, _FakeBackend] = {}

        def make(command, cwd, env):
            backend = _FakeBackend(command, cwd, env)
            store["last"] = backend
            return backend

        session_id = vm._manager.create_session("t", "codex", "", backend_factory=make)
        vm.focus(session_id)
        store["last"].push(menu)
        return session_id, store["last"]


class ViewModelReviewTests(_ViewModelHarness):
    RISKY = "› 1. Delete all files\n  2. No, cancel\n".encode()
    SAFE = "› 1. Yes, continue\n  2. No, quit\n".encode()

    def test_pending_review_is_presented_and_notified(self) -> None:
        ctrl = _StubController()
        vm, app = self._make_vm(ctrl)
        session_id, backend = self._start(vm, ctrl, self.RISKY)
        if app is not None:
            self._pump(app, 2.0)
        else:  # pragma: no cover
            time.sleep(1.5)

        self.assertEqual(vm.reviewPendingCount, 1, "应记录一个待授权项")
        self.assertTrue(ctrl.presented, "应把待授权项推给 controller 弹窗")
        self.assertTrue(ctrl.notifications, "应发出通知/提示音请求")
        self.assertEqual(backend.written(), "", "授权前不应发送任何按键")

    def test_approve_through_controller_spec_sends_once(self) -> None:
        ctrl = _StubController()
        vm, app = self._make_vm(ctrl)
        session_id, backend = self._start(vm, ctrl, self.RISKY)
        if app is not None:
            self._pump(app, 2.0)
        else:  # pragma: no cover
            time.sleep(1.5)

        vm.resolveReview(session_id, "approve")
        if app is not None:
            self._pump(app, 2.0)
        else:  # pragma: no cover
            time.sleep(1.5)
        self.assertIn("1", backend.written())
        self.assertEqual(vm.reviewPendingCount, 0)

    def test_deny_through_view_model_sends_nothing(self) -> None:
        ctrl = _StubController()
        vm, app = self._make_vm(ctrl)
        session_id, backend = self._start(vm, ctrl, self.RISKY)
        if app is not None:
            self._pump(app, 2.0)
        else:  # pragma: no cover
            time.sleep(1.5)

        vm.resolveReview(session_id, "deny")
        if app is not None:
            self._pump(app, 1.5)
        else:  # pragma: no cover
            time.sleep(1.2)
        self.assertEqual(backend.written(), "")

    def test_queue_presents_one_at_a_time(self) -> None:
        """两个会话同时要求授权时，弹窗一次只展示一个（先进先出）。"""
        ctrl = _StubController()
        vm, app = self._make_vm(ctrl)

        store: dict[str, _FakeBackend] = {}

        def make(command, cwd, env):
            backend = _FakeBackend(command, cwd, env)
            store.setdefault("all", []).append(backend)
            return backend

        first = vm._manager.create_session("a", "codex", "", backend_factory=make)
        second = vm._manager.create_session("b", "codex", "", backend_factory=make)
        store["all"][0].push(self.RISKY)
        store["all"][1].push(self.RISKY)
        if app is not None:
            self._pump(app, 2.5)
        else:  # pragma: no cover
            time.sleep(2.0)

        self.assertEqual(vm.reviewPendingCount, 2, "两个会话都应记录待授权项")
        # 一次只推一个：不能出现"后者覆盖前者"。
        self.assertEqual(len(ctrl.presented), 1)
        self.assertEqual(ctrl.presented[0]["sessionId"], first, "应展示最先出现的那个")

        vm.resolveReview(first, "deny")
        if app is not None:
            self._pump(app, 1.5)
        else:  # pragma: no cover
            time.sleep(1.2)
        self.assertTrue(ctrl.presented, "第一个解决后应接着展示第二个")
        self.assertEqual(ctrl.presented[0]["sessionId"], second)

    def test_mode_off_clears_pending_reviews(self) -> None:
        """切到"关闭"后不该再有授权框冒出来。"""
        ctrl = _StubController()
        vm, app = self._make_vm(ctrl)
        session_id, backend = self._start(vm, ctrl, self.RISKY)
        if app is not None:
            self._pump(app, 2.0)
        else:  # pragma: no cover
            time.sleep(1.5)
        self.assertEqual(vm.reviewPendingCount, 1)

        vm.setReviewMode("off")
        self.assertEqual(vm.reviewPendingCount, 0)
        self.assertEqual(vm.reviewMode, "off")
        self.assertFalse(vm.autoAnswer)

    def test_mode_switch_pushes_audio_policy(self) -> None:
        """提示音等只有界面层能处理的项要同步给 controller。"""
        ctrl = _StubController()
        vm, app = self._make_vm(ctrl)
        vm.setReviewMode("strict")
        self.assertTrue(ctrl.policy_payloads, "应把策略推给 controller")
        self.assertIn("soundEnabled", ctrl.policy_payloads[-1])

    def test_safe_menu_does_not_create_review(self) -> None:
        """安全默认项不该产生任何授权请求（否则闸门会变成噪音源）。"""
        ctrl = _StubController()
        vm, app = self._make_vm(ctrl)
        _session_id, backend = self._start(vm, ctrl, self.SAFE)
        if app is not None:
            deadline = time.monotonic() + 3.0
            while time.monotonic() < deadline and "\r" not in backend.written():
                app.processEvents()
                time.sleep(0.02)
        else:  # pragma: no cover
            time.sleep(1.5)
        self.assertIn("1", backend.written())
        self.assertEqual(vm.reviewPendingCount, 0)
        self.assertFalse(ctrl.presented)


class ControllerBridgeTests(unittest.TestCase):
    """controller 的授权桥：规格内容与取消语义。"""

    def _controller(self, root: Path):
        from codex_switch.storage import ProfileStore
        from codex_switch.ui_v2.controller import AppController
        from codex_switch.ui_v2.workspace import Workspace

        return AppController(workspace=Workspace(store=ProfileStore(root)))

    def test_review_spec_exposes_what_will_be_sent(self) -> None:
        with workspace_tempdir() as root:
            controller = self._controller(root)
            controller.presentTerminalReview(
                {
                    "sessionId": "s1",
                    "title": "会话",
                    "label": "1. Delete all files",
                    "payload": "1",
                    "prompt": "Delete all files?",
                    "reason": "高风险",
                    "risk": "risky",
                    "riskLabel": "高风险",
                }
            )
            self.assertTrue(controller.terminalReviewOpen)
            spec = controller.pendingConfirm
            # 授权请求复用**唯一**那个共享确认弹窗（项目刻意只保留一个实例）。
            self.assertIn("AI 终端授权", spec["title"])
            self.assertIn("1. Delete all files", spec["message"])
            self.assertIn("Delete all files?", spec["detail"])
            self.assertEqual(spec["confirmText"], "允许本次")
            self.assertEqual(spec["extraText"], "本会话允许此类")
            self.assertTrue(spec["danger"], "高风险应使用危险样式")

    def test_cancel_is_deny_not_release(self) -> None:
        """取消/关闭弹窗必须等同拒绝——绝不能当成默认放行。"""
        with workspace_tempdir() as root:
            controller = self._controller(root)
            resolved: list[tuple[str, str]] = []
            controller.terminal.resolveReview = lambda session_id, decision: resolved.append(
                (session_id, decision)
            )
            controller.presentTerminalReview({"sessionId": "s1", "title": "T", "reason": "r"})
            controller.cancelPending()
            self.assertEqual(resolved, [("s1", "deny")])
            self.assertFalse(controller.terminalReviewOpen)

    def test_confirm_sends_approve_and_clears(self) -> None:
        with workspace_tempdir() as root:
            controller = self._controller(root)
            resolved: list[tuple[str, str]] = []
            controller.terminal.resolveReview = lambda session_id, decision: resolved.append(
                (session_id, decision)
            )
            controller.presentTerminalReview({"sessionId": "s1", "title": "T", "reason": "r"})
            controller.confirmPending()
            self.assertEqual(resolved, [("s1", "approve")])
            self.assertFalse(controller.terminalReviewOpen)

    def test_extra_button_sends_allow_kind(self) -> None:
        """第三个按钮"本会话允许此类"要走到 allow_kind，而不是当成一次批准。"""
        with workspace_tempdir() as root:
            controller = self._controller(root)
            resolved: list[tuple[str, str]] = []
            controller.terminal.resolveReview = lambda session_id, decision: resolved.append(
                (session_id, decision)
            )
            controller.presentTerminalReview({"sessionId": "s1", "title": "T", "reason": "r"})
            controller.extraPending()
            self.assertEqual(resolved, [("s1", "allow_kind")])

    def test_full_mode_requires_confirmation_and_is_not_blocked(self) -> None:
        """开启"完全放行"要二次确认，但该确认必须真的能点（不能被 warning 卡死）。"""
        with workspace_tempdir() as root:
            controller = self._controller(root)
            controller.requestTerminalFullMode()
            spec = controller.pendingConfirm
            self.assertTrue(spec, "应弹出确认")
            self.assertEqual(spec["warning"], "", "warning 会隐藏确认按钮，这里必须为空")
            controller.confirmPending()
            self.assertEqual(controller.terminal.reviewMode, "full")


if __name__ == "__main__":
    unittest.main()
