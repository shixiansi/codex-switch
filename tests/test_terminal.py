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
from codex_switch.ui_v2.terminal.completion import detect_choice, detect_menu
from codex_switch.ui_v2.terminal.input_assist import (
    SLASH_COMMANDS,
    InputHistory,
    command_hints,
)
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

    # -- 增量时间线 ------------------------------------------------------
    # 真实缺陷：早期每段存的是**整屏快照**，于是 banner、工作目录这些固定内容
    # 被逐段重印。用户实测三段时间戳下面各有一份完整 banner，评价是"一点用没有"。

    BANNER = (
        ">_ OpenAI Codex (v0.154.0)\r\n"
        "model:     grok-4.6 xhigh\r\n"
        "directory: F:\\test\r\n"
        "\r\n"
        "Tip: New Build faster with Codex.\r\n"
        "\r\n"
    )

    def test_timeline_records_only_new_content(self) -> None:
        """固定内容（banner）只应出现一次，不能每段重印一遍。"""
        screen = TerminalScreen()
        screen.feed(self.BANNER.encode())
        screen.mark_segment()

        screen.feed("› Ask Codex to do anything\r\n".encode())
        screen.mark_segment()

        screen.feed("› [Image #1] 图片上的是什么\r\n".encode())
        screen.mark_segment()

        timeline = screen.timeline()
        self.assertEqual(
            timeline.count("OpenAI Codex (v0.154.0)"),
            1,
            f"banner 被重复记录，时间线不可读：\n{timeline}",
        )
        self.assertEqual(timeline.count("model:"), 1)
        self.assertEqual(timeline.count("directory:"), 1)
        # 每一段的新内容都必须保留。
        self.assertIn("Ask Codex to do anything", timeline)
        self.assertIn("[Image #1]", timeline)
        self.assertEqual(len(screen.timeline_lines()), 3, "应有三个事件段")

    def test_timeline_delta_survives_scrolling(self) -> None:
        """终端滚动后仍要是增量。

        实现按**最长公共前缀**求差；若滚动导致前缀对不上，整屏会被当成新内容
        重发一遍——那正是要修的重复问题。这里输出远超一屏（40 行）来压这条路径。
        """
        screen = TerminalScreen()
        screen.feed(self.BANNER.encode())
        screen.mark_segment()

        for index in range(1, 61):
            screen.feed(f"tool call {index}: reading file\r\n".encode())
        screen.mark_segment()

        timeline = screen.timeline()
        self.assertEqual(timeline.count("OpenAI Codex"), 1, "滚动后 banner 被重复记录")
        for index in (1, 30, 60):
            self.assertEqual(
                timeline.count(f"tool call {index}:"),
                1,
                f"tool call {index} 被重复记录",
            )

    def test_blank_lines_are_not_recorded_as_content(self) -> None:
        """纯空白的增量不该形成一个段落（否则时间线会被空行刷屏）。"""
        screen = TerminalScreen()
        screen.feed("第一行\r\n".encode())
        screen.mark_segment()
        before = len(screen.timeline_lines())

        screen.feed(b"\r\n\r\n")
        self.assertFalse(screen.mark_segment(), "只有空行不应新增段落")
        self.assertEqual(len(screen.timeline_lines()), before)

    def test_timestamp_uses_segment_start_not_pause_time(self) -> None:
        """时间戳应表示"这段输出何时开始"，而不是"何时安静下来"。

        工具调用可能跑很久；若按停顿时刻打点，记下的是它结束的时间，
        对"什么时候发生了什么"没有意义。

        注意时间戳只有**秒级精度**，所以间隔必须明显大于 1 秒：用 0.3s 去测
        截断到整秒的字符串，误差本身就可能超过阈值（那是测试设计问题，
        不是实现问题）。这里用 2 秒，并断言"更接近开始而不是结束"。
        """
        screen = TerminalScreen()
        screen.feed("开始输出\r\n".encode())
        started = time.time()
        # 模拟一段持续较久的输出：期间有停顿但同属一段。
        time.sleep(2.0)
        screen.feed("结束输出\r\n".encode())
        ended = time.time()
        screen.mark_segment()

        line = screen.timeline_lines()[0]
        parsed = time.mktime(
            time.strptime(
                time.strftime("%Y-%m-%d ") + line[1:9], "%Y-%m-%d %H:%M:%S"
            )
        )
        self.assertLessEqual(
            abs(parsed - started), 1.0, f"时间戳偏离开始时刻：{line}"
        )
        self.assertLess(
            abs(parsed - started),
            abs(parsed - ended),
            f"时间戳更像结束时刻，说明记的是停顿时间：{line}",
        )


