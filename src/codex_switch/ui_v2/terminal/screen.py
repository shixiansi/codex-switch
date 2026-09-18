"""终端屏幕模型：基于 pyte 的 VT100 解析。

AI CLI（codex / claude）会输出大量光标定位序列（如 ``ESC[1;22H``）来重绘界面，
简单的"追加文本"缓冲无法正确渲染，会把内容错位或丢失。这里用 pyte 维护一个
真正的字符网格，按光标位置落字，再导出为文本供 QML 渲染。

使用 ``HistoryScreen`` 而非 ``Screen``：TUI 只维护一屏内容，旧输出会被覆盖；
带滚动历史的屏幕能把滚出画面的行保留下来，用户才能回看 AI 的历史动作。
"""

from __future__ import annotations

import codecs
import re
import time

import pyte

DEFAULT_COLUMNS = 120
DEFAULT_LINES = 40
# 保留的滚动历史行数，供界面向上翻阅。
DEFAULT_HISTORY = 2000
# 时间线最多保留的段落数，避免长时间运行无限增长。
DEFAULT_MAX_SEGMENTS = 500

# 备用屏幕的进入/退出序列：ESC[?1049h / ESC[?1049l。
# 捕获组只取最后的 h/l —— 用它判断"进入还是退出"。
_ALT_SCREEN_RE = re.compile(r"\x1b\[\?1049([hl])")

# 可能是"半截备用屏幕序列"的开头。PTY 的读取边界会把序列切开，
# 这些前缀先攒着，等后续字节到齐再判定，避免误当普通文本渲染出来。
_PARTIAL_PREFIXES = tuple(
    "\x1b[?1049"[: length] for length in range(1, len("\x1b[?1049") + 1)
)


def _partial_alt_suffix(text: str) -> int:
    """若 ``text`` 以半截备用屏幕序列结尾，返回该尾巴的长度，否则 0。"""
    for size in range(min(len(text), len("\x1b[?1049")), 0, -1):
        if text[-size:] in _PARTIAL_PREFIXES:
            return size
    return 0


