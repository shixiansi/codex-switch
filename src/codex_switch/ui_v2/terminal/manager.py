"""AI 终端会话管理器（业务层，无 Qt 依赖）。

职责：
- 登记/启动/停止多个 PTY 会话；
- 后台线程周期性读取输出、检测退出、触发整树回收（零残留）；
- 把"完成/失败/可选项"事件通知给上层；
- cleanup_orphans() 回收本工具登记过但 root 已死、子树仍在的孤儿进程。
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from .completion import detect_choice
from .logging_setup import get_logger
from .pty_session import (
    PtySession,
    SessionStatus,
    _Backend,
    mark_finished,
    reap_tree,
    start_session,
)
from .screen import TerminalScreen

log = get_logger()

# 事件类型
EVENT_OUTPUT = "output"
EVENT_STATUS = "status"
EVENT_CHOICE = "choice"
# 时间线新增了一段（输出停顿后打点），用于让界面刷新时间线面板。
EVENT_TIMELINE = "timeline"

# 特殊按键 → 终端字节序列。TUI 菜单多靠方向键移动、回车确认、Esc 取消，
# 而普通输入框只能发文本，因此需要单独提供这些控制键。
SPECIAL_KEYS: dict[str, str] = {
    "up": "\x1b[A",
    "down": "\x1b[B",
    "right": "\x1b[C",
    "left": "\x1b[D",
    "enter": "\r",
    "esc": "\x1b",
    "tab": "\t",
    "backspace": "\x7f",
    "ctrl-c": "\x03",
}

# 文本与回车之间的写入间隔。
#
# 实测结论（对真实 codex 二进制扫描 0.05/0.2/0.5/1.0s）：0.05s 无法提交，0.2s 起稳定提交。
# 原因是 codex 开启了 bracketed paste（ESC[?2004h）：同一次读取里到达的"文本+回车"
# 会被当成**粘贴**，回车被吞进粘贴内容里，于是屏幕上能看到消息、AI 却完全不开始工作。
# 分开写入并留出间隔，可确保回车被当作独立的按键处理。取 0.25s 留出余量。
_ENTER_DELAY_S = 0.25

# 自动应答的重试策略：菜单刚出现时 TUI 可能还没开始读输入，单次发送会被丢弃，
# 因此按间隔重试若干次，直到菜单消失。
_AUTO_ANSWER_RETRY_S = 1.5
_AUTO_ANSWER_MAX_ATTEMPTS = 6
# 菜单持续消失多久才认为"真的结束了"，用于避免重绘闪烁导致重复应答。
_MENU_GONE_RESET_S = 2.0

EventHook = Callable[[str, str, dict[str, Any]], None]


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


@dataclass
class SessionSummary:
    """传给 UI 的会话快照（纯数据，可 JSON 化）。"""

    session_id: str
    title: str
    command: str
    cwd: str
    status: str
    exit_code: int | None = None
    started_at: str = ""
    finished_at: str = ""
    awaiting_choice: bool = False
    choices: list[str] = field(default_factory=list)
    last_line: str = ""
    # 运行时长（毫秒）：运行中为"至今"，结束后为总时长。由 manager 计算，
    # 避免 QML 侧做时间运算。
    elapsed_ms: int = 0
    # 当前选项是否已由自动应答处理过。
    auto_answered: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "sessionId": self.session_id,
            "title": self.title,
            "command": self.command,
            "cwd": self.cwd,
            "status": self.status,
            "statusLabel": _STATUS_LABELS.get(self.status, self.status),
            "exitCode": self.exit_code,
            "startedAt": self.started_at,
            "finishedAt": self.finished_at,
            "awaitingChoice": self.awaiting_choice,
            "choices": list(self.choices),
            "lastLine": self.last_line,
            "elapsedMs": self.elapsed_ms,
            "elapsedLabel": _format_elapsed(self.elapsed_ms),
            "autoAnswered": self.auto_answered,
        }


def _elapsed_ms(session: PtySession) -> int:
    """会话运行时长（毫秒）：运行中算到此刻，结束后用结束时间。"""
    if not session.started_at_ms:
        return 0
    end = session.finished_at_ms or (time.time() * 1000.0)
    return max(0, int(end - session.started_at_ms))


def _auto_choice_index(choices: list[str]) -> int:
    """自动应答时选哪一项。

    默认第一项：codex/claude 的确认菜单首项通常是"继续/默认"语义
    （如 ``Yes, continue``），最符合"自动放行"的预期。
    """
    return 0


def _format_elapsed(milliseconds: int) -> str:
    """把毫秒格式化成 ``1h02m03s`` / ``02m03s`` / ``03s`` 形式。"""
    total = max(0, int(milliseconds // 1000))
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}h{minutes:02d}m{seconds:02d}s"
    if minutes:
        return f"{minutes:02d}m{seconds:02d}s"
    return f"{seconds}s"


_STATUS_LABELS = {
    SessionStatus.STARTING.value: "启动中",
    SessionStatus.RUNNING.value: "运行中",
    SessionStatus.COMPLETED.value: "已完成",
    SessionStatus.FAILED.value: "失败",
    SessionStatus.STOPPED.value: "已停止",
}


class TerminalManager:
    """会话登记表 + 轮询线程。"""

    def __init__(self, poll_interval: float = 0.25, on_event: EventHook | None = None) -> None:
        self._sessions: dict[str, PtySession] = {}
        self._backends: dict[str, _Backend] = {}
        self._screens: dict[str, TerminalScreen] = {}
        self._poll_interval = poll_interval
        self._on_event = on_event
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        # 待发送的行队列，由独立写入线程按"先文本、后回车"的顺序处理。
        # 放在队列里而不是在调用方 sleep，是为了不阻塞 GUI 线程。
        self._pending: list[tuple[str, str]] = []
        self._pending_lock = threading.Lock()
        self._pending_event = threading.Event()
        self._writer: threading.Thread | None = None
        # 自动应答：检测到选择菜单时自动按预设策略回答，无需人工点击。
        # 默认关闭，由界面上的开关控制。
        self.auto_answer = False
        # 输出停顿多久算"一段结束"，用于给时间线打点。
        self._segment_idle_seconds = 1.2

    # -- 生命周期 ------------------------------------------------------
    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="terminal-poll")
        self._thread.start()
        self._writer = threading.Thread(target=self._write_loop, daemon=True, name="terminal-writer")
        self._writer.start()
        log.info("轮询线程已启动 interval=%ss", self._poll_interval)

    def _write_loop(self) -> None:
        """按序处理待发送的行：先写文本，停顿后再写回车。

        停顿必须发生在这里（后台线程），不能在 UI 线程 sleep，否则界面会卡住。
        """
        while not self._stop.is_set():
            if not self._pending_event.wait(0.1):
                continue
            while True:
                with self._pending_lock:
                    if not self._pending:
                        self._pending_event.clear()
                        break
                    session_id, text = self._pending.pop(0)
                backend = self._backends.get(session_id)
                if backend is None:
                    continue
                try:
                    backend.write(text)
                    time.sleep(_ENTER_DELAY_S)
                    backend.write("\r")
                except Exception:  # noqa: BLE001 - 写入失败不应终止写入线程
                    log.exception("发送输入失败 id=%s", session_id)

    def shutdown(self) -> None:
        """停止全部会话（整树回收）并结束轮询线程。"""
        self._stop.set()
        with self._lock:
            ids = list(self._sessions.keys())
        for sid in ids:
            self.stop_session(sid, reap=True)
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        if self._writer is not None:
            self._writer.join(timeout=2.0)
            self._writer = None
        with self._pending_lock:
            self._pending.clear()
        self._pending_event.clear()

    # -- 会话操作 ------------------------------------------------------
    def create_session(
        self,
        title: str,
        command: str,
        cwd: str,
        env: dict[str, str] | None = None,
        *,
        backend_factory: Callable[[str, str, dict[str, str]], _Backend] | None = None,
    ) -> str:
        """新建并启动一个会话，返回 session_id。"""
        session_id = uuid.uuid4().hex[:12]
        session = PtySession(
            session_id=session_id,
            title=title or command,
            command=command,
            cwd=cwd,
            env=dict(env or {}),
            started_at=_now(),
            started_at_ms=time.time() * 1000.0,
        )
        log.info("启动会话 id=%s title=%r", session_id, session.title)
        log.info("  命令: %s", command)
        log.info("  目录: %s", cwd or "(默认)")
        if env:
            log.info("  环境变量: %s", ", ".join(sorted(env)))
        with self._lock:
            self._sessions[session_id] = session
            self._screens[session_id] = TerminalScreen()
        try:
            backend = start_session(session, backend_factory=backend_factory)
        except Exception as exc:  # noqa: BLE001 - 记录下来再抛出，避免"悄无声息"
            log.exception("启动会话失败 id=%s: %s", session_id, exc)
            with self._lock:
                self._sessions.pop(session_id, None)
                self._screens.pop(session_id, None)
            raise
        with self._lock:
            self._backends[session_id] = backend
        log.info("会话已启动 id=%s pid=%s", session_id, session.root_pid)
        self._emit(session_id, EVENT_STATUS, {"status": session.status.value})
        return session_id

    def stop_session(self, session_id: str, *, reap: bool = True) -> None:
        backend = self._backends.get(session_id)
        session = self._sessions.get(session_id)
        if backend is not None:
            try:
                backend.kill()
            except Exception:  # noqa: BLE001
                pass
        if session is not None and reap:
            reap_tree(session)
        if session is not None and not session.status.is_terminal:
            mark_finished(session, None)
            self._emit(session_id, EVENT_STATUS, {"status": session.status.value})

    def send_input(self, session_id: str, data: str) -> None:
        """把一行输入交给写入线程提交（非阻塞，不卡界面）。

        提交一行的两个要点（均对真实 codex 实测确认）：
        1) 结束符是单个 CR（0x0D），即真实终端按下 Enter 发出的字节。发 CRLF 会被
           原始模式 TUI 当成两次回车，第二条空消息会顶掉刚输入的请求。
        2) 文本与 CR 必须分成两次写入且留出间隔。codex 开启了 bracketed paste
           （ESC[?2004h），同一次到达的"文本+回车"会被当作粘贴，回车被吞掉，
           于是消息显示出来了但 AI 完全不开始工作。
        """
        if session_id not in self._backends:
            return
        text = str(data or "")
        # 多行输入统一为 CR，避免裸 \n 被当作额外回车提前提交。
        text = text.replace("\r\n", "\r").replace("\n", "\r")
        if not text:
            return
        self._queue_input(session_id, text)
        # 用户输入后，CLI 通常会清掉提示；乐观地关闭"等待选择"态。
        session = self._sessions.get(session_id)
        if session is not None and session.awaiting_choice:
            session.awaiting_choice = False
            session.choices = []
            self._emit(session_id, EVENT_CHOICE, {"awaitingChoice": False, "choices": []})

    def _queue_input(self, session_id: str, text: str) -> None:
        """把一行文本排入写入队列（由写入线程补发回车）。"""
        if not text:
            return
        with self._pending_lock:
            self._pending.append((session_id, text))
        self._pending_event.set()

    def send_key(self, session_id: str, key: str) -> bool:
        """发送一个特殊按键（方向键 / Enter / Esc / Tab / Ctrl-C）。

        与 send_input 不同，控制键要**立即单次写入**：它们本身就是终端的按键序列，
        没有"文本 + 回车被当成粘贴"的问题。返回是否识别并发送了该键。
        用于在 TUI 菜单里上下移动、确认或取消。
        """
        sequence = SPECIAL_KEYS.get(str(key or "").lower())
        if sequence is None:
            return False
        backend = self._backends.get(session_id)
        if backend is None:
            return False
        try:
            backend.write(sequence)
        except Exception:  # noqa: BLE001 - 发送失败不应影响上层
            log.exception("发送按键失败 id=%s key=%s", session_id, key)
            return False
        return True

    def remove_session(self, session_id: str) -> None:
        """从登记表移除（进程若仍在则先回收）。"""
        self.stop_session(session_id, reap=True)
        with self._lock:
            self._sessions.pop(session_id, None)
            self._backends.pop(session_id, None)
            self._screens.pop(session_id, None)

    # -- 查询 ----------------------------------------------------------
    def summaries(self) -> list[SessionSummary]:
        with self._lock:
            sessions = list(self._sessions.values())
        out: list[SessionSummary] = []
        for s in sessions:
            screen = self._screens.get(s.session_id)
            last = screen.last_line if screen is not None else ""
            out.append(
                SessionSummary(
                    session_id=s.session_id,
                    title=s.title,
                    command=s.command,
                    cwd=s.cwd,
                    status=s.status.value,
                    exit_code=s.exit_code,
                    started_at=s.started_at,
                    finished_at=s.finished_at,
                    awaiting_choice=s.awaiting_choice,
                    choices=list(s.choices),
                    last_line=last,
                    elapsed_ms=_elapsed_ms(s),
                    auto_answered=bool(s.choices) and tuple(s.choices) == s.auto_answered,
                )
            )
        return out

    def timeline_text(self, session_id: str, max_segments: int = 200) -> str:
        """带时间戳的输出时间线。"""
        screen = self._screens.get(session_id)
        return screen.timeline(max_segments) if screen is not None else ""

    def screen_text(self, session_id: str) -> str:
        screen = self._screens.get(session_id)
        return screen.tail() if screen is not None else ""

    def running_count(self) -> int:
        with self._lock:
            return sum(1 for s in self._sessions.values() if s.status == SessionStatus.RUNNING)

    # -- 孤儿清理 ------------------------------------------------------
    def cleanup_orphans(self) -> list[dict[str, Any]]:
        """回收"本工具登记过、root 已死但子树仍在"的会话整树。

        返回被清理的会话摘要（用于 UI 报告）。历史遗留的完全无记录的孤儿
        由 psutil 的进程树探测覆盖，但本工具只负责自家登记的会话，避免误杀。
        """
        cleaned: list[dict[str, Any]] = []
        with self._lock:
            sessions = list(self._sessions.values())
        for s in sessions:
            # 仅处理"已结束但曾登记进程树"的会话；其子孙若仍存活即残留。
            if not s.status.is_terminal:
                continue
            reap_tree(s)
            if s.child_pids:
                cleaned.append(
                    {"sessionId": s.session_id, "title": s.title, "children": len(s.child_pids)}
                )
        return cleaned

    # -- 轮询 ----------------------------------------------------------
    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._poll_once()
            except Exception:  # noqa: BLE001
                # 轮询线程一旦因异常退出，界面就再也不会更新（表现为"发消息后
                # 界面不动了"）。这里吞掉单次异常并继续，保证长时间运行稳定。
                log.exception("轮询单次失败，已跳过本轮继续运行")
            self._stop.wait(self._poll_interval)

    def _poll_once(self) -> None:
        with self._lock:
            items = list(self._sessions.items())
        for session_id, session in items:
            backend = self._backends.get(session_id)
            screen = self._screens.get(session_id)
            if backend is None or screen is None:
                continue
            # 读取输出增量（非阻塞：没有数据立即返回）。
            data = backend.read()
            alive = backend.is_alive()
            # 进程已退出时把管道里剩余的输出读干净，否则最后的日志会丢失。
            if not alive:
                while True:
                    tail = backend.read()
                    if not tail:
                        break
                    data += tail
            if data:
                if not session.received_output:
                    # 首个字节到达：用于区分"CLI 根本没输出"和"读取坏了"。
                    session.received_output = True
                    log.info("会话首次收到输出 id=%s 字节=%s", session_id, len(data))
                screen.feed(data)
                # 只渲染一次文本：tail()/text 在长历史下都是 O(行数)，
                # 每轮调用两次会让 4Hz 轮询随历史增长而变慢。
                rendered = screen.tail()
                self._emit(session_id, EVENT_OUTPUT, {"text": rendered})
                awaiting, choices = detect_choice(rendered)
                if awaiting != session.awaiting_choice or choices != session.choices:
                    session.awaiting_choice = awaiting
                    session.choices = choices
                    self._emit(
                        session_id,
                        EVENT_CHOICE,
                        {"awaitingChoice": awaiting, "choices": list(choices)},
                    )
            # 输出停顿一段时间后，把这一屏记入带时间戳的时间线。
            # 必须每轮都检查：停顿意味着"本轮没有数据"，若只在收到数据时才判断，
            # idle_seconds 永远是 0，时间线会一直是空的。
            if session.received_output and screen.idle_seconds >= self._segment_idle_seconds:
                if screen.mark_segment():
                    self._emit(
                        session_id,
                        EVENT_TIMELINE,
                        {"text": screen.timeline(), "segments": len(screen.timeline_lines())},
                    )
            # 自动应答：检测到菜单且用户开启了自动处理时，按策略直接应答。
            if session.awaiting_choice and session.choices:
                session.menu_absent_since = 0.0
                self._maybe_auto_answer(session)
            elif session.auto_answered:
                # 菜单消失后延迟清空状态：TUI 重绘时菜单可能短暂"消失"一两帧，
                # 立刻清空会导致同一菜单被重复应答（多发一次键 = 误操作）。
                # 因此要求菜单持续消失一段时间，才认为是真的结束了。
                if not session.menu_absent_since:
                    session.menu_absent_since = time.monotonic()
                elif time.monotonic() - session.menu_absent_since >= _MENU_GONE_RESET_S:
                    session.auto_answered = ()
                    session.auto_answer_attempts = 0
                    session.auto_answer_last_at = 0.0
                    session.menu_absent_since = 0.0
            # 检测退出
            if not alive and not session.status.is_terminal:
                self._finish(session_id, session, backend)

    def _maybe_auto_answer(self, session: PtySession) -> None:
        """按预设策略自动回应选择菜单。

        关键：菜单出现到 CLI 真正开始读标准输入之间有短暂间隙（TUI 还在重绘），
        此时写入的应答可能被丢弃。因此这里**持续重试**，直到菜单消失或达到
        次数上限——只试一次会出现"日志显示已自动应答、菜单却还在"的情况。
        """
        if not self.auto_answer:
            return
        signature = tuple(session.choices)
        now = time.monotonic()
        if signature != session.auto_answered:
            # 换了一个菜单：重置尝试计数。
            session.auto_answered = signature
            session.auto_answer_attempts = 0
        if session.auto_answer_attempts >= _AUTO_ANSWER_MAX_ATTEMPTS:
            return
        # 每次尝试之间留出冷却时间，避免把按键刷爆。
        if now - session.auto_answer_last_at < _AUTO_ANSWER_RETRY_S:
            return
        session.auto_answer_last_at = now
        session.auto_answer_attempts += 1
        index = _auto_choice_index(session.choices)
        payload = str(index + 1)
        log.info(
            "自动应答会话 id=%s 第 %d/%d 次尝试 -> 发送 %r（选项=%s）",
            session.session_id,
            session.auto_answer_attempts,
            _AUTO_ANSWER_MAX_ATTEMPTS,
            payload,
            [c.strip()[:24] for c in session.choices],
        )
        # 重试发送同一个编号：只有"菜单仍被检测到"时才会走到这里，
        # 因此不会在菜单已关闭后误把编号打进输入框。
        self._queue_input(session.session_id, payload)

    def _finish(self, session_id: str, session: PtySession, backend: _Backend) -> None:
        if session.status == SessionStatus.STOPPED:
            # 用户主动停止：保留 STOPPED，不强改成"已完成"。
            session.finished_at = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
            status = session.status
        else:
            exit_code = getattr(backend, "exit_code", None)
            status = mark_finished(session, 0 if exit_code is None else exit_code)
        if not session.finished_at_ms:
            session.finished_at_ms = time.time() * 1000.0
        # 会话结束前把最后状态记入时间线，否则最后一段会缺失。
        screen = self._screens.get(session_id)
        if screen is not None:
            screen.mark_segment(force=True)
        # 核心：整树回收，消灭 codex/claude 残留子进程。
        reaped = reap_tree(session)
        log.info(
            "会话结束 id=%s status=%s exit=%s 回收子进程=%s",
            session_id,
            status.value,
            session.exit_code,
            reaped,
        )
        self._emit(session_id, EVENT_STATUS, {"status": status.value})

    # -- 事件 ----------------------------------------------------------
    def _emit(self, session_id: str, event: str, payload: dict[str, Any]) -> None:
        if self._on_event is None:
            return
        try:
            self._on_event(session_id, event, payload)
        except Exception:  # noqa: BLE001 - 事件回调异常不应中断轮询
            pass


__all__ = ["TerminalManager", "SessionSummary", "EVENT_OUTPUT", "EVENT_STATUS", "EVENT_CHOICE"]
