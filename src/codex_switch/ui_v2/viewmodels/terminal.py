"""AI 终端视图模型：把 TerminalManager 的状态/事件适配给 QML。

遵循现有 view model 风格：只读属性 + Slot 动作，业务规则全在 manager 里。
"""

from __future__ import annotations

from typing import Any

from ..qt_compat import Property, Signal, Slot
from ..terminal import EVENT_CHOICE, EVENT_STATUS, TerminalManager
from .base import BaseViewModel


class TerminalViewModel(BaseViewModel):
    """AI 终端多开：会话总览 + 输入 + 选项选择 + 清理残留。"""

    sessionsChanged = Signal()
    activeIdChanged = Signal()
    screenChanged = Signal()
    choiceChanged = Signal()
    runningCountChanged = Signal()

    def __init__(self, controller, parent=None) -> None:
        self._controller = controller
        self._manager = TerminalManager(on_event=self._on_manager_event)
        self._sessions: list[dict[str, Any]] = []
        self._active_id = ""
        self._screen = ""
        self._awaiting_choice = False
        self._choices: list[str] = []
        self._running_count = 0
        super().__init__(parent)
        self._manager.start()

    # -- 属性 ----------------------------------------------------------
    @Property("QVariantList", notify=sessionsChanged)
    def sessions(self) -> list[dict[str, Any]]:
        return list(self._sessions)

    @Property(str, notify=activeIdChanged)
    def activeId(self) -> str:
        return self._active_id

    @Property(str, notify=screenChanged)
    def screen(self) -> str:
        return self._screen

    @Property(bool, notify=choiceChanged)
    def awaitingChoice(self) -> bool:
        return self._awaiting_choice

    @Property("QVariantList", notify=choiceChanged)
    def choices(self) -> list[str]:
        return list(self._choices)

    @Property(int, notify=runningCountChanged)
    def runningCount(self) -> int:
        return self._running_count

    @Property(bool, notify=sessionsChanged)
    def hasSessions(self) -> bool:
        return bool(self._sessions)

    # -- 动作 ----------------------------------------------------------
    @Slot(str, str, str)
    def createSession(self, title: str, command: str, cwd: str) -> None:
        command = str(command or "").strip()
        if not command:
            self.report_error("请填写要运行的命令。")
            return
        session_id = self._manager.create_session(str(title or command), command, str(cwd or ""))
        self._refresh_sessions()
        self.focus(session_id)

    @Slot(str)
    def focus(self, session_id: str) -> None:
        value = str(session_id or "")
        if value == self._active_id:
            return
        self._active_id = value
        self.activeIdChanged.emit()
        self._refresh_screen()

    @Slot(str)
    def sendInput(self, text: str) -> None:
        if not self._active_id:
            return
        # 行结束的 CRLF 由 manager 统一追加，保持业务层单一职责。
        self._manager.send_input(self._active_id, str(text or ""))

    @Slot(int)
    def sendChoice(self, index: int) -> None:
        if not self._active_id or not self._choices:
            return
        idx = int(index)
        if 0 <= idx < len(self._choices):
            # 确认型（是/否）映射为 y/n；其余原样发送。
            label = self._choices[idx]
            payload = "y" if label == "是" else ("n" if label == "否" else label)
            self._manager.send_input(self._active_id, payload)

    @Slot(str)
    def stopSession(self, session_id: str) -> None:
        self._manager.stop_session(str(session_id), reap=True)
        self._refresh_sessions()

    @Slot(str)
    def removeSession(self, session_id: str) -> None:
        self._manager.remove_session(str(session_id))
        if self._active_id == session_id:
            self._active_id = ""
            self.activeIdChanged.emit()
            self._refresh_screen()
        self._refresh_sessions()

    @Slot()
    def cleanupOrphans(self) -> None:
        cleaned = self._manager.cleanup_orphans()
        if cleaned:
            names = "、".join(item["title"] for item in cleaned)
            self._controller.showToast(f"已清理 {len(cleaned)} 个残留会话的子进程：{names}", "success")
        else:
            self._controller.showToast("未发现需要清理的残留进程。", "info")
        self._refresh_sessions()

    # -- 内部刷新 ------------------------------------------------------
    def rebuild(self) -> None:
        """被 controller._refresh_models 统一调用；本模型由轮询线程驱动刷新。"""
        self._refresh_sessions()

    def _refresh_sessions(self) -> None:
        rows = [s.to_dict() for s in self._manager.summaries()]
        if rows != self._sessions:
            self._sessions = rows
            self.sessionsChanged.emit()
        rc = self._manager.running_count()
        if rc != self._running_count:
            self._running_count = rc
            self.runningCountChanged.emit()

    def _refresh_screen(self) -> None:
        text = self._manager.screen_text(self._active_id) if self._active_id else ""
        if text != self._screen:
            self._screen = text
            self.screenChanged.emit()
        # 同步"等待选择"态
        awaiting = False
        choices: list[str] = []
        for row in self._sessions:
            if row["sessionId"] == self._active_id:
                awaiting = row.get("awaitingChoice", False)
                choices = list(row.get("choices", []))
                break
        if awaiting != self._awaiting_choice or choices != self._choices:
            self._awaiting_choice = awaiting
            self._choices = choices
            self.choiceChanged.emit()

    def _on_manager_event(self, session_id: str, event: str, payload: dict[str, Any]) -> None:
        # 跨线程事件用 QTimer 抛回主线程刷新，避免直接触碰 QML 属性。
        from ..qt_compat import QTimer

        def refresh() -> None:
            self._refresh_sessions()
            if session_id == self._active_id:
                self._refresh_screen()
            if event == EVENT_STATUS:
                self._report_status(session_id, payload)
            elif event == EVENT_CHOICE:
                if session_id == self._active_id:
                    self._refresh_screen()

        QTimer.singleShot(0, refresh)

    def _report_status(self, session_id: str, payload: dict[str, Any]) -> None:
        status = payload.get("status")
        row = next((r for r in self._sessions if r["sessionId"] == session_id), None)
        name = row.get("title", "会话") if row else "会话"
        if status == "completed":
            self._controller.showToast(f"「{name}」已完成。", "success")
        elif status == "failed":
            self._controller.showToast(f"「{name}」运行失败（退出码非 0）。", "error")
        elif status == "stopped":
            self._controller.showToast(f"「{name}」已停止。", "info")

    def dispose(self) -> None:
        self._manager.shutdown()


__all__ = ["TerminalViewModel"]
