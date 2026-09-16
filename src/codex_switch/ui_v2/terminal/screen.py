"""终端屏幕文本累积。

首版目标：可用、可测、零额外重依赖。PTY 字节流按行累积为纯文本缓冲，
供 QML 的只读 TextArea 渲染。后续可替换为 pyte 的字符网格以还原色彩与光标。
"""

from __future__ import annotations

import re

# 去掉常见的 ANSI/VT 转义序列，避免不可见字符污染 UI。
_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[()][AB0]|\x1b[=>]")


def _strip_escape(data: bytes) -> str:
    """把字节解码并剥离转义序列。优先 UTF-8，失败再按本地编码兜底。"""
    text = ""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = data.decode("mbcs", errors="replace")
        except LookupError:
            text = data.decode("utf-8", errors="replace")
    return _ANSI_RE.sub("", text)


class TerminalScreen:
    """一个有上限行数的滚动文本缓冲。"""

    def __init__(self, max_lines: int = 5000) -> None:
        self._lines: list[str] = []
        self._max_lines = max_lines

    def feed(self, data: bytes) -> None:
        """追加一段 PTY 输出；按 \\r?\\n 切分并维护行缓冲。"""
        text = _strip_escape(data)
        if not text:
            return
        # 去掉回车符，避免 Windows 控制台文本里出现裸 \r。
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        # 以换行为界切分；保留未完成行（不以换行结尾）作为最后一行的一部分。
        parts = text.split("\n")
        if self._lines:
            self._lines[-1] += parts[0]
        else:
            self._lines.append(parts[0])
        for chunk in parts[1:]:
            self._lines.append(chunk)
        if len(self._lines) > self._max_lines:
            self._lines = self._lines[-self._max_lines:]

    @property
    def text(self) -> str:
        return "\n".join(self._lines)

    def tail(self, lines: int = 400) -> str:
        if lines <= 0 or len(self._lines) <= lines:
            return self.text
        return "… 仅显示最后 " + str(lines) + " 行 …\n" + "\n".join(self._lines[-lines:])

    def clear(self) -> None:
        self._lines.clear()


__all__ = ["TerminalScreen"]
