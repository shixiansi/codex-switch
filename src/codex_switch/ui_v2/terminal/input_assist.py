"""输入框的历史记录与命令提示（纯逻辑，无 Qt 依赖）。

界面需要两个键盘小功能：

1. **↑ / ↓ 翻历史**：把之前发过的消息调回输入框，避免重复敲长提示词。
   与 shell 一致：↑ 往更早翻，↓ 往更近翻，翻到底部之外则回到"未编辑"状态。
2. **AI 指令提示**：输入 ``/`` 时给出斜杠命令候选，可用 ↑↓ 选择、Tab 补全。

这两件事都只跟字符串打交道，所以单独成模块，便于直接跑单测——
放进 QML 里会变成难以覆盖的 JS 代码。
"""

from __future__ import annotations

from dataclasses import dataclass, field

# 历史上限。过长会让 ↑ 翻很久才回到想找的那条，也没有保留价值。
MAX_HISTORY = 200


@dataclass
class InputHistory:
    """按会话隔离的输入历史。

    每个会话各存一份：不同会话（不同项目/不同 CLI）的消息混在一起翻会
    很混乱，而且容易把 A 项目的提示词误发到 B 项目。
    """

    _per_session: dict[str, list[str]] = field(default_factory=dict)
    # 每个会话当前的浏览位置：None 表示"不在翻历史"（停在用户正在编辑的内容上）。
    _cursor: dict[str, int | None] = field(default_factory=dict)
    # 开始翻历史前用户已输入的内容，翻回底部时恢复它。
    _draft: dict[str, str] = field(default_factory=dict)

    def record(self, session_id: str, text: str) -> None:
        """记下一条真正发出的消息，并重置浏览位置。"""
        value = str(text or "").strip()
        self._cursor[session_id] = None
        self._draft[session_id] = ""
        if not value:
            return
        items = self._per_session.setdefault(session_id, [])
        # 与上一条相同则不重复记录，避免连按回车把历史刷满。
        if items and items[-1] == value:
            return
        items.append(value)
        if len(items) > MAX_HISTORY:
            del items[: len(items) - MAX_HISTORY]

    def entries(self, session_id: str) -> list[str]:
        return list(self._per_session.get(session_id, ()))

    def forget(self, session_id: str) -> None:
        """会话被清除时一并丢弃它的历史，避免长跑后越堆越多。"""
        self._per_session.pop(session_id, None)
        self._cursor.pop(session_id, None)
        self._draft.pop(session_id, None)

    def previous(self, session_id: str, draft: str = "") -> str | None:
        """↑：返回更早的一条；已经到最早则返回 None（表示不动）。"""
        items = self._per_session.get(session_id) or []
        if not items:
            return None
        cursor = self._cursor.get(session_id)
        if cursor is None:
            # 第一次按 ↑：记下当前草稿，从最新一条开始往回翻。
            self._draft[session_id] = str(draft or "")
            cursor = len(items)
        if cursor <= 0:
            return None
        cursor -= 1
        self._cursor[session_id] = cursor
        return items[cursor]

    def next(self, session_id: str) -> str | None:
        """↓：返回更近的一条；越过最新一条则回到最初编辑的草稿。"""
        items = self._per_session.get(session_id) or []
        cursor = self._cursor.get(session_id)
        if cursor is None:
            return None
        cursor += 1
        if cursor >= len(items):
            # 翻出历史末尾：回到开始翻之前的草稿内容。
            self._cursor[session_id] = None
            return self._draft.get(session_id, "")
        self._cursor[session_id] = cursor
        return items[cursor]

    def reset_cursor(self, session_id: str) -> None:
        """用户手动编辑输入框时调用，退出"正在翻历史"状态。"""
        self._cursor[session_id] = None
        self._draft[session_id] = ""


# 斜杠命令候选。
#
# 这些是 codex / claude 这类 CLI 的常用指令。做成静态表而不是向 CLI 查询：
# 查询需要在 TUI 里输入字符再读屏，既慢又容易干扰用户正在进行的输入。
# 表里的项目在提示里会标注用途，用户不必记住。
SLASH_COMMANDS: tuple[tuple[str, str], ...] = (
    ("/model", "切换模型"),
    ("/approvals", "调整审批/自动执行策略"),
    ("/new", "开始一个新会话"),
    ("/resume", "恢复历史会话"),
    ("/init", "为项目生成说明文件"),
    ("/compact", "压缩上下文以节省额度"),
    ("/status", "查看当前会话状态"),
    ("/diff", "查看本次改动"),
    ("/review", "审查代码改动"),
    ("/undo", "撤销上一步改动"),
    ("/help", "查看全部指令"),
    ("/quit", "退出 CLI"),
)


@dataclass
class CommandHint:
    """当前应该在提示条里展示什么。"""

    visible: bool = False
    items: list[dict[str, str]] = field(default_factory=list)
    # 高亮项下标（-1 表示没有高亮）。
    selected: int = -1


def command_hints(text: str, *, limit: int = 8) -> CommandHint:
    """根据输入框当前内容给出指令候选。

    只有在**整行以 ``/`` 开头且还没打出空格**时才提示：一旦用户输入了参数
    （``/model gpt-5``），再弹候选就是干扰。
    """
    value = str(text or "")
    if not value.startswith("/"):
        return CommandHint()
    if " " in value or "\t" in value:
        return CommandHint()

    prefix = value.lower()
    matched = [
        {"name": name, "description": description}
        for name, description in SLASH_COMMANDS
        if name.startswith(prefix)
    ]
    if not matched:
        return CommandHint()
    return CommandHint(visible=True, items=matched[:limit], selected=0)


__all__ = [
    "MAX_HISTORY",
    "SLASH_COMMANDS",
    "CommandHint",
    "InputHistory",
    "command_hints",
]