class TerminalScreen:
    """维护一块带滚动历史的 VT 字符网格，并可导出为纯文本。

    同时维护一条**带时间戳的时间线**：每当输出出现一段停顿后，就把**这一段真正
    新增的输出**记为一个段落。

    早期版本存的是**整屏快照**，于是每一段都把 banner、工作目录等固定内容完整
    重印一遍——实测三段输出里 ``OpenAI Codex`` 出现 3 次、``model:`` 3 次，
    时间线因此几乎没有阅读价值（用户的原话是"一点用没有"）。
    改成增量后，每个段落对应一个事件，"每次工具调用/回复前面带时间戳"才成立。

    **备用屏幕**：codex 的选择器（resume / 审批菜单）跑在备用屏幕里
    （``ESC[?1049h`` 进入、``ESC[?1049l`` 退出）。pyte 会把 1049 记进模式集合，
    却**不做任何切换**——实测进入再退出后，备用屏内容赖在屏幕上、主屏内容
    反而不见了。表现为"选择器关掉之后界面就停在选择器那一屏"。
    这里自己实现换屏：进入时存下主屏并清空，退出时把主屏还原。
    """

    def __init__(
        self,
        columns: int = DEFAULT_COLUMNS,
        lines: int = DEFAULT_LINES,
        history: int = DEFAULT_HISTORY,
        max_segments: int = DEFAULT_MAX_SEGMENTS,
    ) -> None:
        self._columns = columns
        self._lines = lines
        self._history = history
        self._screen = pyte.HistoryScreen(columns, lines, history=history)
        # strict=False：遇到未知/不完整的转义序列时忽略而不是抛错，
        # 保证 CLI 输出的任何片段都不会中断渲染。
        self._stream = pyte.Stream(self._screen, strict=False)
        # 增量解码器：PTY 的读取边界会切开多字节字符（中文），
        # 用有状态解码器缓存半个字符，避免输出出现 U+FFFD。
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self._use_utf8 = True
        # 时间线：[(时间戳秒, 该段**新增**的输出文本)]
        self._segments: list[tuple[float, str]] = []
        # 上一次打点时的完整屏幕行，用于算出"这一段新增了什么"。
        self._prev_lines: list[str] = []
        # 本段**第一份新输出**到达的时刻；0 表示当前没有正在累积的段落。
        #
        # 时间戳取"开始"而不是"停顿被发现的时刻"：工具调用可能跑很久，
        # 打点发生在它输出结束之后，那样记下来的是"它什么时候安静下来"，
        # 而不是"它什么时候发生"。用户的诉求正是后者。
        self._segment_started_at = 0.0
        self._max_segments = max_segments
        self._last_activity = 0.0
        self._dirty = False
        # 备用屏幕：进入时把主屏文本与主屏时间线存下来，退出时还原。
        self._in_alt_screen = False
        self._saved_lines: list[str] = []
        self._saved_segments: list[tuple[float, str]] = []
        self._saved_prev_lines: list[str] = []
        # 跨读取的未完成序列（见 _split_alt_screen）。
        self._pending_alt = ""

    def feed(self, data: bytes) -> None:
        """喂入一段 PTY 字节流。"""
        if not data:
            return
        text = self._decode(data)
        if not text:
            return
        now = time.time()
        self._last_activity = now
        # 本段的第一份新输出：记下它的时刻作为时间戳。
        if not self._segment_started_at:
            self._segment_started_at = now
        self._dirty = True
        try:
            for chunk in self._split_alt_screen(text):
                if chunk:
                    self._stream.feed(chunk)
        except Exception:  # noqa: BLE001 - 渲染失败绝不应中断会话
            pass

    # -- 备用屏幕 ------------------------------------------------------
    def _split_alt_screen(self, text: str) -> list[str]:
        """按"进入/退出备用屏幕"把输入切开，并在切换点换屏。

        切换序列本身不喂给 pyte：换屏由我们自己做，给它只会留下无用的状态。

        PTY 的读取边界**可能把序列切开**（``ESC[?10`` 与 ``49h`` 分两次到达），
        所以把疑似未完成的尾巴留到下一次处理，而不是当成普通文本喂下去。
        """
        text = self._pending_alt + text
        self._pending_alt = ""

        out: list[str] = []
        index = 0
        for match in _ALT_SCREEN_RE.finditer(text):
            if match.start() > index:
                out.append(text[index:match.start()])
            if match.group(1) == "h":
                self._enter_alt_screen()
            else:
                self._leave_alt_screen()
            index = match.end()

        rest = text[index:]
        # 尾巴可能是半截序列：以 ESC 开头、且不含终止字母 h/l 的片段先留着。
        hold = _partial_alt_suffix(rest)
        if hold:
            self._pending_alt = rest[-hold:]
            rest = rest[:-hold]
        if rest:
            out.append(rest)
        return out

    def _new_screen(self) -> None:
        """换一块干净的网格与流（历史另行处理）。"""
        self._screen = pyte.HistoryScreen(self._columns, self._lines, history=self._history)
        self._stream = pyte.Stream(self._screen, strict=False)

    def _enter_alt_screen(self) -> None:
        """进入备用屏幕：存下主屏文本，再清空给 TUI 用。"""
        if self._in_alt_screen:
            return
        self._saved_lines = self._all_lines()
        self._saved_segments = list(self._segments)
        self._saved_prev_lines = list(self._prev_lines)
        self._in_alt_screen = True
        self._new_screen()
        # 备用屏是全新的一屏：基线要清空，否则增量会拿主屏行去比，
        # 把整块选择器内容都当成"新增"（丢失已有的差分语义）。
        self._prev_lines = []
        self._dirty = True

    def _leave_alt_screen(self) -> None:
        """退出备用屏幕：还原主屏，并把选择器期间的输出并入时间线。"""
        if not self._in_alt_screen:
            return
        alt_segments = list(self._segments)
        saved_lines = self._saved_lines
        saved_segments = self._saved_segments
        saved_prev_lines = self._saved_prev_lines

        self._in_alt_screen = False
        self._saved_lines = []
        self._saved_segments = []
        self._saved_prev_lines = []
        self._new_screen()
        self._replay(saved_lines)

        # 用户在选择器里做的事也有价值（"刚才在选哪个会话"），
        # 因此把那段也接进时间线，而不是直接丢掉。
        merged = list(saved_segments)
        for item in alt_segments:
            if not merged or merged[-1][1] != item[1]:
                merged.append(item)
        self._segments = merged[-self._max_segments:]
        # 主屏已经重画回网格，基线同步回进入前那一份，
        # 这样退出后的第一段增量只包含"退出之后真正新增的内容"。
        self._prev_lines = saved_prev_lines
        self._dirty = True

    def _replay(self, lines: list[str]) -> None:
        """把若干行文本重新画回网格（还原主屏用）。"""
        if not lines:
            return
        try:
            self._stream.feed("\x1b[2J\x1b[H")
            self._stream.feed("\r\n".join(lines))
        except Exception:  # noqa: BLE001 - 还原失败不影响后续输出
            pass

    @property
    def idle_seconds(self) -> float:
        """距离上一次收到输出的秒数；从未收到输出时为 0。"""
        if not self._last_activity:
            return 0.0
        return max(0.0, time.time() - self._last_activity)

    def mark_segment(self, *, force: bool = False) -> bool:
        """把**这一段新增的输出**记入时间线。

        由调用方在"输出停顿"或会话结束时触发；``force=True`` 用于会话收尾，
        确保最后一段状态一定被记录。没有新增内容则不记，避免刷屏。
        返回是否真的新增了一段。
        """
        if not self._dirty and not force:
            return False
        current = self._all_lines()
        self._dirty = False
        delta = self._delta_since(current)
        # 时间戳用"本段开始"的时刻；没有记录过就退回此刻（例如 force 收尾）。
        stamp = self._segment_started_at or time.time()
        self._segment_started_at = 0.0
        if not delta:
            return False
        self._segments.append((stamp, delta))
        if len(self._segments) > self._max_segments:
            self._segments = self._segments[-self._max_segments:]
        return True

    def _delta_since(self, current: list[str]) -> str:
        """算出相对上一次打点新增的行，并把基线推进到 ``current``。

        为什么不能直接用"整屏快照"：CLI 的 banner、工作目录等固定内容会一直
        留在屏幕上，每段都抄一遍就会得到"同一段文字重复 N 次"的时间线——
        实测三段输出里 ``OpenAI Codex`` 出现 3 次，完全没法看。

        实现用**最长公共前缀**而不是集合差：终端内容会向上滚动，用集合会比较
        会把"重复出现的相同行"（例如两次相同的报错）误判成没发生过。
        按行序找公共前缀能正确表达"屏幕从第 N 行之后都是新的"。
        """
        previous = self._prev_lines
        # 找到两者的最长公共前缀长度。
        common = 0
        limit = min(len(previous), len(current))
        while common < limit and previous[common] == current[common]:
            common += 1

        self._prev_lines = current
        fresh = current[common:]
        # 去掉纯空行，避免段落里满是空白。
        fresh = [line for line in fresh if line.strip()]
        if not fresh:
            return ""
        return "\n".join(fresh).strip()

    def timeline(self, max_segments: int = 200) -> str:
        """时间戳 + 段落内容，供界面渲染。"""
        return "\n".join(self.timeline_lines(max_segments))

    def timeline_lines(self, max_segments: int = 200) -> list[str]:
        """返回 ``[HH:MM:SS] 段落内容`` 形式的行列表。"""
        if not self._segments:
            return []
        segments = self._segments[-max_segments:] if max_segments > 0 else self._segments
        out: list[str] = []
        for timestamp, snapshot in segments:
            stamp = time.strftime("%H:%M:%S", time.localtime(timestamp))
            out.append(f"[{stamp}] " + snapshot.replace("\n", "\n         "))
        return out

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
        """滚动历史 + 当前屏幕，已去掉尾部空白行。"""
        return "\n".join(self._all_lines())

    @property
    def last_line(self) -> str:
        """最后一屏非空行，用于会话列表的一行预览。"""
        for row in reversed(self._visible_lines()):
            if row.strip():
                return row.strip()
        return ""

    def tail(self, lines: int = 400) -> str:
        rows = self._all_lines()
        if lines <= 0 or len(rows) <= lines:
            return "\n".join(rows)
        return "… 仅显示最后 " + str(lines) + " 行 …\n" + "\n".join(rows[-lines:])

    def clear(self) -> None:
        self._screen.reset()

    def _all_lines(self) -> list[str]:
        """滚动历史在前、当前视口在后，合成完整可读内容。"""
        rows: list[str] = []
        # history.top 是滚出屏幕顶部的行，按从旧到新排列。
        for row in self._screen.history.top:
            text = _row_text(row.values())
            rows.append(text)
        rows.extend(self._visible_lines())
        return rows

    def _visible_lines(self) -> list[str]:
        # display 每行定宽，右补空格；去掉行尾空白并丢弃完全空白的尾部行，
        # 避免界面上出现大片空白。
        rows = [line.rstrip() for line in self._screen.display]
        while rows and rows[-1] == "":
            rows.pop()
        return rows


def _row_text(row) -> str:
    """把 pyte 历史行（列号 → 字符单元）拼成文本。

    pyte 的历史行是稀疏映射，只存非空列，因此要按列号补空格。
    """
    if not row:
        return ""
    try:
        items = sorted(row.items())
    except AttributeError:
        # 少数版本给出的是可迭代的单元集合。
        return "".join(getattr(cell, "data", "") for cell in row).rstrip()
    parts: list[str] = []
    for column, cell in items:
        while len(parts) < column:
            parts.append(" ")
        parts.append(getattr(cell, "data", " "))
    return "".join(parts).rstrip()


__all__ = ["TerminalScreen"]

