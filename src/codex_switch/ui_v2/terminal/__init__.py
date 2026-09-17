"""AI 终端多开管理器：业务层（无 Qt 依赖）。

每个会话在真正的 PTY 中运行一个交互式 AI CLI（codex / claude 等），
并登记整棵进程树，父进程退出时整树回收，实现"零残留"。

自动应答带**风险审查闸门**：是否替用户按键由 :mod:`review` 的规则链判定
（静默放行 / 通知 / 要求授权 / 拒绝），自主写入只允许从一个出口发出。
"""

from __future__ import annotations

from .manager import (
    TerminalManager,
    SessionSummary,
    PendingReview,
    EVENT_OUTPUT,
    EVENT_STATUS,
    EVENT_CHOICE,
    EVENT_TIMELINE,
    EVENT_REVIEW,
    REVIEW_PENDING,
    REVIEW_APPROVED,
    REVIEW_DENIED,
    REVIEW_EXPIRED,
    REVIEW_DISMISSED,
)
from .pty_session import PtySession, SessionStatus, check_pty_backend
from .screen import TerminalScreen
from .completion import ChoiceMenu, detect_choice, detect_choice_prompt, detect_menu
from .input_assist import CommandHint, InputHistory, command_hints
from .review import (
    Action,
    AnswerRequest,
    Decision,
    MODE_BALANCED,
    MODE_DESCRIPTIONS,
    MODE_FULL,
    MODE_LABELS,
    MODE_OBSERVE,
    MODE_OFF,
    MODE_STRICT,
    MODES,
    PolicyConfig,
    ReviewPolicy,
    Risk,
    normalize_mode,
)
from .policy_store import (
    POLICY_FILENAME,
    config_from_dict,
    config_to_dict,
    load_config,
    policy_path,
    save_config,
)
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
from .notifier import SystemNotifier, icon_path
from .sound import SoundPlayer, is_supported as sound_is_supported

__all__ = [
    "TerminalManager",
    "SessionSummary",
    "PendingReview",
    "EVENT_OUTPUT",
    "EVENT_STATUS",
    "EVENT_CHOICE",
    "EVENT_TIMELINE",
    "EVENT_REVIEW",
    "REVIEW_PENDING",
    "REVIEW_APPROVED",
    "REVIEW_DENIED",
    "REVIEW_EXPIRED",
    "REVIEW_DISMISSED",
    "PtySession",
    "SessionStatus",
    "TerminalScreen",
    "check_pty_backend",
    "ChoiceMenu",
    "detect_choice",
    "detect_choice_prompt",
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
    # 风险审查
    "Action",
    "AnswerRequest",
    "Decision",
    "MODE_BALANCED",
    "MODE_DESCRIPTIONS",
    "MODE_FULL",
    "MODE_LABELS",
    "MODE_OBSERVE",
    "MODE_OFF",
    "MODE_STRICT",
    "MODES",
    "PolicyConfig",
    "ReviewPolicy",
    "Risk",
    "normalize_mode",
    "POLICY_FILENAME",
    "config_from_dict",
    "config_to_dict",
    "load_config",
    "policy_path",
    "save_config",
    # 通知与提示音
    "SystemNotifier",
    "icon_path",
    "SoundPlayer",
    "sound_is_supported",
]
