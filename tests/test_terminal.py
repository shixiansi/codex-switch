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
        # 逐次记录写入，便于断言"文本与回车是两次独立写入"。
        self._write_calls: list[str] = []

    def read(self) -> bytes:
        with self._lock:
            data = self._buf
            self._buf = b""
        return data

    def write(self, data: str) -> None:
        # 记录写入，便于断言"发送输入"生效。
        with self._lock:
            self._write_calls.append(data)

    def write_calls(self) -> list[str]:
        with self._lock:
            return list(self._write_calls)

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
        """所有写入按顺序拼接，便于整体断言。"""
        with self._lock:
            return "".join(self._write_calls)


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


class _ManagerBackedTest(unittest.TestCase):
    """需要假 PTY 后端的测试基类。"""

    def _factory(self, store: dict[str, _FakeBackend]):
        def make(command, cwd, env):
            backend = _FakeBackend(command, cwd, env)
            store.setdefault("last", backend)
            return backend

        return make


class TimelineTests(_ManagerBackedTest):
    def test_mark_segment_records_timestamped_snapshot(self) -> None:
        screen = TerminalScreen()
        screen.feed("第一段输出\n".encode())
        self.assertTrue(screen.mark_segment(), "首次打点应新增一段")

        lines = screen.timeline_lines()
        self.assertEqual(len(lines), 1)
        # 形如 "[HH:MM:SS] 第一段输出"
        self.assertRegex(lines[0], r"^\[\d{2}:\d{2}:\d{2}\] ")
        self.assertIn("第一段输出", lines[0])

    def test_identical_snapshot_is_not_duplicated(self) -> None:
        """输出没有变化时不应重复记录，否则时间线会被刷屏。"""
        screen = TerminalScreen()
        screen.feed("内容\n".encode())
        self.assertTrue(screen.mark_segment())
        self.assertFalse(screen.mark_segment(), "内容未变不应再记录")
        self.assertEqual(len(screen.timeline_lines()), 1)

    def test_force_marks_even_when_not_dirty(self) -> None:
        """会话结束时要强制记最后一段。"""
        screen = TerminalScreen()
        screen.feed("收尾内容\n".encode())
        screen.mark_segment()
        self.assertFalse(screen.mark_segment())
        # 内容变化后再 force
        screen.feed("新内容\n".encode())
        self.assertTrue(screen.mark_segment(force=True))

    def test_idle_seconds_tracks_activity(self) -> None:
        screen = TerminalScreen()
        self.assertEqual(screen.idle_seconds, 0.0, "从未收到输出时应为 0")
        screen.feed("x\n".encode())
        time.sleep(0.2)
        self.assertGreater(screen.idle_seconds, 0.1)

    def test_timeline_marks_on_pause_not_only_with_data(self) -> None:
        """回归：时间线打点必须每轮检查，否则 idle 永远为 0、时间线一直为空。"""
        store: dict[str, _FakeBackend] = {}
        mgr = TerminalManager()
        mgr._segment_idle_seconds = 0.3
        mgr.start()
        try:
            sid = mgr.create_session("t", "codex", "", backend_factory=self._factory(store))
            store["last"].push(b"output one\n")
            time.sleep(0.8)  # 期间没有新数据，靠轮询发现"停顿"
            timeline = mgr.timeline_text(sid)
            self.assertIn("output one", timeline)
            self.assertRegex(timeline, r"\[\d{2}:\d{2}:\d{2}\]")
        finally:
            mgr.shutdown()


class ElapsedTests(_ManagerBackedTest):
    def test_elapsed_label_formatting(self) -> None:
        from codex_switch.ui_v2.terminal.manager import _format_elapsed

        self.assertEqual(_format_elapsed(0), "0s")
        self.assertEqual(_format_elapsed(5_000), "5s")
        self.assertEqual(_format_elapsed(65_000), "01m05s")
        self.assertEqual(_format_elapsed(3_725_000), "1h02m05s")

    def test_summary_reports_elapsed(self) -> None:
        store: dict[str, _FakeBackend] = {}
        mgr = TerminalManager()
        mgr.start()
        try:
            sid = mgr.create_session("t", "codex", "", backend_factory=self._factory(store))
            time.sleep(0.25)
            summary = next(s for s in mgr.summaries() if s.session_id == sid)
            self.assertGreater(summary.elapsed_ms, 0)
            self.assertNotEqual(summary.to_dict()["elapsedLabel"], "")
        finally:
            mgr.shutdown()


