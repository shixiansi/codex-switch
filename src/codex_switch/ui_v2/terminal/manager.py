"""AI 终端会话管理器（业务层，无 Qt 依赖）。

职责：
- 登记/启动/停止多个 PTY 会话；
- 后台线程周期性读取输出、检测退出、触发整树回收（零残留）；
- 把"完成/失败/可选项"事件通知给上层；
- cleanup_orphans() 回收本工具登记过但 root 已死、子树仍在的孤儿进程；
- **风险审查闸门**：自动应答不再无条件选第一项，而是先经 :class:`ReviewPolicy`
  判定（静默放行 / 通知 / 要求授权 / 拒绝），自主写入只允许从
  :meth:`TerminalManager._write_auto_answer` 这一个出口发出。
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from .completion import detect_menu
from .logging_setup import get_logger
from .pty_session import (
    PtySession,
    SessionStatus,
    _Backend,
    mark_finished,
    reap_tree,
    start_session,
)
from .review import Action, AnswerRequest, Decision, ReviewPolicy
from .screen import TerminalScreen

log = get_logger()

# 事件类型
EVENT_OUTPUT = "output"
EVENT_STATUS = "status"
EVENT_CHOICE = "choice"
# 时间线新增了一段（输出停顿后打点），用于让界面刷新时间线面板。
EVENT_TIMELINE = "timeline"
# 风险审查状态变化：需要通知 / 需要授权 / 授权已过期。
EVENT_REVIEW = "review"

# 审查状态（payload.state）
REVIEW_PENDING = "pending"
REVIEW_APPROVED = "approved"
REVIEW_DENIED = "denied"
REVIEW_EXPIRED = "expired"
REVIEW_DISMISSED = "dismissed"

# 特殊按键 → 终端字节序列。TUI 菜单多靠方向键移动、回车确认、Esc 取消，
# 而普通输入框只能发文本，因此需要单独提供这些控制键。
SPECIAL_KEYS: dict[str, str] = {
    "up": "\x1b[A",
    "down": "\x1b[B",
    "right": "\x1b[C",
    "left": "\x1b[D",
    "enter": "\r",
    "esc": "\x1b",
    "tab": "\t",
    "backspace": "\x7f",
    "ctrl-c": "\x03",
    # 粘贴。AI CLI 的图片输入走"系统剪贴板 + Ctrl+V"这条通道：
    # codex 与 claude 都在按 Ctrl+V 时自己去读剪贴板里的 PNG（实测 codex
    # 会随即在输入框显示 `[Image #1]`）。PTY 是纯文本流，传不了二进制，
    # 所以附加图片 = 写剪贴板 + 发这个键，由 CLI 自己取。
    "ctrl-v": "\x16",
}

# 文本与回车之间的写入间隔。
#
# 实测结论（对真实 codex 二进制扫描 0.05/0.2/0.5/1.0s）：0.05s 无法提交，0.2s 起稳定提交。
# 原因是 codex 开启了 bracketed paste（ESC[?2004h）：同一次读取里到达的"文本+回车"
# 会被当成**粘贴**，回车被吞进粘贴内容里，于是屏幕上能看到消息、AI 却完全不开始工作。
# 分开写入并留出间隔，可确保回车被当作独立的按键处理。取 0.25s 留出余量。
_ENTER_DELAY_S = 0.25

# 自动应答的重试策略：菜单刚出现时 TUI 可能还没开始读输入，单次发送会被丢弃，
# 因此按间隔重试若干次，直到菜单消失。
_AUTO_ANSWER_RETRY_S = 1.5
_AUTO_ANSWER_MAX_ATTEMPTS = 6
# 菜单持续消失多久才认为"真的结束了"，用于避免重绘闪烁导致重复应答。
_MENU_GONE_RESET_S = 2.0

EventHook = Callable[[str, str, dict[str, Any]], None]


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


@dataclass
class SessionSummary:
    """传给 UI 的会话快照（纯数据，可 JSON 化）。"""

    session_id: str
    title: str
    command: str
    cwd: str
    status: str
    exit_code: int | None = None
    started_at: str = ""
    finished_at: str = ""
    awaiting_choice: bool = False
    choices: list[str] = field(default_factory=list)
    # 菜单当前高亮项下标（-1 表示看不出）；以及菜单种类。
    selected_index: int = -1
    kind: str = "numbered"
    last_line: str = ""
    # 运行时长（毫秒）：运行中为"至今"，结束后为总时长。由 manager 计算，
    # 避免 QML 侧做时间运算。
    elapsed_ms: int = 0
    # 当前选项是否已由自动应答处理过。
    auto_answered: bool = False
    # 风险审查：是否存在等待用户授权的菜单，以及本会话的审查计数。
    review_pending: bool = False
    review_pending_count: int = 0
    reviewed_count: int = 0
    denied_count: int = 0
    # 当前待审项的风险等级与拟发送内容，供界面展示。
    review_risk: str = ""
    review_label: str = ""
    review_mode: str = ""
    review_mode_label: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "sessionId": self.session_id,
            "title": self.title,
            "command": self.command,
            "cwd": self.cwd,
            "status": self.status,
            "statusLabel": _STATUS_LABELS.get(self.status, self.status),
            "exitCode": self.exit_code,
            "startedAt": self.started_at,
            "finishedAt": self.finished_at,
            "awaitingChoice": self.awaiting_choice,
            "choices": list(self.choices),
            "selectedIndex": self.selected_index,
            "kind": self.kind,
            "lastLine": self.last_line,
            "elapsedMs": self.elapsed_ms,
            "elapsedLabel": _format_elapsed(self.elapsed_ms),
            "autoAnswered": self.auto_answered,
            "reviewPending": self.review_pending,
            "reviewPendingCount": self.review_pending_count,
            "reviewedCount": self.reviewed_count,
            "deniedCount": self.denied_count,
            "reviewRisk": self.review_risk,
            "reviewLabel": self.review_label,
            "reviewMode": self.review_mode,
            "reviewModeLabel": self.review_mode_label,
        }


def _elapsed_ms(session: PtySession) -> int:
    """会话运行时长（毫秒）：运行中算到此刻，结束后用结束时间。"""
    if not session.started_at_ms:
        return 0
    end = session.finished_at_ms or (time.time() * 1000.0)
    return max(0, int(end - session.started_at_ms))


def _auto_choice_index(choices: list[str]) -> int:
    """自动应答时选哪一项。

    默认第一项：codex/claude 的确认菜单首项通常是"继续/默认"语义
    （如 ``Yes, continue``），最符合"自动放行"的预期。

    **注意**：选哪一项已不再是安全边界。风险是否可接受由
    :mod:`review` 的规则链判定，本函数只负责"点哪里"。
    """
    return 0


@dataclass
class PendingReview:
    """一项等待用户授权的自动应答。

    保存请求的完整快照与菜单签名：用户批准时要用签名复核"菜单还是原来那个吗"，
    否则用户看到的与将要按下的可能已经不是同一件事。
    """

    request: AnswerRequest
    decision: Decision
    created_at: float
    session_id: str
    title: str

    @property
    def deadline(self) -> float:
        return self.created_at + self.timeout_seconds

    # 由 manager 在建立待审项时写入。
    timeout_seconds: float = 60.0

    def label(self) -> str:
        """拟发送内容的可读描述，用于界面展示"要替你按哪个键"。"""
        request = self.request
        if request.kind == "confirm":
            return "是（" + (request.intended_payload or "y") + "）"
        if request.intended_label:
            return f"{request.intended_index + 1}. {request.intended_label}"
        return str(request.intended_payload or "")

    def to_dict(self) -> dict[str, Any]:
        return {
            "sessionId": self.session_id,
            "title": self.title,
            "kind": self.request.kind,
            "label": self.label(),
            "payload": self.request.intended_payload,
            "prompt": self.request.prompt,
            "reason": self.decision.reason,
            "ruleId": self.decision.rule_id,
            "risk": self.decision.risk.value,
            "riskLabel": self.decision.risk.label,
            "createdAt": self.created_at,
            "timeoutSeconds": self.timeout_seconds,
            "choices": list(self.request.choices),
            "index": self.request.intended_index,
        }


def _format_elapsed(milliseconds: int) -> str:
    """把毫秒格式化成 ``1h02m03s`` / ``02m03s`` / ``03s`` 形式。"""
    total = max(0, int(milliseconds // 1000))
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}h{minutes:02d}m{seconds:02d}s"
    if minutes:
        return f"{minutes:02d}m{seconds:02d}s"
    return f"{seconds}s"


_STATUS_LABELS = {
    SessionStatus.STARTING.value: "启动中",
    SessionStatus.RUNNING.value: "运行中",
    SessionStatus.COMPLETED.value: "已完成",
    SessionStatus.FAILED.value: "失败",
    SessionStatus.STOPPED.value: "已停止",
}


class TerminalManager:
    """会话登记表 + 轮询线程。"""

    def __init__(
        self,
        poll_interval: float = 0.25,
        on_event: EventHook | None = None,
        policy: ReviewPolicy | None = None,
    ) -> None:
        self._sessions: dict[str, PtySession] = {}
        self._backends: dict[str, _Backend] = {}
        self._screens: dict[str, TerminalScreen] = {}
        self._poll_interval = poll_interval
        self._on_event = on_event
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        # 待发送的动作队列，由独立写入线程按顺序处理。
        # 元素是 ("line", 文本) 或 ("key", 按键名)——按键必须与文本行走同一条
        # 队列，否则"先发数字再发方向键"这类顺序会被打乱。
        # 放在队列里而不是在调用方 sleep，是为了不阻塞 GUI 线程。
        self._pending: list[tuple[str, str, str]] = []
        self._pending_lock = threading.Lock()
        self._pending_event = threading.Event()
        self._writer: threading.Thread | None = None
        # 自动应答：检测到选择菜单时自动按预设策略回答，无需人工点击。
        # 默认关闭，由界面上的开关控制。
        self.auto_answer = False
        # 风险审查策略。manager 不读文件：策略由上层从 terminal_policy.json
        # 读好后注入（依赖倒置），这样 terminal/ 包继续保持无全局状态。
        self._policy = policy or ReviewPolicy()
        # 等待用户授权的自动应答，按会话 id 索引。
        self._reviews: dict[str, PendingReview] = {}
        # 输出停顿多久算"一段结束"，用于给时间线打点。
        self._segment_idle_seconds = 1.2

    # -- 生命周期 ------------------------------------------------------
    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="terminal-poll")
        self._thread.start()
        self._writer = threading.Thread(target=self._write_loop, daemon=True, name="terminal-writer")
        self._writer.start()
        log.info("轮询线程已启动 interval=%ss", self._poll_interval)

    def _write_loop(self) -> None:
        """按序处理待发送的动作：文本行补回车，按键序列逐个发。

        停顿必须发生在这里（后台线程），不能在 UI 线程 sleep，否则界面会卡住。
        队列里存的是 ``("line", 文本)`` 或 ``("key", 按键名)``：
        按键之间的间隔同样重要，TUI 会把连续写入合并成一次读取，导致只移动一格。
        """
        while not self._stop.is_set():
            if not self._pending_event.wait(0.1):
                continue
            while True:
                with self._pending_lock:
                    if not self._pending:
                        self._pending_event.clear()
                        break
                    session_id, kind, payload = self._pending.pop(0)
                backend = self._backends.get(session_id)
                if backend is None:
                    continue
                try:
                    if kind == "key":
                        sequence = SPECIAL_KEYS.get(payload)
                        if sequence is None:
                            continue
                        backend.write(sequence)
                        time.sleep(_ENTER_DELAY_S)
                    else:
                        backend.write(payload)
                        time.sleep(_ENTER_DELAY_S)
                        backend.write("\r")
                except Exception:  # noqa: BLE001 - 写入失败不应终止写入线程
                    log.exception("发送失败 id=%s kind=%s", session_id, kind)

    def shutdown(self) -> None:
        """停止全部会话（整树回收）并结束轮询线程。"""
        self._stop.set()
        with self._lock:
            ids = list(self._sessions.keys())
        for sid in ids:
            self.stop_session(sid, reap=True)
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        if self._writer is not None:
            self._writer.join(timeout=2.0)
            self._writer = None
        with self._pending_lock:
            self._pending.clear()
        self._pending_event.clear()

    # -- 会话操作 ------------------------------------------------------
    def create_session(
        self,
        title: str,
        command: str,
        cwd: str,
        env: dict[str, str] | None = None,
        *,
        backend_factory: Callable[[str, str, dict[str, str]], _Backend] | None = None,
    ) -> str:
        """新建并启动一个会话，返回 session_id。"""
        session_id = uuid.uuid4().hex[:12]
        session = PtySession(
            session_id=session_id,
            title=title or command,
            command=command,
            cwd=cwd,
            env=dict(env or {}),
            started_at=_now(),
            started_at_ms=time.time() * 1000.0,
        )
        log.info("启动会话 id=%s title=%r", session_id, session.title)
        log.info("  命令: %s", command)
        log.info("  目录: %s", cwd or "(默认)")
        if env:
            log.info("  环境变量: %s", ", ".join(sorted(env)))
        with self._lock:
            self._sessions[session_id] = session
            self._screens[session_id] = TerminalScreen()
        try:
            backend = start_session(session, backend_factory=backend_factory)
        except Exception as exc:  # noqa: BLE001 - 记录下来再抛出，避免"悄无声息"
            log.exception("启动会话失败 id=%s: %s", session_id, exc)
            with self._lock:
                self._sessions.pop(session_id, None)
                self._screens.pop(session_id, None)
            raise
        with self._lock:
            self._backends[session_id] = backend
        log.info("会话已启动 id=%s pid=%s", session_id, session.root_pid)
        self._emit(session_id, EVENT_STATUS, {"status": session.status.value})
        return session_id

    def stop_session(self, session_id: str, *, reap: bool = True) -> None:
        backend = self._backends.get(session_id)
        session = self._sessions.get(session_id)
        if backend is not None:
            try:
                backend.kill()
            except Exception:  # noqa: BLE001
                pass
        if session is not None and reap:
            reap_tree(session)
        if session is not None and not session.status.is_terminal:
            mark_finished(session, None)
            self._emit(session_id, EVENT_STATUS, {"status": session.status.value})

    def send_input(self, session_id: str, data: str) -> None:
        """把一行输入交给写入线程提交（非阻塞，不卡界面）。

        提交一行的两个要点（均对真实 codex 实测确认）：
        1) 结束符是单个 CR（0x0D），即真实终端按下 Enter 发出的字节。发 CRLF 会被
           原始模式 TUI 当成两次回车，第二条空消息会顶掉刚输入的请求。
        2) 文本与 CR 必须分成两次写入且留出间隔。codex 开启了 bracketed paste
           （ESC[?2004h），同一次到达的"文本+回车"会被当作粘贴，回车被吞掉，
           于是消息显示出来了但 AI 完全不开始工作。
        """
        if session_id not in self._backends:
            return
        text = str(data or "")
        # 多行输入统一为 CR，避免裸 \n 被当作额外回车提前提交。
        text = text.replace("\r\n", "\r").replace("\n", "\r")
        if not text:
            return
        self._queue_input(session_id, text)
        # 用户输入后，CLI 通常会清掉提示；乐观地关闭"等待选择"态。
        session = self._sessions.get(session_id)
        if session is not None and session.awaiting_choice:
            session.awaiting_choice = False
            session.choices = []
            self._emit(session_id, EVENT_CHOICE, {"awaitingChoice": False, "choices": []})

    def _queue_input(self, session_id: str, text: str) -> None:
        """把一行文本排入写入队列（由写入线程补发回车）。"""
        if not text:
            return
        with self._pending_lock:
            self._pending.append((session_id, "line", text))
        self._pending_event.set()

    def _queue_keys(self, session_id: str, keys: list[str]) -> None:
        """把一串按键排入写入队列，由写入线程逐个、带间隔地发出。

        与 :meth:`send_key`（立即写单个键）不同：这里用于"移动若干格再确认"
        这类多步操作，必须保证顺序与间隔，且不能阻塞调用方。
        """
        usable = [key for key in keys if key in SPECIAL_KEYS]
        if not usable:
            return
        with self._pending_lock:
            self._pending.extend((session_id, "key", key) for key in usable)
        self._pending_event.set()

    def send_key(self, session_id: str, key: str) -> bool:
        """发送一个特殊按键（方向键 / Enter / Esc / Tab / Ctrl-C / Ctrl-V）。

        与 send_input 不同，控制键要**立即单次写入**：它们本身就是终端的按键序列，
        没有"文本 + 回车被当成粘贴"的问题。返回是否识别并发送了该键。
        用于在 TUI 菜单里上下移动、确认或取消。
        """
        sequence = SPECIAL_KEYS.get(str(key or "").lower())
        if sequence is None:
            return False
        backend = self._backends.get(session_id)
        if backend is None:
            return False
        try:
            backend.write(sequence)
        except Exception:  # noqa: BLE001 - 发送失败不应影响上层
            log.exception("发送按键失败 id=%s key=%s", session_id, key)
            return False
        return True

    def paste_clipboard_image(self, session_id: str) -> bool:
        """让 CLI 从系统剪贴板粘贴一张图片。

        这是 AI CLI 收图的**唯一**通道：它们按 Ctrl+V 时自己去读操作系统
        剪贴板（codex 会随即在输入框显示 ``[Image #1]``）。因此"附加图片"
        分两步——先把图片放进剪贴板，再发 Ctrl+V。

        **本方法不碰剪贴板**（那是 Qt 的事，见 viewmodels/terminal.py），
        只负责发键。这样业务层继续保持无 Qt 依赖，剪贴板的读写集中在一处。

        刻意**不自动回车**：附加图片只是把附件放进输入框，发不发由用户决定。
        """
        return self.send_key(session_id, "ctrl-v")

    def select_choice(self, session_id: str, index: int) -> bool:
        """选中菜单里的第 ``index`` 项（0 起）。

        分两种情况：

        * **编号菜单**：直接发编号（1 起）。TUI 的编号菜单普遍接受数字直选。
        * **无编号菜单**（如 codex 的 resume 列表）：不能发数字——那会被当成
          搜索关键词，菜单内容会被过滤掉。必须用方向键把光标从当前高亮项
          移到目标项，再按回车。若屏幕上看不出当前高亮位置，则先发一串 ↑
          回到首项，再从首项往下走，保证结果确定。

        所有按键排进写入队列，由后台线程带间隔逐个发出。方向键之间必须留间隔，
        但**绝不能在本方法里 sleep**：本方法由界面线程调用，阻塞几秒会让整个
        窗口卡死。

        Returns:
            是否成功排入队列。
        """
        session = self._sessions.get(session_id)
        if session is None or not session.choices:
            return False
        if not (0 <= index < len(session.choices)):
            return False
        if session_id not in self._backends:
            return False

        if session.choice_kind == "confirm":
            # 确认提示要发 y / n 这两个字符，不是数字也不是方向键。
            self._queue_input(session_id, "y" if index == 0 else "n")
            return True

        if session.choice_kind == "numbered":
            self._queue_input(session_id, str(index + 1))
            return True

        # 无编号列表菜单：用方向键移动。
        current = session.choice_selected
        keys: list[str] = []
        if current < 0:
            # 看不出高亮位置：先回到顶部再往下，避免"少按/多按"。
            keys.extend(["up"] * len(session.choices))
            current = 0
        if index > current:
            keys.extend(["down"] * (index - current))
        elif index < current:
            keys.extend(["up"] * (current - index))
        keys.append("enter")

        self._queue_keys(session_id, keys)
        # 乐观更新本地高亮位置，避免下一次点击基于过期状态计算移动量。
        session.choice_selected = index
        return True

    def remove_session(self, session_id: str) -> None:
        """从登记表移除（进程若仍在则先回收）。"""
        # 先丢弃待审项：会话马上就不存在了，再弹出它的授权框只会让用户困惑。
        self.dismiss_review(session_id, "会话已移除")
        self.stop_session(session_id, reap=True)
        with self._lock:
            self._sessions.pop(session_id, None)
            self._backends.pop(session_id, None)
            self._screens.pop(session_id, None)

    # -- 查询 ----------------------------------------------------------
    def summaries(self) -> list[SessionSummary]:
        with self._lock:
            sessions = list(self._sessions.values())
            reviews = dict(self._reviews)
        out: list[SessionSummary] = []
        for s in sessions:
            screen = self._screens.get(s.session_id)
            last = screen.last_line if screen is not None else ""
            pending = reviews.get(s.session_id)
            out.append(
                SessionSummary(
                    session_id=s.session_id,
                    title=s.title,
                    command=s.command,
                    cwd=s.cwd,
                    status=s.status.value,
                    exit_code=s.exit_code,
                    started_at=s.started_at,
                    finished_at=s.finished_at,
                    awaiting_choice=s.awaiting_choice,
                    choices=list(s.choices),
                    selected_index=s.choice_selected,
                    kind=s.choice_kind,
                    last_line=last,
                    elapsed_ms=_elapsed_ms(s),
                    auto_answered=bool(s.choices) and tuple(s.choices) == s.auto_answered,
                    review_pending=pending is not None,
                    review_pending_count=1 if pending is not None else 0,
                    reviewed_count=s.reviewed_count,
                    denied_count=s.denied_count,
                    review_risk=pending.decision.risk.value if pending is not None else "",
                    review_label=pending.label() if pending is not None else "",
                    review_mode=self._policy.mode,
                    review_mode_label=self._policy.mode_label,
                )
            )
        return out

    def timeline_text(self, session_id: str, max_segments: int = 200) -> str:
        """带时间戳的输出时间线。"""
        screen = self._screens.get(session_id)
        return screen.timeline(max_segments) if screen is not None else ""

    def screen_text(self, session_id: str) -> str:
        screen = self._screens.get(session_id)
        return screen.tail() if screen is not None else ""

    def session(self, session_id: str) -> PtySession | None:
        """按 id 取会话对象；不存在返回 None。

        调用方需要会话的工作目录（例如按项目读历史）时用它，
        避免直接摸内部字典。
        """
        return self._sessions.get(str(session_id or ""))

    def running_count(self) -> int:
        with self._lock:
            return sum(1 for s in self._sessions.values() if s.status == SessionStatus.RUNNING)

    # -- 孤儿清理 ------------------------------------------------------
    def cleanup_orphans(self) -> list[dict[str, Any]]:
        """回收"本工具登记过、root 已死但子树仍在"的会话整树。

        返回被清理的会话摘要（用于 UI 报告）。历史遗留的完全无记录的孤儿
        由 psutil 的进程树探测覆盖，但本工具只负责自家登记的会话，避免误杀。
        """
        cleaned: list[dict[str, Any]] = []
        with self._lock:
            sessions = list(self._sessions.values())
        for s in sessions:
            # 仅处理"已结束但曾登记进程树"的会话；其子孙若仍存活即残留。
            if not s.status.is_terminal:
                continue
            reap_tree(s)
            if s.child_pids:
                cleaned.append(
                    {"sessionId": s.session_id, "title": s.title, "children": len(s.child_pids)}
                )
        return cleaned

    # -- 轮询 ----------------------------------------------------------
    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._poll_once()
            except Exception:  # noqa: BLE001
                # 轮询线程一旦因异常退出，界面就再也不会更新（表现为"发消息后
                # 界面不动了"）。这里吞掉单次异常并继续，保证长时间运行稳定。
                log.exception("轮询单次失败，已跳过本轮继续运行")
            self._stop.wait(self._poll_interval)

    def _poll_once(self) -> None:
        with self._lock:
            items = list(self._sessions.items())
        for session_id, session in items:
            backend = self._backends.get(session_id)
            screen = self._screens.get(session_id)
            if backend is None or screen is None:
                continue
            # 读取输出增量（非阻塞：没有数据立即返回）。
            data = backend.read()
            alive = backend.is_alive()
            # 进程已退出时把管道里剩余的输出读干净，否则最后的日志会丢失。
            if not alive:
                while True:
                    tail = backend.read()
                    if not tail:
                        break
                    data += tail
            if data:
                if not session.received_output:
                    # 首个字节到达：用于区分"CLI 根本没输出"和"读取坏了"。
                    session.received_output = True
                    log.info("会话首次收到输出 id=%s 字节=%s", session_id, len(data))
                screen.feed(data)
                # 只渲染一次文本：tail()/text 在长历史下都是 O(行数)，
                # 每轮调用两次会让 4Hz 轮询随历史增长而变慢。
                rendered = screen.tail()
                self._emit(session_id, EVENT_OUTPUT, {"text": rendered})
                menu = detect_menu(rendered)
                state = (
                    menu.awaiting,
                    menu.choices,
                    menu.selected,
                    menu.kind,
                    menu.prompt,
                )
                previous = (
                    session.awaiting_choice,
                    session.choices,
                    session.choice_selected,
                    session.choice_kind,
                    session.choice_prompt,
                )
                if state != previous:
                    session.awaiting_choice = menu.awaiting
                    session.choices = list(menu.choices)
                    session.choice_selected = menu.selected
                    session.choice_kind = menu.kind
                    session.choice_prompt = menu.prompt
                    self._emit(
                        session_id,
                        EVENT_CHOICE,
                        {
                            "awaitingChoice": menu.awaiting,
                            "choices": list(menu.choices),
                            "selectedIndex": menu.selected,
                            "kind": menu.kind,
                            "prompt": menu.prompt,
                        },
                    )
            # 输出停顿一段时间后，把这一屏记入带时间戳的时间线。
            # 必须每轮都检查：停顿意味着"本轮没有数据"，若只在收到数据时才判断，
            # idle_seconds 永远是 0，时间线会一直是空的。
            if session.received_output and screen.idle_seconds >= self._segment_idle_seconds:
                if screen.mark_segment():
                    self._emit(
                        session_id,
                        EVENT_TIMELINE,
                        {"text": screen.timeline(), "segments": len(screen.timeline_lines())},
                    )
            # 自动应答：检测到菜单且用户开启了自动处理时，交由风险审查决定。
            if session.awaiting_choice and session.choices:
                session.menu_absent_since = 0.0
                self._maybe_auto_answer(session)
            elif session.auto_answered:
                # 菜单消失后延迟清空状态：TUI 重绘时菜单可能短暂"消失"一两帧，
                # 立刻清空会导致同一菜单被重复应答（多发一次键 = 误操作）。
                # 因此要求菜单持续消失一段时间，才认为是真的结束了。
                if not session.menu_absent_since:
                    session.menu_absent_since = time.monotonic()
                elif time.monotonic() - session.menu_absent_since >= _MENU_GONE_RESET_S:
                    session.auto_answered = ()
                    session.auto_answer_attempts = 0
                    session.auto_answer_last_at = 0.0
                    session.menu_absent_since = 0.0
                    session.declined_menus.clear()
                    session.answered_menus.clear()
                    # approved_kinds 刻意**不**清空：用户的"这类不用再问"应当
                    # 在整个会话内有效，而不是菜单一消失就作废。
                    # 菜单确实结束了，悬着的授权框也就没有意义了。
                    self.dismiss_review(session_id, "菜单已关闭")
            # 检测退出
            if not alive and not session.status.is_terminal:
                self._finish(session_id, session, backend)

        # 授权超时检查必须**每轮**都做，不能塞进上面的 `if data:` 分支：
        # CLI 静默时没有输出，待审项会永远不过期，授权框就一直悬着。
        self._expire_reviews()

    def _maybe_auto_answer(self, session: PtySession) -> None:
        """按策略自动回应选择菜单（**唯一**的自动应答决策入口）。

        与旧实现的区别：不再"检测到菜单就选第一项"，而是先把请求交给
        :class:`ReviewPolicy`，由它决定静默放行、通知、还是要求授权。
        真正的写入只允许从 :meth:`_write_auto_answer` 发出。

        关键：菜单出现到 CLI 真正开始读标准输入之间有短暂间隙（TUI 还在重绘），
        此时写入的应答可能被丢弃。因此这里**持续重试**，直到菜单消失或达到
        次数上限——只试一次会出现"日志显示已自动应答、菜单却还在"的情况。
        """
        if not self._session_auto_answer(session):
            return
        # 已有一个待授权的菜单：**绝不重试**。用户还没看清就把键刷出去，
        # 等于绕过了审查本身。
        if session.session_id in self._reviews:
            return
        if not session.choices:
            return

        signature = tuple(session.choices)
        threshold = self._policy.config.review_timeout_seconds
        if signature != session.auto_answered:
            # 换了一个菜单：重置尝试计数。
            session.auto_answered = signature
            session.auto_answer_attempts = 0
        now = time.monotonic()
        if session.auto_answer_attempts >= _AUTO_ANSWER_MAX_ATTEMPTS:
            return
        # 每次尝试之间留出冷却时间，避免把按键刷爆。
        if now - session.auto_answer_last_at < _AUTO_ANSWER_RETRY_S:
            return

        # 这一屏已经处理过了（自动应答过，或用户刚授权/拒绝过）。
        #
        # 必要性：按键要经写入队列延迟约 0.25s 才真正发出，而轮询间隔也是
        # 0.25s。没有这个标记时，菜单在屏幕上多停留一拍就会被**再问一次**，
        # 用户会看到同一个菜单连续弹两遍。菜单消失后标记会被清空。
        if signature in session.answered_menus or signature in session.declined_menus:
            return

        # 用户点过"本会话允许此类"：同种类的菜单不再询问，直接按策略执行。
        # 注意"这类"是按菜单**种类**（confirm / numbered）判定的，与按钮字面一致；
        # 列表菜单永远排除在外。
        skip_ask = session.choice_kind in session.approved_kinds and session.choice_kind != "list"
        request = self._build_request(session, now)
        decision = self._policy.evaluate(request, skip_ask=skip_ask)
        self._record_review(session, request, decision)

        if decision.action is Action.BLOCK:
            # 不发任何按键。关闭模式、列表菜单、预算耗尽、已拒绝都从这里返回。
            if decision.rule_id == "list_menu":
                # 记下来，避免同一屏列表菜单每轮都被重新判定一次。
                session.answered_menus.add(signature)
            return

        if decision.action is Action.ASK:
            pending = PendingReview(
                request=request,
                decision=decision,
                created_at=now,
                session_id=session.session_id,
                title=session.title,
                timeout_seconds=threshold,
            )
            self._reviews[session.session_id] = pending
            # 标记"这一屏已经问过了"：应答要经写入队列延迟约 0.25s 才发出，
            # 而轮询间隔也是 0.25s；不标记的话菜单多停一拍就会再弹一次。
            session.answered_menus.add(signature)
            # 菜单刚出现时 TUI 可能还没开始读输入，挂起前的那次尝试就是"白打"。
            # 这里同步一次时间戳，让用户授权后立即发送，不必再等一个冷却周期。
            session.auto_answer_last_at = now
            log.info(
                "自动应答已挂起待授权 id=%s 规则=%s 风险=%s 拟发送=%r 提示=%r",
                session.session_id,
                decision.rule_id,
                decision.risk.value,
                request.intended_payload,
                request.prompt[:80],
            )
            self._emit(
                session.session_id,
                EVENT_REVIEW,
                {
                    "state": REVIEW_PENDING,
                    "review": pending.to_dict(),
                    "mode": self._policy.mode,
                    "modeLabel": self._policy.mode_label,
                },
            )
            return

        # SILENT / NOTIFY 才真正按键。通知由界面层负责（manager 不碰 Qt）。
        session.auto_answer_attempts += 1
        session.auto_answer_last_at = now
        session.auto_write_times.append(now)
        # 记下"这一屏已答过"，避免菜单尚未从屏幕消失时被重复处理。
        session.answered_menus.add(signature)
        if decision.action is Action.NOTIFY:
            self._emit(
                session.session_id,
                EVENT_REVIEW,
                {
                    "state": "notice",
                    "review": {
                        "sessionId": session.session_id,
                        "title": session.title,
                        "label": request.intended_label,
                        "payload": request.intended_payload,
                        "prompt": request.prompt,
                        "reason": decision.reason,
                        "ruleId": decision.rule_id,
                        "risk": decision.risk.value,
                        "riskLabel": decision.risk.label,
                    },
                    "mode": self._policy.mode,
                    "modeLabel": self._policy.mode_label,
                },
            )
        self._write_auto_answer(session, request, decision)

    def _session_auto_answer(self, session: PtySession) -> bool:
        """这个会话当前是否允许自动应答。

        调用方（界面层）的设置优先：即使策略里写着 balanced，只要用户把开关
        关掉了就必须尊重。两者是独立的所有权层级，取交集最不容易出意外。
        """
        enabled = bool(self.auto_answer)
        session_flag = getattr(session, "auto_answer_enabled", None)
        if session_flag is not None:
            enabled = enabled and bool(session_flag)
        return enabled

    def _build_request(self, session: PtySession, now: float) -> AnswerRequest:
        """组装一次审查请求（纯数据，供策略层判定）。"""
        index = _auto_choice_index(session.choices)
        kind = session.choice_kind
        if kind == "confirm":
            payload = "y" if index == 0 else "n"
            # confirm 的选项文本是本工具自造的"是/否"，没有信息量；
            # 风险判定要靠 CLI 的提示原文。
            label = ""
            prompt = str(getattr(session, "choice_prompt", "") or "")
        else:
            payload = str(index + 1)
            label = session.choices[index] if 0 <= index < len(session.choices) else ""
            prompt = ""
        return AnswerRequest(
            session_id=session.session_id,
            kind=kind,
            choices=tuple(session.choices),
            intended_index=index,
            intended_payload=payload,
            intended_label=label,
            prompt=prompt,
            title=session.title,
            cwd=session.cwd,
            command=session.command,
            screen_tail=self.screen_text(session.session_id),
            attempt=session.auto_answer_attempts + 1,
            declined=tuple(session.choices) in session.declined_menus,
            asked=tuple(session.choices) in session.answered_menus,
            budget_exhausted=self._budget_exhausted(session, now),
        )

    def _budget_exhausted(self, session: PtySession, now: float) -> bool:
        """自主写入是否已超出预算（限流，防止菜单刷屏时无限按键）。"""
        window = self._policy.config.budget_window_seconds
        horizon = now - window
        session.auto_write_times = [item for item in session.auto_write_times if item > horizon]
        return len(session.auto_write_times) >= self._policy.config.budget_max_writes

    def _write_auto_answer(
        self,
        session: PtySession,
        request: AnswerRequest,
        decision: Decision,
    ) -> None:
        """**唯一**允许自主按键的出口。

        所有"替用户按键"的路径都必须经过这里：策略放行与用户授权都汇聚到此，
        便于统一记日志与统计，也避免将来新增规则时绕开审查。

        这里再做一次开关判断：本模块的调用路径不止自动应答（例如用户授权之后
        可能又把自动应答关掉），把闸门放在出口最不容易漏。
        """
        if not self._session_auto_answer(session):
            log.info("自动应答已被关闭，取消发送 id=%s", session.session_id)
            return
        log.info(
            "自动应答 id=%s 动作=%s 规则=%s 风险=%s 发送=%r 选项=%s",
            session.session_id,
            decision.action.value,
            decision.rule_id,
            decision.risk.value,
            request.intended_payload,
            [item.strip()[:24] for item in session.choices],
        )
        # 重试发送同一个应答：只有"菜单仍被检测到"时才会走到这里，
        # 因此不会在菜单已关闭后误把内容打进输入框。
        self._queue_input(session.session_id, request.intended_payload)

    def _record_review(self, session: PtySession, request: AnswerRequest, decision: Decision) -> None:
        """统一记录审查结论，供排查"它到底为什么按键/没按键"。"""
        log.info(
            "[review] id=%s 菜单=%s 拟发送=%r 风险=%s 动作=%s 规则=%s 理由=%s",
            session.session_id,
            request.kind,
            request.intended_payload,
            decision.risk.value,
            decision.action.value,
            decision.rule_id,
            decision.reason,
        )

    # -- 授权（人工出口）-----------------------------------------------
    def pending_reviews(self) -> list[dict[str, Any]]:
        with self._lock:
            return [item.to_dict() for item in self._reviews.values()]

    def pending_review(self, session_id: str) -> dict[str, Any]:
        with self._lock:
            item = self._reviews.get(str(session_id or ""))
            return item.to_dict() if item is not None else {}

    def has_pending_review(self, session_id: str) -> bool:
        with self._lock:
            return str(session_id or "") in self._reviews

    def resolve_review(
        self,
        session_id: str,
        approve: bool,
        *,
        allow_kind: bool = False,
    ) -> bool:
        """处理一次授权请求（界面线程调用，绝不阻塞）。

        返回是否真的发出了按键——菜单在等待期间变了就返回 False，**绝不补发**
        （用户批准的是他看到的那一屏，屏幕变了就不该再按）。

        ``allow_kind=True`` 表示"本会话允许此类"，只影响本会话内存态，不落盘：
        永久白名单等于换个地方开后门。
        """
        target = str(session_id or "")
        with self._lock:
            pending = self._reviews.pop(target, None)
        if pending is None:
            return False

        session = self._sessions.get(target)
        if session is None:
            log.info("[review] id=%s 会话已不存在，授权作废", target)
            return False

        request = pending.request
        # 无论批准还是拒绝，这一屏都已经有结论了，别再问第二遍。
        session.answered_menus.add(request.signature)
        if not approve:
            session.declined_menus.add(request.signature)
            session.denied_count += 1
            log.info("[review] id=%s 用户拒绝，本会话不再提示该菜单", target)
            self._emit(
                target,
                EVENT_REVIEW,
                {"state": REVIEW_DENIED, "review": pending.to_dict(), "ruleId": request.kind},
            )
            return False

        # 复核签名：用户看到的那一屏与现在这一屏必须是同一个菜单。
        current = tuple(session.choices)
        if current != request.signature:
            log.info(
                "[review] id=%s 菜单已变化（批准时 %s，现在 %s），授权作废",
                target,
                list(request.signature)[:3],
                list(current)[:3],
            )
            self._emit(
                target,
                EVENT_REVIEW,
                {"state": REVIEW_EXPIRED, "review": pending.to_dict(), "reason": "菜单已变化"},
            )
            return False

        session.reviewed_count += 1
        if allow_kind:
            # 记住"这类菜单"已获授权。按**种类**（confirm / numbered）而
            # 不是按签名记录，因为按钮的字面承诺就是"此类"；只存在内存里，
            # 会话结束即失效（永久白名单等于换个地方开后门）。
            session.approved_kinds.add(request.kind)
            log.info("[review] id=%s 用户允许此类（本会话）：%s", target, request.kind)
        self._emit(
            target,
            EVENT_REVIEW,
            {"state": REVIEW_APPROVED, "review": pending.to_dict()},
        )
        # 人工放行不计入预算：那不是自动化，没理由被限流。
        self._write_auto_answer(session, request, pending.decision)
        return True

    # -- 策略 ----------------------------------------------------------
    def set_policy(self, policy: ReviewPolicy) -> None:
        """热更新审查策略（界面切换模式时调用）。"""
        self._policy = policy
        log.info("审查策略已更新：模式=%s", policy.mode)

    @property
    def policy(self) -> ReviewPolicy:
        return self._policy

    # -- 授权超时 ------------------------------------------------------
    def _expire_reviews(self, now: float | None = None) -> None:
        """清理超时的待授权项。

        **超时一律按拒绝处理，绝不超时放行**：无人值守时"悄悄放行"正是审查
        要防的那件事；需要完全放手就该显式切到"完全放行"模式。

        必须每轮轮询都调用，而不是只在收到输出时调用——CLI 静默时没有输出，
        待审项会永远不过期，界面上的授权框一直悬着。
        """
        if not self._reviews:
            return
        moment = time.monotonic() if now is None else now
        expired: list[PendingReview] = []
        with self._lock:
            for session_id, item in list(self._reviews.items()):
                if moment >= item.deadline:
                    expired.append(item)
                    del self._reviews[session_id]
        for item in expired:
            session = self._sessions.get(item.session_id)
            if session is not None:
                session.declined_menus.add(item.request.signature)
                session.denied_count += 1
            log.info(
                "[review] id=%s 授权超时（%.0fs），按拒绝处理",
                item.session_id,
                item.timeout_seconds,
            )
            self._emit(
                item.session_id,
                EVENT_REVIEW,
                {
                    "state": REVIEW_EXPIRED,
                    "review": item.to_dict(),
                    "reason": "等待授权超时，已按拒绝处理",
                },
            )

    def dismiss_review(self, session_id: str, reason: str = "会话已移除") -> None:
        """会话消失时丢弃它的待审项，避免弹出已不存在会话的授权框。"""
        target = str(session_id or "")
        with self._lock:
            item = self._reviews.pop(target, None)
        if item is None:
            return
        self._emit(
            target,
            EVENT_REVIEW,
            {"state": REVIEW_DISMISSED, "review": item.to_dict(), "reason": str(reason)},
        )

    def _finish(self, session_id: str, session: PtySession, backend: _Backend) -> None:
        if session.status == SessionStatus.STOPPED:
            # 用户主动停止：保留 STOPPED，不强改成"已完成"。
            session.finished_at = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
            status = session.status
        else:
            exit_code = getattr(backend, "exit_code", None)
            status = mark_finished(session, 0 if exit_code is None else exit_code)
        if not session.finished_at_ms:
            session.finished_at_ms = time.time() * 1000.0
        # 会话结束前把最后状态记入时间线，否则最后一段会缺失。
        screen = self._screens.get(session_id)
        if screen is not None:
            screen.mark_segment(force=True)
        # 核心：整树回收，消灭 codex/claude 残留子进程。
        reaped = reap_tree(session)
        log.info(
            "会话结束 id=%s status=%s exit=%s 回收子进程=%s",
            session_id,
            status.value,
            session.exit_code,
            reaped,
        )
        self._emit(session_id, EVENT_STATUS, {"status": status.value})

    # -- 事件 ----------------------------------------------------------
    def _emit(self, session_id: str, event: str, payload: dict[str, Any]) -> None:
        if self._on_event is None:
            return
        try:
            self._on_event(session_id, event, payload)
        except Exception:  # noqa: BLE001 - 事件回调异常不应中断轮询
            pass


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
]
