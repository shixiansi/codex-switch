"""可选项提示检测。

AI CLI 需要用户确认或选择时，会在屏幕上给出明确的提示。本模块识别两类：

1. 确认型：``Overwrite? [Y/n]``、``Continue (y/N)``
2. 编号选项：连续多行形如 ``› 1. Yes`` / ``2. No`` / ``1) ...``

设计取舍（重要）：早期版本把任意 ``›`` 都当作选项提示，导致 Codex 的**输入提示符**
（``› Ask Codex to do anything``、``› 用户刚输入的文本``）被误判成选项，界面上弹出
一堆毫无意义的"选项"。因此这里要求真正的编号选项列表，宁可漏报也不误报。
"""

from __future__ import annotations

import re

# 确认型提示，如 "Overwrite? [Y/n]" / "Continue (y/N)" / "[y/N]"
_CONFIRM_RE = re.compile(r"\[\s*([Yy])\s*/\s*([Nn])\s*\]|\(\s*([Yy])\s*/\s*([Nn])\s*\)")

# 编号选项行：可选的前导符号（› ❯ > ）+ 数字 + . 或 ) + 文本
_OPTION_LINE_RE = re.compile(r"^\s*[›❯>»]?\s*(\d{1,2})\s*[.)、]\s*(\S.*?)\s*$")

# 至少要有这么多条编号选项，才认为是在等待选择。
_MIN_OPTIONS = 2
# 只看屏幕末尾，避免匹配到历史输出里的旧内容。
_TAIL_CHARS = 800


def detect_choice(text: str) -> tuple[bool, list[str]]:
    """返回 ``(awaiting_choice, choices)``。

    ``awaiting_choice`` 为 True 表示屏幕末尾看起来正在等待用户选择；
    ``choices`` 是提取到的选项标签（确认型给出 是/否）。
    """
    if not text:
        return False, []

    tail = text[-_TAIL_CHARS:]

    # 1) 确认型提示优先：只有两个选项。
    if _CONFIRM_RE.search(tail):
        return True, ["是", "否"]

    # 2) 编号选项：需要连续（允许中间有空行）的多条编号行。
    lines = tail.splitlines()
    options: list[tuple[int, str]] = []
    # 从末尾向上收集，遇到不匹配且已经收集到内容就停止，保证只看最后一段菜单。
    for line in reversed(lines):
        match = _OPTION_LINE_RE.match(line)
        if match:
            options.append((int(match.group(1)), match.group(2)))
            continue
        if line.strip() == "":
            continue
        if options:
            break

    if len(options) < _MIN_OPTIONS:
        return False, []

    options.reverse()
    # 编号必须从 1 开始递增，进一步排除正文里的巧合。
    numbers = [number for number, _ in options]
    if numbers[0] != 1 or numbers != list(range(1, len(numbers) + 1)):
        return False, []

    labels = [label for _, label in options]
    return True, labels


__all__ = ["detect_choice"]
