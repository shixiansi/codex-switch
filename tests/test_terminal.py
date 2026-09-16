"""AI 终端业务层测试（无 Qt 依赖，使用假 PTY 后端）。

覆盖：屏幕文本累积、可选项检测、会话创建/输出/退出事件、整树回收零残留。
"""

from __future__ import annotations

import os
import sys
import threading
import time
import unittest
from pathlib import Path

# 让测试模块不依赖 conftest 即可找到 codex_switch 包（与 tests/helpers.py 一致）。
_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
for _p in (_SRC, _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

os.environ.setdefault("CODEX_SWITCH_DISABLE_OPEN_URL", "1")

from codex_switch.ui_v2.terminal import TerminalManager
from codex_switch.ui_v2.terminal.completion import detect_choice
from codex_switch.ui_v2.terminal.pty_session import PtySession, SessionStatus, _Backend
from codex_switch.ui_v2.terminal.screen import TerminalScreen


class _FakeBackend(_Backend):
    """用一个可手动驱动的缓冲区模拟 PTY 后端。"""

    def __init__(self, command: str, cwd: str, env: dict[str, str]) -> None:
        self._buf = b""
        self._alive = True
        self._pid = 4242
        self._lock = threading.Lock()

    def read(self) -> bytes:
        with self._lock:
            data = self._buf
            self._buf = b""
        return data

    def write(self, data: str) -> None:
        # 记录写入，便于断言"发送输入"生效。
        with self._lock:
            self._written = getattr(self, "_written", "") + data

    def is_alive(self) -> bool:
        return self._alive

    def pid(self) -> int:
        return self._pid

    def kill(self) -> None:
        self._alive = False

    def push(self, data: bytes) -> None:
        with self._lock:
            self._buf += data

    def written(self) -> str:
        return getattr(self, "_written", "")


class ScreenTests(unittest.TestCase):
    def test_feed_strips_escape_and_splits_lines(self) -> None:
        screen = TerminalScreen()
        screen.feed(b"\x1b[32mHello\x1b[0m\r\nWorld")
        self.assertEqual(screen.text, "Hello\nWorld")

    def test_tail_keeps_last_n(self) -> None:
        screen = TerminalScreen()
        for i in range(10):
            screen.feed(f"line{i}\n".encode())
        tail = screen.tail(3)
        self.assertIn("line9", tail)
        self.assertNotIn("line0", tail)

    def test_pure_control_sequences_render_nothing(self) -> None:
        """回归：CLI 启动横幅常常只是一堆控制序列，旧实现会渲染成空/乱码。"""
        screen = TerminalScreen()
        screen.feed(b"\x1b[1t\x1b[c\x1b[?1004h\x1b[?9001h")
        self.assertEqual(screen.text, "")

    def test_cursor_addressed_repaint(self) -> None:
        """回归：CLI 用 ESC[row;colH 重绘界面，必须按光标落字而不是顺序追加。"""
        screen = TerminalScreen()
        screen.feed(b"hello\r\nworld")
        screen.feed(b"\x1b[1;1HREPLACED")
        lines = screen.text.split("\n")
        self.assertEqual(lines[0], "REPLACED")
        self.assertEqual(lines[1], "world")

    def test_multibyte_split_across_chunks(self) -> None:
        """回归：PTY 读取边界会切开中文字符，不能出现 U+FFFD。"""
        screen = TerminalScreen()
        raw = "中文测试".encode("utf-8")
        screen.feed(raw[:3])
        screen.feed(raw[3:])
        self.assertEqual(screen.text, "中文测试")
        self.assertNotIn("\ufffd", screen.text)

    def test_last_line_preview(self) -> None:
        screen = TerminalScreen()
        screen.feed("第一行\n第二行\n".encode())
        self.assertEqual(screen.last_line, "第二行")


class CompletionTests(unittest.TestCase):
    def test_confirm_prompt(self) -> None:
        awaiting, choices = detect_choice("Overwrite file? [Y/n] ")
        self.assertTrue(awaiting)
        self.assertEqual(choices, ["是", "否"])

    def test_numbered_options(self) -> None:
        awaiting, choices = detect_choice("请选择：\n› 1. Yes\n  2. No\n  3. Cancel")
        self.assertTrue(awaiting)
        self.assertEqual(choices, ["Yes", "No", "Cancel"])

    def test_no_prompt(self) -> None:
        awaiting, choices = detect_choice("Normal output line")
        self.assertFalse(awaiting)
        self.assertEqual(choices, [])

    def test_input_prompt_is_not_a_choice(self) -> None:
        """回归：Codex 的输入提示符 `›` 曾被误判成选项，弹出无意义的选项条。"""
        awaiting, choices = detect_choice("› Ask Codex to do anything")
        self.assertFalse(awaiting, "输入提示符不是选项")
        self.assertEqual(choices, [])

    def test_echoed_user_input_is_not_a_choice(self) -> None:
        awaiting, choices = detect_choice("› 你好\n\n› 添加本地收藏，现在收藏夹是账号上的")
        self.assertFalse(awaiting, "用户回显不是选项")
        self.assertEqual(choices, [])

    def test_paragraph_numbers_are_not_a_choice(self) -> None:
        """正文里的编号（不从 1 连续递增）不应被当成菜单。"""
        awaiting, choices = detect_choice("步骤\n1. 先做 A\n3. 再做 B\n7. 最后 C")
        self.assertFalse(awaiting)
        self.assertEqual(choices, [])


class ManagerTests(unittest.TestCase):
    def _factory(self, store: dict[str, _FakeBackend]):
        def make(command, cwd, env):
            backend = _FakeBackend(command, cwd, env)
            store.setdefault("last", backend)
            return backend
        return make

    def test_create_emits_status_and_streams_output(self) -> None:
        events: list[tuple[str, str, dict]] = []
        store: dict[str, _FakeBackend] = {}
        mgr = TerminalManager(on_event=lambda sid, ev, pl: events.append((sid, ev, pl)))
        mgr.start()
        try:
            sid = mgr.create_session("t", "codex", "", backend_factory=self._factory(store))
            self.assertTrue(any(e[1] == "status" for e in events))
            store["last"].push(b"hello world\n")
            time.sleep(0.4)
            self.assertIn("hello world", mgr.screen_text(sid))
        finally:
            mgr.shutdown()

    def test_input_writes_crlf(self) -> None:
        store: dict[str, _FakeBackend] = {}
        mgr = TerminalManager()
        mgr.start()
        try:
            sid = mgr.create_session("t", "codex", "", backend_factory=self._factory(store))
            mgr.send_input(sid, "y")
            self.assertIn("y\r\n", store["last"].written())
        finally:
            mgr.shutdown()

    def test_finish_emits_terminal_status(self) -> None:
        events: list[tuple[str, str, dict]] = []
        store: dict[str, _FakeBackend] = {}
        mgr = TerminalManager(on_event=lambda sid, ev, pl: events.append((sid, ev, pl)))
        mgr.start()
        try:
            sid = mgr.create_session("t", "codex", "", backend_factory=self._factory(store))
            store["last"]._alive = False  # 模拟进程退出
            time.sleep(0.4)
            statuses = [pl["status"] for _, ev, pl in events if ev == "status"]
            self.assertTrue(any(s in {"completed", "failed", "stopped"} for s in statuses))
        finally:
            mgr.shutdown()

    def test_cleanup_orphans_reaps_dead_tree(self) -> None:
        # 一个已结束但登记了子进程的会话，cleanup_orphans 应报告清理。
        mgr = TerminalManager()
        session = PtySession(
            session_id="x", title="x", command="codex", cwd="", env={},
            status=SessionStatus.COMPLETED,
        )
        session.child_pids = {999999}
        mgr._sessions["x"] = session
        cleaned = mgr.cleanup_orphans()
        self.assertTrue(any(c["sessionId"] == "x" for c in cleaned))


class WinPtyBackendContractTests(unittest.TestCase):
    """pywinpty 3.x 的 API 契约回归测试。

    该库在 3.0 把导入模块从 ``pywinpty`` 改名为 ``winpty``、类从 ``PTYProcess``
    改为 ``PtyProcess``；此前代码写死旧名字，导致每次启动都 ModuleNotFoundError，
    而异常被吞掉后表现为"点击启动没反应"。这里锁定真实安装的 API 形态。
    """

    @unittest.skipIf(os.name != "nt", "ConPTY 后端仅 Windows 可用")
    def test_can_construct_real_backend(self) -> None:
        from codex_switch.ui_v2.terminal.pty_session import _WinPtyBackend

        backend = _WinPtyBackend("cmd.exe /c echo CONTRACT_OK", "", {})
        try:
            self.assertGreater(backend.pid(), 0)
            data = b""
            for _ in range(80):
                data += backend.read()
                if not backend.is_alive():
                    break
                time.sleep(0.05)
            self.assertIn(b"CONTRACT_OK", data)
        finally:
            backend.kill()

    @unittest.skipIf(os.name != "nt", "ConPTY 后端仅 Windows 可用")
    def test_read_is_non_blocking(self) -> None:
        """回归：pywinpty.read() 是阻塞 recv，空闲时会把轮询线程永久挂住，
        导致输出读不到、退出也检测不到（界面表现为"什么都没有"）。"""
        from codex_switch.ui_v2.terminal.pty_session import _WinPtyBackend

        backend = _WinPtyBackend("cmd.exe /k", "", {})
        try:
            # 排空启动横幅
            for _ in range(40):
                backend.read()
                time.sleep(0.05)
            # CLI 空闲时 read() 必须立即返回，而不是阻塞。
            start = time.monotonic()
            for _ in range(30):
                backend.read()
            elapsed = time.monotonic() - start
            self.assertLess(elapsed, 1.0, "空闲读取不应阻塞")
        finally:
            backend.kill()

    def test_winpty_module_importable(self) -> None:
        # 只要装了 pywinpty，就必须能通过 winpty（3.x）或 pywinpty（2.x）导入。
        try:
            import winpty  # noqa: F401
        except ImportError:
            try:
                import pywinpty  # noqa: F401
            except ImportError:
                self.skipTest("pywinpty 未安装")

    @unittest.skipIf(os.name != "nt", "ConPTY 后端仅 Windows 可用")
    def test_backend_health_check_detects_missing_native_files(self) -> None:
        """回归：冻结包曾缺少 winpty 原生文件，却只在空白界面里体现。

        check_pty_backend 必须能报出具体缺了什么，供界面直接提示。
        """
        from unittest.mock import patch

        from codex_switch.ui_v2.terminal.pty_session import check_pty_backend

        # 正常环境下应为空
        self.assertEqual(check_pty_backend(), "")
        # 模拟原生文件缺失
        with patch("pathlib.Path.exists", lambda self: False):
            issue = check_pty_backend()
        self.assertIn("winpty", issue)


if __name__ == "__main__":
    unittest.main()