class TimelineLayoutTests(unittest.TestCase):
    """时间戳要显示在**主输出里**，不另开面板。

    演变过程（值得记下来，避免再走回头路）：
    1. 最初时间线与终端互斥，打开时输入框一起消失；
    2. 后来改成右侧 380px 侧栏并存；
    3. 用户明确要求的是"每一次工具调用、每一次对话前面显示时间戳"，
       而且强调"不是单独新开一个界面"——所以最终把时间戳**并进主输出文本**
       （TerminalScreen.annotated_text），并把侧栏整个去掉。
    """

    def _page_source(self) -> str:
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        path = (
            root
            / "src"
            / "codex_switch"
            / "ui_v2"
            / "qml"
            / "pages"
            / "TerminalDashboard.qml"
        )
        return path.read_text(encoding="utf-8")

    def test_no_separate_timeline_panel_remains(self) -> None:
        """不该再有独立的时间线面板 / 切换按钮。"""
        src = self._page_source()
        self.assertNotIn(
            "Layout.preferredWidth: page.showTimeline ? 380 : 0",
            src,
            "独立时间线侧栏应已移除（时间戳改为并进主输出）",
        )
        self.assertNotIn(
            'text: page.showTimeline ? "隐藏时间线" : "时间线"',
            src,
            "时间线切换按钮应已移除",
        )

    def test_main_output_uses_annotated_text(self) -> None:
        """主输出必须走带时间戳的 annotated_text，而不是裸 screen_text。"""
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        vm = (
            root
            / "src"
            / "codex_switch"
            / "ui_v2"
            / "viewmodels"
            / "terminal.py"
        ).read_text(encoding="utf-8")
        self.assertIn("annotated_text", vm, "视图模型没有使用带时间戳的输出")

    def test_annotated_text_carries_timestamps_and_live_tail(self) -> None:
        """带时间戳的输出：已打点内容有时间戳，实时尾部仍即时可见。"""
        screen = TerminalScreen()
        screen.feed("第一段\r\n".encode())
        screen.mark_segment()
        screen.feed("第二段\r\n".encode())
        screen.mark_segment()
        # 尚未打点的实时输出
        screen.feed("正在输出\r\n".encode())

        text = screen.annotated_text()
        self.assertRegex(text, r"\[\d{2}:\d{2}:\d{2}\] 第一段")
        self.assertRegex(text, r"\[\d{2}:\d{2}:\d{2}\] 第二段")
        self.assertIn("正在输出", text, "实时尾部必须保留，否则流式期间主界面会僵住")
        # 实时部分尚未结算，因此不应带时间戳。
        self.assertNotRegex(text, r"\[\d{2}:\d{2}:\d{2}\] 正在输出")

    def test_annotated_text_is_incremental(self) -> None:
        """固定内容（banner）只带一个时间戳，不能每段重印。"""
        screen = TerminalScreen()
        screen.feed(b">_ OpenAI Codex (v0.154.0)\r\nmodel: x\r\n\r\n")
        screen.mark_segment()
        screen.feed(b"\xe2\x80\x9a hello\r\n")
        screen.mark_segment()
        screen.feed(b"\xe2\x80\x9a world\r\n")
        screen.mark_segment()

        text = screen.annotated_text()
        self.assertEqual(text.count("OpenAI Codex (v0.154.0)"), 1)
        self.assertEqual(text.count("model: x"), 1)

    def test_annotated_blocks_structure(self) -> None:
        """结构化输出块：已打点块带 stamp，实时尾部 stamp 为空。

        界面靠这个结构把时间戳单独上色（与正文同色等宽文本"太丑"）。
        """
        screen = TerminalScreen()
        screen.feed(b">_ OpenAI Codex\r\n")
        screen.mark_segment()
        screen.feed("\u203a \u4f60\u597d\r\n".encode())
        screen.mark_segment()
        # 尚未打点的实时输出
        screen.feed("\u2022 \u6b63\u5728\u56de\u590d\r\n".encode())

        blocks = screen.annotated_blocks()
        self.assertEqual(len(blocks), 3, f"应有 3 块，实际 {blocks}")
        for block in blocks[:2]:
            self.assertRegex(block["stamp"], r"^\d{2}:\d{2}:\d{2}$")
            self.assertTrue(block["lines"], "每个块都要有内容")
        self.assertEqual(blocks[-1]["stamp"], "", "实时块不应带时间戳")
        self.assertTrue(any("\u6b63\u5728\u56de\u590d" in line for line in blocks[-1]["lines"]))

    def test_annotated_blocks_match_annotated_text(self) -> None:
        """结构化块与纯文本视图必须描述同一份内容（两者不能漂移）。"""
        screen = TerminalScreen()
        screen.feed(b"alpha\r\n")
        screen.mark_segment()
        screen.feed(b"beta\r\n")
        screen.mark_segment()

        blocks = screen.annotated_blocks()
        text = screen.annotated_text()
        for block in blocks:
            for line in block["lines"]:
                self.assertIn(line, text)
            if block["stamp"]:
                self.assertIn(block["stamp"], text)