class AutoAnswerTests(_ManagerBackedTest):
    def test_auto_answer_selects_first_option_once(self) -> None:
        """开启自动应答后，菜单出现即自动选第一项，且同一菜单只答一次。"""
        store: dict[str, _FakeBackend] = {}
        mgr = TerminalManager()
        mgr.auto_answer = True
        mgr.start()
        try:
            sid = mgr.create_session("t", "codex", "", backend_factory=self._factory(store))
            store["last"].push("› 1. Yes, continue\n  2. No, quit\n".encode())
            deadline = time.time() + 2.5
            while time.time() < deadline:
                if "\r" in store["last"].written():
                    break
                time.sleep(0.05)
            self.assertEqual(
                store["last"].written(), "1\r", "应自动选择第 1 项（单 CR 提交）"
            )
            # 同一菜单不应重复应答
            calls_after_first = len(store["last"].write_calls())
            time.sleep(0.8)
            self.assertEqual(
                len(store["last"].write_calls()),
                calls_after_first,
                "同一菜单不应被反复自动选择",
            )
        finally:
            mgr.shutdown()

    def test_auto_answer_disabled_by_default(self) -> None:
        store: dict[str, _FakeBackend] = {}
        mgr = TerminalManager()
        self.assertFalse(mgr.auto_answer, "manager 默认不自动应答")
        mgr.start()
        try:
            sid = mgr.create_session("t", "codex", "", backend_factory=self._factory(store))
            store["last"].push("› 1. Yes\n  2. No\n".encode())
            time.sleep(0.8)
            self.assertEqual(store["last"].written(), "", "关闭时不应自动发送任何输入")
        finally:
            mgr.shutdown()


class CompletionTests(unittest.TestCase):
    def test_confirm_prompt(self) -> None:
        awaiting, choices = detect_choice("Overwrite file? [Y/n] ")
        self.assertTrue(awaiting)
        self.assertEqual(choices, ["是", "否"])

    def test_numbered_options(self) -> None:
        awaiting, choices = detect_choice("请选择：\n› 1. Yes\n  2. No\n  3. Cancel")
        self.assertTrue(awaiting)
        self.assertEqual(choices, ["Yes", "No", "Cancel"])

    def test_real_codex_menu_with_wrapped_description(self) -> None:
        """回归：codex 登录菜单的选项说明会换行成缩进续行。

        早期实现遇到非选项行就停止收集，导致开头带 `>` 标记的那一项被漏掉，
        整个菜单识别失败（用户看到菜单却弹不出选项条）。
        """
        menu = (
            "> 1. Sign in with ChatGPT\n"
            "     Usage included with Plus, Pro plans\n"
            "  2. Sign in with Device Code\n"
            "     Sign in from another device\n"
            "  3. Provide your own API key\n"
            "     Pay for what you use\n"
            "\n  Press enter to continue"
        )
        awaiting, choices = detect_choice(menu)
        self.assertTrue(awaiting)
        self.assertEqual(
            choices,
            ["Sign in with ChatGPT", "Sign in with Device Code", "Provide your own API key"],
        )

    def test_wrapped_reply_list_is_not_a_menu(self) -> None:
        """回归：AI 回复里的普通编号列表不应被判成菜单（无选中标记）。"""
        reply = (
            "你需要做三件事：\n"
            "1. 添加收藏按钮\n"
            "2. 添加本地收藏\n"
            "3. 区分长短视频"
        )
        awaiting, choices = detect_choice(reply)
        self.assertFalse(awaiting, "正文编号列表不是菜单")
        self.assertEqual(choices, [])

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

    def test_input_submits_with_separate_cr(self) -> None:
        """回归：必须"文本"与"单个 CR"分两次写入。

        真实 codex 开启 bracketed paste（ESC[?2004h），同一次写入里的"文本+回车"
        会被当作粘贴而吞掉回车 —— 屏幕上看得到消息，AI 却不开始工作。
        另外发 CRLF 会被当成两次回车，第二条空消息会顶掉请求。
        """
        store: dict[str, _FakeBackend] = {}
        mgr = TerminalManager()
        mgr.start()
        try:
            sid = mgr.create_session("t", "codex", "", backend_factory=self._factory(store))
            mgr.send_input(sid, "y")
            # 输入由独立写入线程异步提交，等待其完成。
            deadline = time.time() + 2.0
            written = ""
            while time.time() < deadline:
                written = store["last"].written()
                if "\r" in written:
                    break
                time.sleep(0.02)
            self.assertEqual(written, "y\r", f"应为文本+单独 CR，实际 {written!r}")
            self.assertEqual(
                store["last"].write_calls(),
                ["y", "\r"],
                "文本与回车必须是两次独立写入",
            )
        finally:
            mgr.shutdown()

    def test_send_key_emits_control_sequences(self) -> None:
        """TUI 菜单靠方向键移动、回车确认、Esc 取消，必须支持这些控制键。"""
        store: dict[str, _FakeBackend] = {}
        mgr = TerminalManager()
        mgr.start()
        try:
            sid = mgr.create_session("t", "codex", "", backend_factory=self._factory(store))
            expected = {
                "up": "\x1b[A",
                "down": "\x1b[B",
                "left": "\x1b[D",
                "right": "\x1b[C",
                "enter": "\r",
                "esc": "\x1b",
                "tab": "\t",
                "backspace": "\x7f",
                "ctrl-c": "\x03",
            }
            for key, sequence in expected.items():
                before = len(store["last"].write_calls())
                self.assertTrue(mgr.send_key(sid, key), f"{key} 应被识别")
                calls = store["last"].write_calls()
                self.assertEqual(calls[before:], [sequence], f"{key} 应单次写入正确序列")
            # 未知按键不应写入任何东西
            before = len(store["last"].write_calls())
            self.assertFalse(mgr.send_key(sid, "f13"))
            self.assertEqual(len(store["last"].write_calls()), before)
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
