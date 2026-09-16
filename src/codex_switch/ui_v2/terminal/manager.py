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
from .pty_session import (
    PtySession,
    SessionStatus,
    _Backend,
    mark_finished,
    reap_tree,
    start_session,
)
from .screen import TerminalScreen

# 事件类型
EVENT_OUTPUT = "output"
EVENT_STATUS = "status"
EVENT_CHOICE = "choice"

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
        }


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

    # -- 生命周期 ------------------------------------------------------
    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

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
        )
        with self._lock:
            self._sessions[session_id] = session
            self._screens[session_id] = TerminalScreen()
        backend = start_session(session, backend_factory=backend_factory)
        with self._lock:
            self._backends[session_id] = backend
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
        backend = self._backends.get(session_id)
        if backend is None:
            return
        # 终端行规约：以 CRLF 结束一行，符合多数交互式 CLI 的约定。
        backend.write(str(data or "") + "\r\n")
        # 用户输入后，CLI 通常会清掉提示；乐观地关闭"等待选择"态。
        session = self._sessions.get(session_id)
        if session is not None and session.awaiting_choice:
            session.awaiting_choice = False
            session.choices = []
            self._emit(session_id, EVENT_CHOICE, {"awaitingChoice": False, "choices": []})

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
                )
            )
        return out

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
            self._poll_once()
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
                screen.feed(data)
                self._emit(session_id, EVENT_OUTPUT, {"text": screen.tail()})
                awaiting, choices = detect_choice(screen.text)
                if awaiting != session.awaiting_choice or choices != session.choices:
                    session.awaiting_choice = awaiting
                    session.choices = choices
                    self._emit(
                        session_id,
                        EVENT_CHOICE,
                        {"awaitingChoice": awaiting, "choices": list(choices)},
                    )
            # 检测退出
            if not alive and not session.status.is_terminal:
                self._finish(session_id, session, backend)

    def _finish(self, session_id: str, session: PtySession, backend: _Backend) -> None:
        if session.status == SessionStatus.STOPPED:
            # 用户主动停止：保留 STOPPED，不强改成"已完成"。
            session.finished_at = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
            status = session.status
        else:
            exit_code = getattr(backend, "exit_code", None)
            status = mark_finished(session, 0 if exit_code is None else exit_code)
        # 核心：整树回收，消灭 codex/claude 残留子进程。
        reap_tree(session)
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
