"""AI 终端多开管理器：业务层（无 Qt 依赖）。

每个会话在真正的 PTY 中运行一个交互式 AI CLI（codex / claude 等），
并登记整棵进程树，父进程退出时整树回收，实现"零残留"。
"""

from __future__ import annotations

from .manager import (
    TerminalManager,
    SessionSummary,
    EVENT_OUTPUT,
    EVENT_STATUS,
    EVENT_CHOICE,
    EVENT_TIMELINE,
)
from .pty_session import PtySession, SessionStatus, check_pty_backend
from .screen import TerminalScreen
from .completion import ChoiceMenu, detect_choice, detect_menu
from .input_assist import CommandHint, InputHistory, command_hints
from .cli_history import (
    CLI_KINDS,
    ClaudeHistorySource,
    CodexHistorySource,
    PromptHistoryReader,
    claude_home,
    codex_home,
    detect_cli,
    sessions_root,
)
from .logging_setup import get_logger, log_path

__all__ = [
    "TerminalManager",
    "SessionSummary",
    "EVENT_OUTPUT",
    "EVENT_STATUS",
    "EVENT_CHOICE",
    "EVENT_TIMELINE",
    "PtySession",
    "SessionStatus",
    "TerminalScreen",
    "check_pty_backend",
    "ChoiceMenu",
    "detect_choice",
    "detect_menu",
    "CommandHint",
    "InputHistory",
    "PromptHistoryReader",
    "CLI_KINDS",
    "ClaudeHistorySource",
    "CodexHistorySource",
    "claude_home",
    "codex_home",
    "command_hints",
    "detect_cli",
    "get_logger",
    "log_path",
    "sessions_root",
]
