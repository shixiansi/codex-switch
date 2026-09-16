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

# 编号选项行：可选的前导符号（› ❯ > »）+ 数字 + . 或 ) + 文本
_OPTION_LINE_RE = re.compile(r"^(\s*)([›❯>»]?)(\s*)(\d{1,2})\s*[.)、]\s*(\S.*?)\s*$")

# TUI 菜单总会把"当前选中项"用符号标出来。正文里的编号列表没有这个标记，
# 这是区分"真菜单"和"AI 回复里的 1. 2. 3."的关键。
_SELECTION_MARKERS = "›❯>»"

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

    # 2) 编号选项。真实菜单里，选项的说明文字会换行成缩进的续行
    #    （codex 登录菜单就是这样），所以不能"遇到非选项行就停止收集"，
    #    否则会漏掉菜单开头带选中标记的那一项。这里改为扫描整段末尾，
    #    再在结果里找"从 1 开始连续递增"的那一段。
    found: list[tuple[int, str, bool]] = []
    for line in tail.splitlines():
        match = _OPTION_LINE_RE.match(line)
        if not match:
            continue
        marker = match.group(2)
        # 注意：必须写成 `if marker and ...`。空字符串是任何字符串的子串，
        # `"" in "›❯>»"` 在 Python 里为 True，直接用 in 会让"无标记"也判为已选中。
        selected = bool(marker) and marker in _SELECTION_MARKERS
        found.append((int(match.group(4)), match.group(5), selected))

    if len(found) < _MIN_OPTIONS:
        return False, []

    # 取最后一段"从 1 开始、编号连续"的选项，作为当前菜单。
    run: list[tuple[int, str, bool]] = []
    for item in found:
        expected = len(run) + 1
        if item[0] == expected:
            run.append(item)
        elif item[0] == 1:
            run = [item]
        # 编号跳跃：丢弃这段，等待下一次从 1 开始。
        elif run:
            run = []

    if len(run) < _MIN_OPTIONS:
        return False, []

    # 必须是真正的 TUI 菜单：至少有一项带选中标记（`›` / `>` 等）。
    # 否则 AI 回复里的普通编号列表 "1. xxx  2. xxx" 会被误判成菜单，
    # 弹出一条毫无意义的选项栏。
    if not any(marked for _, _, marked in run):
        return False, []

    return True, [_clean_label(label) for _, label, _ in run]


def _clean_label(label: str) -> str:
    """清理选项标签里的对齐填充空格。

    codex 的授权菜单是两列布局（选项名左对齐、说明另起一列），导出后选项名与
    说明之间会留下一长串用于对齐的空格，例如
    ``Allow                   Run the tool and continue.``。
    这里把连续空格压成单个分隔符，让界面上显示的按钮文字可读。
    """
    return re.sub(r"\s{2,}", "  ", label).strip()


__all__ = ["detect_choice"]
