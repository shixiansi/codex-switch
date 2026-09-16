"""终端屏幕模型：基于 pyte 的 VT100 解析。

AI CLI（codex / claude）会输出大量光标定位序列（如 ``ESC[1;22H``）来重绘界面，
简单的"追加文本"缓冲无法正确渲染，会把内容错位或丢失。这里用 pyte 维护一个
真正的字符网格，按光标位置落字，再导出为文本供 QML 渲染。
"""

from __future__ import annotations

import codecs

import pyte

DEFAULT_COLUMNS = 120
DEFAULT_LINES = 40


class TerminalScreen:
    """维护一块 VT 字符网格，并可导出为纯文本。"""

    def __init__(self, columns: int = DEFAULT_COLUMNS, lines: int = DEFAULT_LINES) -> None:
        self._columns = columns
        self._lines = lines
        self._screen = pyte.Screen(columns, lines)
        # strict=False：遇到未知/不完整的转义序列时忽略而不是抛错，
        # 保证 CLI 输出的任何片段都不会中断渲染。
        self._stream = pyte.Stream(self._screen, strict=False)
        # 增量解码器：PTY 的读取边界会切开多字节字符（中文），
        # 用有状态解码器缓存半个字符，避免输出出现 U+FFFD。
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self._use_utf8 = True

    def feed(self, data: bytes) -> None:
        """喂入一段 PTY 字节流。"""
        if not data:
            return
        text = self._decode(data)
        if not text:
            return
        try:
            self._stream.feed(text)
        except Exception:  # noqa: BLE001 - 渲染失败绝不应中断会话
            pass

    def _decode(self, data: bytes) -> str:
        """增量解码 PTY 字节，跨块保留未完成的多字节字符。"""
        if self._use_utf8:
            try:
                return self._decoder.decode(data)
            except UnicodeDecodeError:
                # 一旦确定不是 UTF-8，就不再回退（避免中文 Windows 的 GBK 输出乱码）。
                self._use_utf8 = False
        try:
            return data.decode("mbcs", errors="replace")
        except LookupError:
            return data.decode("utf-8", errors="replace")

    @property
    def text(self) -> str:
        """完整屏幕内容，已去掉尾部空白行。"""
        return "\n".join(self._visible_lines())

    @property
    def last_line(self) -> str:
        """最后一屏非空行，用于会话列表的一行预览。"""
        for row in reversed(self._visible_lines()):
            if row.strip():
                return row.strip()
        return ""

    def tail(self, lines: int = 400) -> str:
        rows = self._visible_lines()
        if lines <= 0 or len(rows) <= lines:
            return "\n".join(rows)
        return "… 仅显示最后 " + str(lines) + " 行 …\n" + "\n".join(rows[-lines:])

    def clear(self) -> None:
        self._screen.reset()

    def _visible_lines(self) -> list[str]:
        # display 每行定宽，右补空格；去掉行尾空白并丢弃完全空白的尾部行，
        # 避免界面上出现大片空白。
        rows = [line.rstrip() for line in self._screen.display]
        while rows and rows[-1] == "":
            rows.pop()
        return rows


__all__ = ["TerminalScreen"]
