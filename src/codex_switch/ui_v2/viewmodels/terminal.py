"""AI 终端视图模型：把 TerminalManager 的状态/事件适配给 QML。

遵循现有 view model 风格：只读属性 + Slot 动作，业务规则全在 manager 里。
"""

from __future__ import annotations

from typing import Any

from ..qt_compat import Property, Signal, Slot
from ..terminal import EVENT_CHOICE, EVENT_STATUS, TerminalManager, check_pty_backend
from ..terminal.logging_setup import get_logger, log_path
from .base import BaseViewModel

log = get_logger()


class TerminalViewModel(BaseViewModel):
    """AI 终端多开：会话总览 + 输入 + 选项选择 + 清理残留。"""

    sessionsChanged = Signal()
    activeIdChanged = Signal()
    screenChanged = Signal()
    choiceChanged = Signal()
    runningCountChanged = Signal()
    zoomChanged = Signal()

    def __init__(self, controller, parent=None) -> None:
        self._controller = controller
        self._manager = TerminalManager(on_event=self._on_manager_event)
        self._sessions: list[dict[str, Any]] = []
        self._active_id = ""
        self._screen = ""
        self._awaiting_choice = False
        self._choices: list[str] = []
        self._running_count = 0
        self._zoomed_id = ""
        self._zoomed_screen = ""
        self._zoomed_choices: list[str] = []
        self._zoomed_awaiting = False
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

    # 放大浮窗使用的独立会话视图（不抢占主区 activeId）。
    @Property(str, notify=zoomChanged)
    def zoomedId(self) -> str:
        return self._zoomed_id

    @Property(str, notify=zoomChanged)
    def zoomedScreen(self) -> str:
        return self._zoomed_screen

    @Property(bool, notify=zoomChanged)
    def zoomedAwaiting(self) -> bool:
        return self._zoomed_awaiting

    @Property("QVariantList", notify=zoomChanged)
    def zoomedChoices(self) -> list[str]:
        return list(self._zoomed_choices)

    @Property(int, notify=runningCountChanged)
    def runningCount(self) -> int:
        return self._running_count

    @Property(bool, notify=sessionsChanged)
    def hasSessions(self) -> bool:
        return bool(self._sessions)

    @Property(str, constant=True)
    def logPath(self) -> str:
        """终端日志文件路径，供界面"打开日志"排查问题。"""
        return str(log_path())

    @Property(str, constant=True)
    def backendIssue(self) -> str:
        """PTY 运行环境问题描述；为空表示正常。

        冻结包最容易缺 winpty 的原生文件，提前暴露原因比让用户面对空白界面好。
        """
        return check_pty_backend()

    @Property("QVariantList", notify=sessionsChanged)
    def projects(self) -> list[dict[str, Any]]:
        """可选项目列表（供"按项目打开"选择器使用）。"""
        rows: list[dict[str, Any]] = []
        for project in self._controller.snapshot().get("projects") or []:
            rows.append(
                {
                    "id": str(project.get("id") or ""),
                    "name": str(project.get("name") or ""),
                    "projectDir": str(project.get("projectDir") or ""),
                }
            )
        return rows

    # -- 动作 ----------------------------------------------------------
    @Slot(str, str, str)
    def createSession(self, title: str, command: str, cwd: str) -> None:
        command = str(command or "").strip()
        if not command:
            self.report_error("请填写要运行的命令。")
            return
        self._start_session(str(title or command), command, str(cwd or ""), {})

    @Slot(str, str)
    def createProjectSession(self, project_id: str, client: str) -> None:
        """按项目打开：自动导入该项目的环境变量与 Codex/Claude 配置。

        复用 Workspace 的启动准备管线（刷新代理规则、同步项目绑定、写 Claude settings），
        再在应用内 PTY 中运行对应 CLI，而不是弹出外部控制台。
        """
        target = str(project_id or "")
        if not target:
            self.report_error("请先选择一个项目。")
            return
        try:
            spec = self._controller.workspace.terminal_launch_spec(str(client or "codex"), target)
        except Exception as exc:  # noqa: BLE001 - 统一转成可读提示
            self.report_error(str(exc))
            return
        command = str(spec.get("command") or "").strip()
        if not command:
            self.report_error("项目启动命令为空。")
            return
        self._start_session(
            str(spec.get("title") or command),
            command,
            str(spec.get("cwd") or ""),
            dict(spec.get("env") or {}),
        )

    def _start_session(self, title: str, command: str, cwd: str, env: dict[str, str]) -> None:
        """启动会话并把失败转成可见提示。

        PTY 启动可能因为命令不存在（如未安装 codex/claude）而抛错；这里统一
        捕获并通过 toast/错误通道报告，同时写入终端日志，避免"点了启动却没反应"。
        """
        log.info("请求启动会话 title=%r command=%r cwd=%r", title, command, cwd)
        issue = check_pty_backend()
        if issue:
            log.error("PTY 环境不可用：%s", issue)
            self.report_error(issue)
            return
        try:
            session_id = self._manager.create_session(title, command, cwd, env=env)
        except FileNotFoundError:
            log.error("找不到命令：%s", command)
            self.report_error(f"找不到命令：{command}。请确认已安装并加入 PATH。")
            return
        except Exception as exc:  # noqa: BLE001 - 统一转成可读提示
            log.exception("启动会话失败：%s", exc)
            self.report_error(f"启动会话失败：{exc}")
            return
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
    def zoom(self, session_id: str) -> None:
        """在新浮窗中放大一个会话（独立视图，不抢占主区焦点）。"""
        value = str(session_id or "")
        if not value:
            return
        self._zoomed_id = value
        self._refresh_zoom()
        self.zoomChanged.emit()

    @Slot()
    def closeZoom(self) -> None:
        if not self._zoomed_id:
            return
        self._zoomed_id = ""
        self.zoomChanged.emit()

    @Slot(str)
    def sendInput(self, text: str) -> None:
        if not self._active_id:
            return
        # 行结束的 CRLF 由 manager 统一追加，保持业务层单一职责。
        self._manager.send_input(self._active_id, str(text or ""))

    @Slot(str)
    def sendZoomInput(self, text: str) -> None:
        if not self._zoomed_id:
            return
        self._manager.send_input(self._zoomed_id, str(text or ""))

    @Slot(str)
    def stopZoom(self, session_id: str) -> None:
        """停止并清除放大视图中的会话，同时关闭浮窗。"""
        target = str(session_id or "")
        if not target:
            return
        name = self._title_for(target)
        self._manager.remove_session(target)
        if self._zoomed_id == target:
            self._zoomed_id = ""
            self.zoomChanged.emit()
        if self._active_id == target:
            self._active_id = ""
            self.activeIdChanged.emit()
            self._refresh_screen()
        self._refresh_sessions()
        if name:
            self._controller.showToast(f"已停止并清除「{name}」。", "info")

    @Slot(int)
    def sendChoice(self, index: int) -> None:
        if not self._active_id or not self._choices:
            return
        self._send_choice(self._active_id, self._choices, int(index))

    @Slot(int)
    def sendZoomChoice(self, index: int) -> None:
        if not self._zoomed_id or not self._zoomed_choices:
            return
        self._send_choice(self._zoomed_id, self._zoomed_choices, int(index))

    def _send_choice(self, session_id: str, choices: list[str], idx: int) -> None:
        if not (0 <= idx < len(choices)):
            return
        label = choices[idx]
        if label == "是":
            payload = "y"
        elif label == "否":
            payload = "n"
        else:
            # 编号选项：发送对应编号（1 起），这是 TUI 选择菜单的通用约定；
            # 发送标签文本往往不会被识别。
            payload = str(idx + 1)
        self._manager.send_input(session_id, payload)

    @Slot(str)
    def stopSession(self, session_id: str) -> None:
        """停止会话并从列表中清除。

        "停止"是终结操作：进程回收之后会话不应继续占着列表，
        否则已结束的会话会永远堆在那里无法清理（之前的表现就是"停不掉"）。
        """
        target = str(session_id or "")
        if not target:
            return
        name = self._title_for(target)
        # manager.remove_session 内部会先停止并整树回收，再摘除登记。
        self.removeSession(target)
        if name:
            self._controller.showToast(f"已停止并清除「{name}」。", "info")

    @Slot(str)
    def removeSession(self, session_id: str) -> None:
        target = str(session_id or "")
        self._manager.remove_session(target)
        if self._active_id == target:
            self._active_id = ""
            self.activeIdChanged.emit()
            self._refresh_screen()
        if self._zoomed_id == target:
            self._zoomed_id = ""
            self.zoomChanged.emit()
        self._refresh_sessions()

    @Slot()
    def clearFinished(self) -> None:
        """清除所有已结束（非运行中）的会话。"""
        finished = [
            row["sessionId"]
            for row in self._sessions
            if row.get("status") != "running"
        ]
        if not finished:
            self._controller.showToast("没有已结束的会话需要清除。", "info")
            return
        for session_id in finished:
            self._manager.remove_session(session_id)
        if self._active_id in finished:
            self._active_id = ""
            self.activeIdChanged.emit()
            self._refresh_screen()
        if self._zoomed_id in finished:
            self._zoomed_id = ""
            self.zoomChanged.emit()
        self._refresh_sessions()
        self._controller.showToast(f"已清除 {len(finished)} 个已结束的会话。", "success")

    def _title_for(self, session_id: str) -> str:
        for row in self._sessions:
            if row.get("sessionId") == session_id:
                return str(row.get("title") or "")
        return ""

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

    def _refresh_zoom(self) -> None:
        if not self._zoomed_id:
            return
        text = self._manager.screen_text(self._zoomed_id)
        awaiting = False
        choices: list[str] = []
        for row in self._sessions:
            if row["sessionId"] == self._zoomed_id:
                awaiting = row.get("awaitingChoice", False)
                choices = list(row.get("choices", []))
                break
        if text != self._zoomed_screen or awaiting != self._zoomed_awaiting or choices != self._zoomed_choices:
            self._zoomed_screen = text
            self._zoomed_awaiting = awaiting
            self._zoomed_choices = choices
            self.zoomChanged.emit()

    def _on_manager_event(self, session_id: str, event: str, payload: dict[str, Any]) -> None:
        # 管理器的轮询在后台线程运行，必须把它派发回 GUI 线程再触碰 QML 属性。
        # QTimer.singleShot 在"无事件循环的线程"上创建的定时器永远不会触发，
        # 因此用 QMetaObject.invokeMethod(QueuedConnection) 显式投递到本对象所在的 GUI 线程。
        from ..qt_compat import QT_AVAILABLE

        if QT_AVAILABLE:
            from PySide6.QtCore import QMetaObject, Qt, Q_ARG

            QMetaObject.invokeMethod(
                self,
                "_dispatch_manager_event",
                Qt.QueuedConnection,
                Q_ARG(str, session_id),
                Q_ARG(str, event),
                Q_ARG("QVariantMap", payload),
            )
        else:
            self._dispatch_manager_event(session_id, event, payload)

    @Slot(str, str, "QVariantMap")
    def _dispatch_manager_event(self, session_id: str, event: str, payload: dict[str, Any]) -> None:
        self._refresh_sessions()
        if session_id == self._active_id:
            self._refresh_screen()
        if session_id == self._zoomed_id:
            self._refresh_zoom()
        if event == EVENT_STATUS:
            self._report_status(session_id, payload)
        elif event == EVENT_CHOICE:
            if session_id == self._active_id:
                self._refresh_screen()
            if session_id == self._zoomed_id:
                self._refresh_zoom()

    def _report_status(self, session_id: str, payload: dict[str, Any]) -> None:
        status = payload.get("status")
        row = next((r for r in self._sessions if r["sessionId"] == session_id), None)
        if row is None:
            # 会话已被用户清除；迟到的轮询事件不应再弹出提示，
            # 否则"停止并清除"之后还会冒出一条"已完成"。
            return
        name = row.get("title") or "会话"
        if status == "completed":
            self._controller.showToast(f"「{name}」已完成。", "success")
        elif status == "failed":
            self._controller.showToast(f"「{name}」运行失败（退出码非 0）。", "error")
        elif status == "stopped":
            self._controller.showToast(f"「{name}」已停止。", "info")

    def dispose(self) -> None:
        self._manager.shutdown()


__all__ = ["TerminalViewModel"]