class AltScreenTests(unittest.TestCase):
    """备用屏幕（ESC[?1049h / l）的换屏处理。

    codex 的选择器（resume / 审批菜单）跑在备用屏幕里。pyte 虽然把 1049
    记进模式集合，却**不做任何切换**——实测退出后选择器内容赖在屏幕上、
    主屏内容反而不见了。用户看到的正是"第二次输入的内容看不见了"。
    """

    ALT_ON = "\x1b[?1049h"
    ALT_OFF = "\x1b[?1049l"

    def test_main_screen_is_restored_after_leaving_alt(self) -> None:
        """这条是本次缺陷的直接回归。"""
        screen = TerminalScreen()
        screen.feed(b"\x1b[2J\x1b[H")
        screen.feed("MAIN CONTENT\r\n".encode())
        self.assertIn("MAIN CONTENT", screen.tail())

        screen.feed(self.ALT_ON.encode())
        screen.feed(b"\x1b[2J\x1b[H")
        screen.feed("ALT CONTENT\r\n".encode())
        self.assertIn("ALT CONTENT", screen.tail())
        self.assertNotIn("MAIN CONTENT", screen.tail(), "备用屏幕应是干净的一屏")

        screen.feed(self.ALT_OFF.encode())
        self.assertIn("MAIN CONTENT", screen.tail(), "退出后主屏内容没有恢复")
        self.assertNotIn("ALT CONTENT", screen.tail(), "备用屏内容没有清掉")

    def test_alt_screen_starts_clean(self) -> None:
        screen = TerminalScreen()
        screen.feed("主屏内容\r\n".encode())
        screen.feed(self.ALT_ON.encode())
        self.assertNotIn("主屏内容", screen.tail(), "备用屏幕应清空后使用")

    def test_nested_enter_is_ignored(self) -> None:
        """重复进入不应把备用屏内容当成主屏存起来。"""
        screen = TerminalScreen()
        screen.feed("主屏\r\n".encode())
        screen.feed(self.ALT_ON.encode())
        screen.feed(self.ALT_ON.encode())
        screen.feed("备用屏\r\n".encode())
        screen.feed(self.ALT_OFF.encode())
        self.assertIn("主屏", screen.tail(), "重复进入导致主屏丢失")

    def test_leave_without_enter_is_harmless(self) -> None:
        screen = TerminalScreen()
        screen.feed("内容\r\n".encode())
        screen.feed(self.ALT_OFF.encode())
        self.assertIn("内容", screen.tail())

    def test_output_after_leaving_alt_still_works(self) -> None:
        """退出选择器后必须还能正常接收输出（用户抱怨的正是这一点）。"""
        screen = TerminalScreen()
        screen.feed("主屏\r\n".encode())
        screen.feed(self.ALT_ON.encode())
        screen.feed("选择器\r\n".encode())
        screen.feed(self.ALT_OFF.encode())
        screen.feed("退出后继续输出\r\n".encode())
        tail = screen.tail()
        self.assertIn("退出后继续输出", tail)
        self.assertIn("主屏", tail)

    def test_alt_sequence_split_across_reads(self) -> None:
        """PTY 读取边界可能把序列切开，两半都得能认出。"""
        screen = TerminalScreen()
        screen.feed("主屏\r\n".encode())
        screen.feed(b"\x1b[?10")
        screen.feed(b"49h")
        screen.feed("备用\r\n".encode())
        self.assertIn("备用", screen.tail())
        self.assertNotIn("主屏", screen.tail())

    def test_alt_period_is_kept_in_timeline(self) -> None:
        """选择器里发生的事也有价值，不该从时间线里丢掉。"""
        screen = TerminalScreen()
        screen.feed("主屏\r\n".encode())
        screen.mark_segment()
        screen.feed(self.ALT_ON.encode())
        screen.feed("选择器内容\r\n".encode())
        screen.mark_segment()
        screen.feed(self.ALT_OFF.encode())

        timeline = screen.timeline()
        self.assertIn("选择器内容", timeline, "选择器内容没有并入时间线")
        self.assertIn("主屏", timeline)


