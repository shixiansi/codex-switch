"""可选项提示检测。

AI CLI 需要用户确认或选择时，会在屏幕上给出明确的提示。本模块识别三类：

1. 确认型：``Overwrite? [Y/n]``、``Continue (y/N)``
2. 编号选项：连续多行形如 ``› 1. Yes`` / ``2. No`` / ``1) ...``
3. 无编号列表：``> 1d ago  某次会话`` 这种靠方向键移动的列表菜单，
   底部通常带一行按键提示（``enter resume  ctrl+a archive  esc exit``）。
   codex 的 ``resume`` 会话选择器就是这一类。

设计取舍（重要）：早期版本把任意 ``›`` 都当作选项提示，导致 Codex 的**输入提示符**
（``› Ask Codex to do anything``、``› 用户刚输入的文本``）被误判成选项，界面上弹出
一堆毫无意义的"选项"。因此这里要求真正的编号选项列表，宁可漏报也不误报。
无编号列表更危险（更容易把正文当成菜单），所以额外要求底部存在**按键提示行**，
且列表里至少有一项带选中标记。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# 确认型提示，如 "Overwrite? [Y/n]" / "Continue (y/N)" / "[y/N]"
_CONFIRM_RE = re.compile(r"\[\s*([Yy])\s*/\s*([Nn])\s*\]|\(\s*([Yy])\s*/\s*([Nn])\s*\)")

# 编号选项行：可选的前导符号（› ❯ > »）+ 数字 + . 或 ) + 文本
_OPTION_LINE_RE = re.compile(r"^(\s*)([›❯>»]?)(\s*)(\d{1,2})\s*[.)、]\s*(\S.*?)\s*$")

# 无编号列表行：可选选中标记 + 内容。用于 resume 这类列表菜单。
#
# 前导空格数量不一（真实 codex 输出里选中项前是两格、其余是四格），
# 所以统一用 ``\s+`` 吸收缩进，不再区分"带标记"与"缩进"两种分支。
_PLAIN_ROW_RE = re.compile(r"^(\s*)([›❯>»])?\s*(\S.*?)\s*$")

# "还有更多"提示行（``↓ more`` / ``↑ more``）。它是列表与页脚之间的装饰，
# 既不是列表项也不该打断收集，必须单独识别后跳过。
_MORE_RE = re.compile(r"^\s*[↑↓⇡⇣]\s*more\s*$", re.I)

# TUI 菜单总会把"当前选中项"用符号标出来。正文里的编号列表没有这个标记，
# 这是区分"真菜单"和"AI 回复里的 1. 2. 3."的关键。
_SELECTION_MARKERS = "›❯>»"

# 按键提示行里的按键名。出现两个以上不同按键，基本可以认定是交互菜单的页脚。
_HINT_KEY_RE = re.compile(r"(?<![\w+])(enter|esc|tab|ctrl\+\w|shift\+tab)(?![\w+])", re.I)

# 至少要有这么多条编号选项，才认为是在等待选择。
_MIN_OPTIONS = 2
# 只看屏幕末尾，避免匹配到历史输出里的旧内容。
#
# 取尾部时**按行对齐**（见 _tail_lines）：直接切字符串会把第一行截成半截，
# 那一行既匹配不上列表项，又会因为"不像列表项"而让整块作废——
# 真实 codex resume 输出正是这样被漏掉的。
#
# 窗口要比一屏（40 行）宽裕：列表很长时 TUI 会把列表滚动到只露出后半段，
# 若窗口刚好卡在选中项上方，就会因为"找不到选中标记"而整个菜单认不出来。
_TAIL_CHARS = 6000
_TAIL_LINES = 60
# 从末尾向上找按键提示行时最多看几行：页脚可能有多行（codex 的 resume
# 是两行），但也不该一路往上找到正常输出里。
_FOOTER_SCAN_LINES = 6

# 分页行，如 "  1 / 4 · 100% ────────────"。它是 TUI 的页脚装饰，
# 既不是按键提示也不是列表项，查找与收集时都要跳过。
_PAGINATION_RE = re.compile(r"^\s*\d+\s*/\s*\d+\s*[·⋅]|^\s*[─━-]{4,}\s*$|─{4,}")


def _is_footer_noise(line: str) -> bool:
    """这一行是否是页脚装饰（空行 / 分页行 / "更多"提示），而不是列表项。"""
    if not line.strip():
        return True
    if _PAGINATION_RE.search(line):
        return True
    return bool(_MORE_RE.match(line))


def _tail_lines(text: str, max_chars: int = _TAIL_CHARS, max_lines: int = _TAIL_LINES) -> list[str]:
    """取屏幕末尾的若干行，**按整行切分**。

    不能直接 ``text[-N:]``：那会把第一行截成半截，而半截行既不像列表项、
    也不像页脚，会让整块列表收集作废。真实 codex resume 输出正是因此被漏掉。
    """
    lines = [line for line in text.splitlines()]
    if len(lines) > max_lines:
        lines = lines[-max_lines:]
    # 再按字符数收敛一次，同样保持整行。
    total = 0
    kept: list[str] = []
    for line in reversed(lines):
        total += len(line) + 1
        if kept and total > max_chars:
            break
        kept.append(line)
    kept.reverse()
    return kept


@dataclass
class ChoiceMenu:
    """一次菜单检测的结果。

    除了选项文本，还带上"当前选中第几项"与菜单种类：

    * ``confirm``  —— ``[Y/n]`` 这类确认提示，应答要发 ``y`` / ``n``；
    * ``numbered`` —— 带数字编号的菜单，可以直接发编号选中；
    * ``list``     —— 无编号的列表菜单（codex 的 resume），**必须**用方向键
      把光标移过去再回车；发数字会被当成搜索关键词，表现为"看得到却选不中"。

    区分这三者是必要的：早先只有"发编号"一条路径，于是列表菜单点了没反应。
    """

    awaiting: bool = False
    choices: list[str] = field(default_factory=list)
    # 当前高亮项下标；-1 表示屏幕上没有可辨认的选中标记。
    selected: int = -1
    # confirm / numbered / list
    kind: str = "numbered"

    @property
    def numbered(self) -> bool:
        """选项是否带数字编号（点击可直接发编号）。"""
        return self.kind == "numbered"


def _clean_label(label: str) -> str:
    """清理选项标签里的对齐填充空格。

    codex 的授权菜单是两列布局（选项名左对齐、说明另起一列），导出后选项名与
    说明之间会留下一长串用于对齐的空格，例如
    ``Allow                   Run the tool and continue.``。
    这里把连续空格压成单个分隔符，让界面上显示的按钮文字可读。
    """
    return re.sub(r"\s{2,}", "  ", label).strip()


def _detect_confirm(lines: list[str]) -> ChoiceMenu | None:
    if _CONFIRM_RE.search("\n".join(lines)):
        return ChoiceMenu(awaiting=True, choices=["是", "否"], selected=0, kind="confirm")
    return None


def _detect_numbered(lines: list[str]) -> ChoiceMenu | None:
    """编号选项菜单（带选中标记，且编号从 1 起连续）。"""
    found: list[tuple[int, str, bool]] = []
    for line in lines:
        match = _OPTION_LINE_RE.match(line)
        if not match:
            continue
        marker = match.group(2)
        # 注意：必须写成 `if marker and ...`。空字符串是任何字符串的子串，
        # `"" in "›❯>»"` 在 Python 里为 True，直接用 in 会让"无标记"也判为已选中。
        selected = bool(marker) and marker in _SELECTION_MARKERS
        found.append((int(match.group(4)), match.group(5), selected))

    if len(found) < _MIN_OPTIONS:
        return None

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
        return None

    # 必须是真正的 TUI 菜单：至少有一项带选中标记（`›` / `>` 等）。
    # 否则 AI 回复里的普通编号列表 "1. xxx  2. xxx" 会被误判成菜单，
    # 弹出一条毫无意义的选项栏。
    if not any(marked for _, _, marked in run):
        return None

    selected = next((index for index, item in enumerate(run) if item[2]), -1)
    return ChoiceMenu(
        awaiting=True,
        choices=[_clean_label(label) for _, label, _ in run],
        selected=selected,
        kind="numbered",
    )


def _detect_plain_list(lines: list[str]) -> ChoiceMenu | None:
    """无编号的列表菜单（如 codex 的 resume 会话选择器）。

    判定条件刻意收紧，避免把 AI 正文里的引用块当成菜单：

    1. 屏幕尾部存在**按键提示行**（含两个以上按键名）；
    2. 提示行上方是一段连续列表项，至少两行；
    3. 这段里至少有一行带选中标记。

    三条同时满足才认。缺任何一条都返回 None，宁可漏报。

    实现要点（每一条都来自真实 codex 输出）：

    * 页脚是**多行**的（第二行还有 ``ctrl+o ... ↑/↓ browse``），
      所以不能只看最后一行；
    * 页脚与列表之间夹着分页行（``1 / 25 · 0% ────``）；
    * 列表末尾还有一行 ``↓ more``，既不是列表项也不该打断收集；
    * 缩进不固定：选中项前是两格、其余是四格。
    """
    if len(lines) < _MIN_OPTIONS + 1:
        return None

    # 在尾部有限几行内找按键提示行。取**最靠上**的那一行：页脚的第一行
    # 才是"按键说明"，其下的补充行（ctrl+o / ctrl+t ...）不是。
    hint_index = -1
    start = max(0, len(lines) - _FOOTER_SCAN_LINES)
    for index in range(start, len(lines)):
        line = lines[index]
        if not line.strip() or _PAGINATION_RE.search(line):
            continue
        keys = {match.group(1).lower() for match in _HINT_KEY_RE.finditer(line)}
        if len(keys) >= 2:
            hint_index = index
            break
    if hint_index < 0:
        return None

    # 提示行与列表之间可能夹着空行/分页行，先跳掉。
    cursor = hint_index - 1
    while cursor >= 0 and _is_footer_noise(lines[cursor]):
        cursor -= 1

    # 再往上收集连续列表项。
    block: list[str] = []
    while cursor >= 0:
        if not lines[cursor].strip():
            break
        block.append(lines[cursor])
        cursor -= 1
    block.reverse()

    if len(block) < _MIN_OPTIONS:
        return None

    # 逐行解析：带标记的算一项并记录选中位置。
    labels: list[str] = []
    selected = -1
    for raw in block:
        # "还有更多"行是列表与页脚之间的装饰，跳过而不是作废整块。
        if _MORE_RE.match(raw):
            continue
        match = _PLAIN_ROW_RE.match(raw)
        if not match:
            # 块里出现不像列表项的行（例如说明文字）：整块作废，避免拼出
            # 一个"半真半假"的菜单让用户点到错误的东西。
            return None
        marker = match.group(2) or ""
        if marker and marker in _SELECTION_MARKERS and selected < 0:
            selected = len(labels)
        label = _clean_label(match.group(3) or "")
        if not label:
            return None
        labels.append(label)

    if len(labels) < _MIN_OPTIONS or selected < 0:
        return None

    # 很长的段落更像是正文而不是菜单项。
    if any(len(label) > 200 for label in labels):
        return None

    return ChoiceMenu(awaiting=True, choices=labels, selected=selected, kind="list")


def detect_menu(text: str) -> ChoiceMenu:
    """检测屏幕末尾是否是一个等待选择的菜单。

    按"确认型 → 编号菜单 → 无编号列表"的顺序尝试；编号菜单优先于无编号列表，
    因为它更明确，误判风险更低。
    """
    if not text:
        return ChoiceMenu()

    lines = _tail_lines(text)
    if not lines:
        return ChoiceMenu()

    for detector in (_detect_confirm, _detect_numbered, _detect_plain_list):
        menu = detector(lines)
        if menu is not None:
            return menu
    return ChoiceMenu()


def detect_choice(text: str) -> tuple[bool, list[str]]:
    """返回 ``(awaiting_choice, choices)``。

    保留这个二元组接口给既有调用方；需要选中项信息时请用 :func:`detect_menu`。
    """
    menu = detect_menu(text)
    return menu.awaiting, menu.choices


__all__ = ["ChoiceMenu", "detect_choice", "detect_menu"]
