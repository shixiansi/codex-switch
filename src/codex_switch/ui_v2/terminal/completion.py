"""可选项提示检测（轻量、够用）。

AI CLI 在需要用户选择时会输出形如 `[Y/n]`、`(y/N)`、`? Select … ›` 的提示，
本模块从最近一段输出里识别"正在等待选择"并尽量提取选项文本，供 UI 浮出选项条。
这是 YAGNI 的最小实现：只覆盖最常见的两种模式，不解析复杂的 TUI 菜单。
"""

from __future__ import annotations

import re

# 确认型提示，如 "Overwrite? [Y/n]" / "Continue (y/N)"
_CONFIRM_RE = re.compile(r"\[([Yy])\/([Nn])\]|\(([Yy])\/([Nn])\)")

# 选择型提示，如 "? Which model ›" / "Select a plan:"
_CHOICE_RE = re.compile(r"[?›]\s*(.+?)(?:\s*:|$)", re.MULTILINE)

_SENTINEL = -1


def detect_choice(text: str) -> tuple[bool, list[str]]:
    """返回 (awaiting_choice, choices)。

    awaiting_choice=True 表示输出尾部看起来在等待用户输入；
    choices 为提取到的选项标签（确认型给出 是/否）。
    """
    if not text:
        return False, []

    tail = text[-600:]
    confirm = _CONFIRM_RE.search(tail)
    if confirm:
        return True, ["是", "否"]

    matches = _CHOICE_RE.findall(tail)
    choices = [m.strip() for m in matches if m.strip()]
    # 去重保序
    seen: set[str] = set()
    unique: list[str] = []
    for item in choices:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    if unique:
        return True, unique
    return False, []


__all__ = ["detect_choice"]
