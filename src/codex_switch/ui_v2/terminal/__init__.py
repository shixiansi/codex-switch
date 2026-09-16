"""AI 终端多开管理器：业务层（无 Qt 依赖）。

每个会话在真正的 PTY 中运行一个交互式 AI CLI（codex / claude 等），
并登记整棵进程树，父进程退出时整树回收，实现"零残留"。
"""

from __future__ import annotations

from .manager import TerminalManager, SessionSummary, EVENT_OUTPUT, EVENT_STATUS, EVENT_CHOICE
from .pty_session import PtySession, SessionStatus
from .screen import TerminalScreen
from .completion import detect_choice

__all__ = [
    "TerminalManager",
    "SessionSummary",
    "EVENT_OUTPUT",
    "EVENT_STATUS",
    "EVENT_CHOICE",
    "PtySession",
    "SessionStatus",
    "TerminalScreen",
    "detect_choice",
]