class _AltScreenManagerTest(_ManagerBackedTest):
    def test_timeline_marks_on_pause_not_only_with_data(self) -> None:
        """回归：时间线打点必须每轮检查，否则 idle 永远为 0、时间线一直为空。

        用轮询等待而不是固定 sleep：打点发生在"某个轮询恰好看到 idle 已超过
        阈值"时，而轮询间隔 0.25s、阈值 0.3s，固定 sleep 0.8s 只剩约 50ms 余量，
        在负载高时会偶发失败。这里一直等到打点出现，既保留原意（期间没有新数据）
        又不会因调度抖动而假失败。
        """
        store: dict[str, _FakeBackend] = {}
        mgr = TerminalManager()
        mgr._segment_idle_seconds = 0.3
        mgr.start()
        try:
            sid = mgr.create_session("t", "codex", "", backend_factory=self._factory(store))
            store["last"].push(b"output one\n")
            # 期间不再 push 任何数据：靠轮询自己发现"停顿"。
            deadline = time.time() + 5.0
            timeline = ""
            while time.time() < deadline:
                timeline = mgr.timeline_text(sid)
                if "output one" in timeline:
                    break
                time.sleep(0.05)
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
    def test_auto_answer_selects_first_option(self) -> None:
        """开启自动应答后，菜单出现即自动选第一项。"""
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
        finally:
            mgr.shutdown()

    def test_auto_answer_retries_while_menu_persists(self) -> None:
        """回归：菜单仍在时必须重试。

        真实情形是菜单刚出现时 TUI 还没开始读输入，第一次应答会被丢弃；
        旧实现只发一次就把该菜单标记为"已答过"，于是日志显示已自动应答、
        菜单却一直停在那里等用户手动点击。
        """
        store: dict[str, _FakeBackend] = {}
        mgr = TerminalManager()
        mgr.auto_answer = True
        mgr.start()
        try:
            sid = mgr.create_session("t", "codex", "", backend_factory=self._factory(store))
            # 持续输出让菜单一直被检测到
            deadline = time.time() + 3.0
            while time.time() < deadline:
                store["last"].push("› 1. Yes, continue\n  2. No, quit\n".encode())
                time.sleep(0.15)
            calls = store["last"].write_calls()
            # 至少出现过两次"1"的提交，说明重试确实发生
            submissions = [c for c in calls if c == "1"]
            self.assertGreaterEqual(
                len(submissions), 2, f"菜单持续存在时应重试，实际写入 {calls}"
            )
        finally:
            mgr.shutdown()

    def test_auto_answer_stops_after_max_attempts(self) -> None:
        """重试必须有上限，避免无限刷键。"""
        from codex_switch.ui_v2.terminal import manager as manager_module

        store: dict[str, _FakeBackend] = {}
        mgr = TerminalManager()
        mgr.auto_answer = True
        mgr.start()
        try:
            sid = mgr.create_session("t", "codex", "", backend_factory=self._factory(store))
            end = time.time() + 4.0
            while time.time() < end:
                store["last"].push("› 1. Yes\n  2. No\n".encode())
                time.sleep(0.2)
            submissions = [c for c in store["last"].write_calls() if c == "1"]
            self.assertLessEqual(
                len(submissions),
                manager_module._AUTO_ANSWER_MAX_ATTEMPTS,
                "重试次数不应超过上限",
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

    def test_two_column_menu_labels_are_cleaned(self) -> None:
        """回归：codex 授权菜单是两列布局，标签里夹着大段对齐空格。

        直接显示会让按钮文字变成
        ``Allow                   Run the tool and continue.``。
        """
        menu = (
            "› 1. Allow                   Run the tool and continue.\n"
            "  2. Allow for this session  Run the tool and remember this choice.\n"
            "  3. Cancel                  Cancel this tool call"
        )
        awaiting, choices = detect_choice(menu)
        self.assertTrue(awaiting)
        self.assertEqual(choices[0], "Allow  Run the tool and continue.")
        # 不应残留用于对齐的长串空格
        for label in choices:
            self.assertNotIn("   " + "  ", label)
            self.assertNotIn("     ", label)

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


class PlainListMenuTests(unittest.TestCase):
    """无编号列表菜单（codex 的 resume 会话选择器）。

    真实缺陷：这类菜单没有数字编号，只有 ``>`` 标出的当前项和一行按键提示。
    原实现只认编号菜单，于是 **detect 返回 False**，界面上根本弹不出选项条——
    用户看到菜单里列着历史会话，却点不了、也选不中。
    """

    RESUME = (
        "Resume a previous session\n"
        "Type to search     Filter: [Cwd] All  Status: [Active] Archived\n"
        "\n"
        "> 1d ago        读取改项目，查看项目结构，有没有哪里需要优化的地方\n"
        "  157d ago      你好\n"
        "  157d ago      你好\n"
        "  157d ago      你好\n"
        "\n"
        "enter resume  ctrl+a archive  esc exit  ctrl+c exit\n"
    )

    def test_resume_list_is_detected(self) -> None:
        menu = detect_menu(self.RESUME)
        self.assertTrue(menu.awaiting, "resume 列表菜单没有被识别出来")
        self.assertEqual(len(menu.choices), 4)
        self.assertEqual(menu.kind, "list")
        self.assertFalse(menu.numbered, "list 菜单不应被当作编号菜单")

    def test_current_highlight_is_reported(self) -> None:
        """要能看出当前高亮在第几项，界面才能标出"回车会选中哪个"。"""
        menu = detect_menu(self.RESUME)
        self.assertEqual(menu.selected, 0)

        shifted = self.RESUME.replace("> 1d ago", "  1d ago").replace(
            "  157d ago      你好\n  157d ago      你好\n  157d ago      你好",
            "> 157d ago      你好\n  157d ago      你好\n  157d ago      你好",
        )
        self.assertEqual(detect_menu(shifted).selected, 1)

    def test_list_without_hint_footer_is_not_a_menu(self) -> None:
        """没有按键提示行就不是交互菜单（避免把正文引用块当成菜单）。"""
        text = "输出如下\n> 引用第一行\n> 引用第二行\n"
        self.assertFalse(detect_menu(text).awaiting)

    def test_list_without_selection_marker_is_not_a_menu(self) -> None:
        text = "会话\n  157d ago 你好\n  158d ago 再见\n\nenter resume  esc exit\n"
        self.assertFalse(detect_menu(text).awaiting, "没有选中标记就不是菜单")

    def test_numbered_menu_still_wins(self) -> None:
        """编号菜单的判定优先于列表菜单（更明确、误判风险更低）。"""
        text = "› 1. Yes\n  2. No\n\nenter confirm  esc cancel\n"
        menu = detect_menu(text)
        self.assertTrue(menu.awaiting)
        self.assertEqual(menu.kind, "numbered")

    # -- 只有一项的列表菜单 ----------------------------------------------
    # 真实缺陷（用户截图）：只剩一个历史会话时，`1 / 1` 的 resume 菜单被整个
    # 否决，界面不弹选项条，用户完全无法选择。
    SINGLE_ITEM_SCREEN = (
        "Resume a previous session\n"
        "Type to search\n"
        "Filter: [Cwd] All  Status: [Active] Archived  Sort: [Updated] Created\n"
        "\n"
        "› 26m ago  开发视频图片智能分类去重App\n"
        "\n"
        "  1 / 1 · 100% ────────────────────────\n"
        "enter resume  ctrl+a archive  ctrl+c exit  tab focus sort/filter  "
        "+/→ change option\n"
        "ctrl+o comfortable view  ctrl+t transcript  ctrl+e expand  ↑/↓ browse\n"
    )

    def test_single_item_list_is_detected(self) -> None:
        """只有一项的列表菜单同样要识别出来。

        旧实现要求列表至少两项，于是"只剩一个历史会话"这一常见场景整屏失效。
        列表菜单的条件是叠加的（页脚按键行 + 选中标记），单项仍然可靠。
        """
        menu = detect_menu(self.SINGLE_ITEM_SCREEN)
        self.assertTrue(menu.awaiting, "单项 resume 菜单没有被识别出来")
        self.assertEqual(menu.kind, "list")
        self.assertEqual(len(menu.choices), 1)
        self.assertEqual(menu.selected, 0)
        self.assertIn("开发视频图片智能分类去重App", menu.choices[0])

    def test_single_numbered_option_is_still_not_a_menu(self) -> None:
        """编号菜单**不**放宽到 1 项：codex 的输入提示符就是这个形状。

        放宽会把用户自己输入的 ``1. xxx`` 判成菜单，这是本模块一直在防的误报。
        """
        self.assertFalse(detect_menu("› 1. do something\n").awaiting)
        self.assertFalse(detect_menu("› 1. Yes\n").awaiting)

    def test_single_item_still_requires_footer_and_marker(self) -> None:
        """单项放宽后，防误报的两个条件必须仍然生效。"""
        no_footer = "输出：\n› 26m ago  某个会话\n"
        self.assertFalse(detect_menu(no_footer).awaiting, "缺按键提示行不该认作菜单")

        no_marker = (
            "Resume a previous session\n"
            "  26m ago  某个会话\n"
            "\n"
            "enter resume  esc exit  ctrl+c exit\n"
        )
        self.assertFalse(detect_menu(no_marker).awaiting, "缺选中标记不该认作菜单")

    def test_single_item_with_wrapped_label_is_still_detected(self) -> None:
        """标题长到触发 TUI 折行时，菜单仍要能被识别出来（可用性优先）。

        已知局限：折行的续行目前会被当成额外选项，于是选项数偏多
        （实测长标题得 3 项）。这与"只剩一项"是两个独立问题，且属于本次
        修复之前就存在的行为，因此这里如实记录现状，不假装已经解决：
        - 识别本身必须成功（否则用户完全无法操作，才是真正的卡死）；
        - 但不能因此把菜单判成不可用。

        真正要修需要"折行续行"的判定规则（续行没有 "xx ago" 前缀、缩进更深），
        属于独立改动，避免在没有真实样本的情况下引入新的误判。
        """
        long_title = "一个特别长的会话标题" * 12  # 填满 120 列，必然折行
        wrapped = (
            "Resume a previous session\n"
            "Type to search\n"
            "\n"
            f"› 26m ago   {long_title}\n"
            "\n"
            "  1 / 1 · 100% ────────────────────────\n"
            "enter resume  ctrl+a archive  esc exit  ←/→ change option\n"
        )
        menu = detect_menu(wrapped)
        self.assertTrue(menu.awaiting, "折行的列表菜单仍应被识别")
        self.assertEqual(menu.kind, "list")
        # 如实记录：续行被计入，因此项数多于真实会话数。
        self.assertGreaterEqual(len(menu.choices), 1)


    def test_confirm_prompt_kind(self) -> None:
        menu = detect_menu("Overwrite file? [Y/n] ")
        self.assertTrue(menu.awaiting)
        self.assertEqual(menu.kind, "confirm")
        self.assertEqual(menu.choices, ["是", "否"])

    # 真实屏幕内容（取自用户截图）。这一条最值得留：
    # 先前用手写的简化样例测试一直是过的，但拿到真实内容就失败——
    # 因为 codex 的页脚是**两行**，中间还夹着分页行，而实现当时只看最后一行。
    REAL_SCREEN = (
        "Resume a previous session\n"
        "Type to search     Filter: [Cwd] All  Status: [Active] Archived  "
        "Sort: [Updated] Created\n"
        "\n"
        "> 1d ago      读取改项目，查看项目结构，有没有哪里需要优化的地方\n"
        "  157d ago    你好\n"
        "  157d ago    你好\n"
        "  157d ago    你好\n"
        "\n"
        "  1 / 4 · 100% ──────────────────────────────\n"
        "enter resume  ctrl+a archive  esc exit  ctrl+c exit  "
        "tab focus sort/filter  //+- change option\n"
        "ctrl+o comfortable view  ctrl+t transcript  ctrl+e expand  ↑/↓ browse\n"
    )

    def test_real_screen_with_two_line_footer(self) -> None:
        """真实 resume 菜单：页脚两行 + 分页行。

        手写简化样例能过、真实内容过不了，说明样例不够真实。
        这里直接用真实屏幕文本锁死。
        """
        menu = detect_menu(self.REAL_SCREEN)
        self.assertTrue(menu.awaiting, "真实 resume 菜单没有被识别")
        self.assertEqual(menu.kind, "list")
        self.assertEqual(len(menu.choices), 4)
        self.assertEqual(menu.selected, 0)

    def test_real_screen_without_pagination_line(self) -> None:
        """分页行可能不存在，识别不该依赖它。"""
        without = self.REAL_SCREEN.replace(
            "  1 / 4 · 100% ──────────────────────────────\n", ""
        )
        menu = detect_menu(without)
        self.assertTrue(menu.awaiting)
        self.assertEqual(len(menu.choices), 4)

    def test_real_screen_with_second_item_selected(self) -> None:
        moved = self.REAL_SCREEN.replace("> 1d ago", "  1d ago").replace(
            "  157d ago    你好", "> 157d ago    你好", 1
        )
        self.assertEqual(detect_menu(moved).selected, 1)

    def test_footer_alone_is_not_a_menu(self) -> None:
        """只有页脚、没有列表时不构成菜单。"""
        footer_only = (
            "enter resume  ctrl+a archive  esc exit\n"
            "ctrl+o comfortable view  ctrl+t transcript\n"
        )
        self.assertFalse(detect_menu(footer_only).awaiting)

    # 真实捕获（codex resume --all 的 PTY 输出）。与手写样例的差别：
    #   * 缩进不固定（选中项两格、其余四格）
    #   * 列表末尾有 "↓ more" 行
    #   * 共 21 项，且被 _TAIL_CHARS 截断过
    # 先前的手写样例这三点都没有，所以测试全绿但实际用不了。
    REAL_CAPTURE = (
        " Resume a previous session\n"
        "\n"
        " Type to search                              Filter:  Cwd [All]   "
        "Status: [Active] Archived    Sort: [Updated] Created\n"
        "\n"
        "  \u276f 14d ago     [Image #1]没更新前的数据抽数是对的，更新记录后角色的抽数显示就\n"
        "    61d ago     首页logo大小改成120*120，同时左边菜单栏显示具体的导航名称\n"
        "    72d ago     依旧重复验证码\n"
        "    118d ago    Unable to locate the real codex executable from PATH.\n"
        "    120d ago    说明更新规则\n"
        "    120d ago    遵循开发规则与PMNote\n"
        "    121d ago    检查pmnote MCP能力\n"
        "    121d ago    打招呼\n"
        "    121d ago    优化角色素材与图层控制\n"
        "    121d ago    修复 pickGroup 代理错误\n"
        "    122d ago    Fix bottom part slicing\n"
        "    122d ago    Refactor body rigging pipeline\n"
        "    124d ago    编写图片生成裁剪脚本\n"
        "    125d ago    整理角色外观自定义PRD\n"
        "    127d ago    分析AIGC检测原理\n"
        "    130d ago    调查 collect 长度不一致\n"
        "    131d ago    分析三个JS文件作用\n"
        "    145d ago    定位 button 消息处理冲突\n"
        "    146d ago    为什么启动不了这个项目\n"
        "    153d ago    修改ChatGPT第二步注册并新增退出登录流程\n"
        "    157d ago    无法连接 PostgreSQL。请检查 DATABASE_URL 是否正确，"
        "以及数据库账号密码是否可用。\n"
        "  \u2193 more\n"
        "\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500 1 / 25 \u00b7 0% \u2500\n"
        " enter resume   ctrl+a archive   esc start new   ctrl+c quit   "
        "tab focus sort/filter   \u2190/\u2192 change option\n"
        " ctrl+o comfortable view   ctrl+t transcript   ctrl+e expand   \u2191/\u2193 browse\n"
    )

    def test_real_capture_is_detected(self) -> None:
        """真实捕获的 resume 列表（21 项、含 ↓ more、缩进不固定）。"""
        menu = detect_menu(self.REAL_CAPTURE)
        self.assertTrue(menu.awaiting, "真实 resume 列表没有被识别")
        self.assertEqual(menu.kind, "list")
        self.assertEqual(len(menu.choices), 21)
        self.assertEqual(menu.selected, 0)

    def test_more_row_is_not_treated_as_option(self) -> None:
        """"↓ more" 是列表与页脚间的装饰，不该成为一个可选会话。"""
        menu = detect_menu(self.REAL_CAPTURE)
        joined = " ".join(menu.choices).lower()
        self.assertNotIn("more", joined)
        self.assertNotIn("enter resume", joined)

    def test_tail_window_does_not_slice_lines(self) -> None:
        """尾部截断必须是整行的。

        直接按字符切会把第一行截成半截，半截行既不像列表项也不像页脚，
        会让整块列表作废——真实 resume 输出正是这样被漏掉的。
        """
        from codex_switch.ui_v2.terminal.completion import _tail_lines

        text = "\n".join(f"    行 {index}" for index in range(200))
        lines = _tail_lines(text)
        self.assertTrue(lines)
        for line in lines:
            self.assertRegex(line, r"^    行 \d+$", "截断产生了半截行")

    def test_long_list_survives_tail_truncation(self) -> None:
        """列表很长时仍要能识别。

        真实终端只有 40 行，列表会被 TUI 滚动；若尾部窗口太窄，可能刚好
        把带选中标记的那一项切掉，于是整个菜单认不出来（表现为"看得到
        菜单却弹不出选项条"）。窗口必须比一屏宽裕。
        """
        rows = ["Select a session", ""]
        rows.append("  \u276f 1d ago    第一项")
        for index in range(44):
            rows.append(f"    {index}d ago    第 {index} 项")
        rows.append("  \u2193 more")
        rows.append("\u2500" * 40 + " 1 / 45 \u00b7 0% \u2500")
        rows.append(" enter resume   esc exit   ctrl+c quit   tab focus   \u2190/\u2192 change")
        rows.append(" ctrl+o view   ctrl+t transcript   \u2191/\u2193 browse")

        menu = detect_menu("\n".join(rows))
        self.assertTrue(menu.awaiting, "长列表没有被识别")
        self.assertEqual(menu.selected, 0)
        self.assertEqual(len(menu.choices), 45)

    def test_selection_near_end_is_still_found(self) -> None:
        """选中标记落在列表末尾附近时也要能找到。"""
        rows = ["Select a session", ""]
        for index in range(30):
            rows.append(f"    {index}d ago    第 {index} 项")
        rows.append("  \u276f 31d ago    选中项在最后")
        rows.append("  \u2193 more")
        rows.append("\u2500" * 40 + " 1 / 35 \u00b7 0% \u2500")
        rows.append(" enter resume   esc exit   ctrl+c quit   tab focus")
        rows.append(" ctrl+o view   ctrl+t transcript")

        menu = detect_menu("\n".join(rows))
        self.assertTrue(menu.awaiting)
        self.assertEqual(menu.selected, len(menu.choices) - 1)


class SelectChoiceTests(unittest.TestCase):
    """选中菜单项时该发什么——发错就等于点了没反应。"""

    def _manager_with_backend(self):
        store: dict[str, _FakeBackend] = {}

        def make(command, cwd, env):
            backend = _FakeBackend(command, cwd, env)
            store["last"] = backend
            return backend

        manager = TerminalManager(poll_interval=0.05)
        manager.start()
        self.addCleanup(manager.shutdown)
        manager.create_session("t", "codex", "", backend_factory=make)
        session = next(iter(manager._sessions.values()))
        return manager, session, store["last"]

    @staticmethod
    def _written(backend: _FakeBackend) -> str:
        """把多次写入拼起来，便于断言"整体发了什么"。"""
        return "".join(backend.write_calls())

    def _wait_for_write(self, backend: _FakeBackend, timeout=3.0) -> str:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if backend.write_calls():
                return self._written(backend)
            time.sleep(0.02)
        return self._written(backend)

    def test_numbered_menu_sends_the_number(self) -> None:
        manager, session, backend = self._manager_with_backend()
        session.choices = ["Yes", "No"]
        session.choice_kind = "numbered"
        manager.select_choice(session.session_id, 1)
        self.assertIn("2", self._wait_for_write(backend))

    def test_confirm_menu_sends_y_or_n(self) -> None:
        """确认提示要发 y / n，不是数字。"""
        manager, session, backend = self._manager_with_backend()
        session.choices = ["是", "否"]
        session.choice_kind = "confirm"
        manager.select_choice(session.session_id, 0)
        self.assertIn("y", self._wait_for_write(backend))

    def test_list_menu_uses_arrow_keys_not_numbers(self) -> None:
        """列表菜单必须用方向键：发数字会被 TUI 当成搜索词。

        这正是"看得到选项却选不中"的根因。
        """
        manager, session, backend = self._manager_with_backend()
        session.choices = ["会话一", "会话二", "会话三"]
        session.choice_kind = "list"
        session.choice_selected = 0
        manager.select_choice(session.session_id, 2)

        deadline = time.time() + 4.0
        while time.time() < deadline:
            if "\r" in self._written(backend):
                break
            time.sleep(0.02)
        written = self._written(backend)
        self.assertIn("\x1b[B", written, "没有发送下方向键")
        self.assertNotIn("3", written, "列表菜单不该发数字")
        self.assertIn("\r", written, "最后应当回车确认")

    def test_list_menu_from_unknown_position_returns_to_top(self) -> None:
        """看不出高亮位置时先发 ↑ 回到首项，保证结果确定。"""
        manager, session, backend = self._manager_with_backend()
        session.choices = ["一", "二"]
        session.choice_kind = "list"
        session.choice_selected = -1
        manager.select_choice(session.session_id, 0)

        deadline = time.time() + 4.0
        while time.time() < deadline:
            if "\r" in self._written(backend):
                break
            time.sleep(0.02)
        self.assertIn("\x1b[A", self._written(backend), "没有先回到首项")

    def test_list_menu_is_not_auto_answered(self) -> None:
        """列表菜单不能被自动应答。

        开启自动选择后如果对 resume 菜单也自动回车，等于替用户随便恢复一个
        历史会话——这是有副作用的误操作，必须跳过。
        """
        manager, session, backend = self._manager_with_backend()
        manager.auto_answer = True
        session.choices = ["会话一", "会话二"]
        session.choice_kind = "list"
        manager._maybe_auto_answer(session)
        time.sleep(0.4)
        self.assertEqual(self._written(backend), "", "列表菜单不应被自动应答")

    def test_confirm_menu_is_auto_answered_with_y(self) -> None:
        manager, session, backend = self._manager_with_backend()
        manager.auto_answer = True
        session.choices = ["是", "否"]
        session.choice_kind = "confirm"
        manager._maybe_auto_answer(session)
        deadline = time.time() + 3.0
        while time.time() < deadline:
            if backend.write_calls():
                break
            time.sleep(0.02)
        self.assertIn("y", self._written(backend))


class InputHistoryTests(unittest.TestCase):
    """↑↓ 翻历史。"""

    def test_previous_and_next_navigate(self) -> None:
        history = InputHistory()
        for text in ("一", "二", "三"):
            history.record("s", text)
        self.assertEqual(history.previous("s", "草稿"), "三")
        self.assertEqual(history.previous("s"), "二")
        self.assertEqual(history.next("s"), "三")
        self.assertEqual(history.next("s"), "草稿", "越过最新应回到草稿")
        self.assertIsNone(history.next("s"))

    def test_previous_at_oldest_returns_none(self) -> None:
        history = InputHistory()
        history.record("s", "只有一条")
        self.assertEqual(history.previous("s", ""), "只有一条")
        self.assertIsNone(history.previous("s"), "到最早后不应再动")

    def test_consecutive_duplicates_are_not_recorded(self) -> None:
        history = InputHistory()
        history.record("s", "重复")
        history.record("s", "重复")
        self.assertEqual(history.entries("s"), ["重复"])

    def test_blank_input_is_not_recorded(self) -> None:
        history = InputHistory()
        history.record("s", "   ")
        self.assertEqual(history.entries("s"), [])

    def test_history_is_isolated_per_session(self) -> None:
        """不同会话的历史不能混：否则会把 A 项目的提示词发到 B 项目。"""
        history = InputHistory()
        history.record("a", "A 的")
        history.record("b", "B 的")
        self.assertEqual(history.entries("a"), ["A 的"])
        self.assertEqual(history.entries("b"), ["B 的"])

    def test_forget_drops_only_that_session(self) -> None:
        history = InputHistory()
        history.record("a", "A 的")
        history.record("b", "B 的")
        history.forget("a")
        self.assertEqual(history.entries("a"), [])
        self.assertEqual(history.entries("b"), ["B 的"])

    def test_recording_resets_navigation(self) -> None:
        history = InputHistory()
        history.record("s", "旧")
        history.previous("s", "")
        history.record("s", "新")
        self.assertEqual(history.previous("s", ""), "新")


class CommandHintTests(unittest.TestCase):
    """斜杠指令提示。"""

    def test_slash_prefix_shows_candidates(self) -> None:
        hint = command_hints("/")
        self.assertTrue(hint.visible)
        self.assertGreater(len(hint.items), 3)

    def test_prefix_filters(self) -> None:
        hint = command_hints("/mo")
        self.assertEqual([item["name"] for item in hint.items], ["/model"])

    def test_plain_text_shows_nothing(self) -> None:
        self.assertFalse(command_hints("你好").visible)

    def test_arguments_stop_the_hint(self) -> None:
        """已输入参数后不再提示，免得挡着用户看自己写的内容。"""
        self.assertFalse(command_hints("/model gpt-5").visible)

    def test_unknown_command_shows_nothing(self) -> None:
        self.assertFalse(command_hints("/zzz").visible)

    def test_every_candidate_has_a_description(self) -> None:
        for item in command_hints("/").items:
            self.assertTrue(item.get("description"), item)

    def test_no_fabricated_commands(self) -> None:
        """候选里不能出现在 codex 中并不存在的命令。

        早先这表里有 /approvals /undo /help，全凭印象写的；
        用户照着提示输入只会得到一个错误的菜单。
        这份白名单来自实测（逐字母输入 /a../z 收集 CLI 自己的补全）。
        """
        names = {name for name, _ in SLASH_COMMANDS}
        for fake in ("/approvals", "/undo", "/help"):
            self.assertNotIn(fake, names, f"{fake} 在 codex 里不存在，不该出现在提示里")
        for real in ("/model", "/resume", "/review", "/permissions", "/plan"):
            self.assertIn(real, names)

    def test_prefix_order_matches_codex(self) -> None:
        """/re 的候选顺序要与 codex 自己的一致。

        顺序重要：用户只输入前缀就回车时，codex 会取它列表里的**第一个**
        匹配项。界面若把别的命令排前面，用户以为选中的与实际执行的不一致。
        """
        names = [item["name"] for item in command_hints("/re").items]
        self.assertEqual(names[0], "/resume", f"第一个应是 /resume，实际 {names}")


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
