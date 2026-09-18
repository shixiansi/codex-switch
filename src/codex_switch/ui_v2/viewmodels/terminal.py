"""AI 终端视图模型：把 TerminalManager 的状态/事件适配给 QML。

遵循现有 view model 风格：只读属性 + Slot 动作，业务规则全在 manager 里。
审查策略（模式、预算、通知与提示音开关）从 ``terminal_policy.json`` 读出后
注入 manager——视图模型只做接线，不参与判定。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..qt_compat import Property, Signal, Slot
from ..terminal import (
    EVENT_CHOICE,
    EVENT_REVIEW,
    EVENT_STATUS,
    EVENT_TIMELINE,
    MODE_DESCRIPTIONS,
    MODE_LABELS,
    MODE_OFF,
    MODES,
    REVIEW_DENIED,
    REVIEW_DISMISSED,
    REVIEW_EXPIRED,
    REVIEW_PENDING,
    InputHistory,
    PolicyConfig,
    PromptHistoryReader,
    ReviewPolicy,
    TerminalManager,
    check_pty_backend,
    command_hints,
    detect_cli,
    load_config,
    normalize_mode,
    save_config,
)
from ..terminal.logging_setup import get_logger, log_path
from ..terminal.image_attach import FILE_DIALOG_FILTER, prepare_image
from .base import BaseViewModel

log = get_logger()


class TerminalViewModel(BaseViewModel):
    """AI 终端多开：会话总览 + 输入 + 选项选择 + 清理残留 + 风险审查。"""

    sessionsChanged = Signal()
    activeIdChanged = Signal()
    screenChanged = Signal()
    choiceChanged = Signal()
    runningCountChanged = Signal()
    zoomChanged = Signal()
    timelineChanged = Signal()
    autoAnswerChanged = Signal()
    inputAssistChanged = Signal()
    reviewChanged = Signal()
    reviewModeChanged = Signal()

    def __init__(self, controller, parent=None) -> None:
        self._controller = controller
        # 审查策略必须先于 manager 建好：manager 需要注入策略才能判定。
        self._policy_config = self._load_policy_config()
        self._manager = TerminalManager(
            on_event=self._on_manager_event,
            policy=ReviewPolicy(self._policy_config),
        )
        self._sessions: list[dict[str, Any]] = []
        self._active_id = ""
        self._screen = ""
        self._awaiting_choice = False
        self._choices: list[str] = []
        self._selected_index = -1
        self._choice_kind = "numbered"
        self._running_count = 0
        self._zoomed_id = ""
        self._zoomed_screen = ""
        self._zoomed_choices: list[str] = []
        self._zoomed_awaiting = False
        self._zoomed_selected_index = -1
        self._zoomed_choice_kind = "numbered"
        # 自动应答开关由审查模式决定：关闭模式下完全不自动应答。
        enabled = self._policy_config.mode != MODE_OFF
        self._auto_answer = enabled
        self._manager.auto_answer = enabled
        self._active_timeline = ""
        # 待授权项：按会话 id 索引当前等待用户决定的菜单。
        self._reviews: dict[str, dict[str, Any]] = {}
        # 最近一次"仅通知"的审查结果，供界面提示条展示。
        self._last_notice: dict[str, Any] = {}
        # 输入历史与指令提示（纯逻辑，见 terminal/input_assist.py）。
        self._history = InputHistory()
        # 项目级历史读取器：从 CLI 自己的会话记录里取以前发过的提示词。
        self._cli_history = PromptHistoryReader()
        self._hint_visible = False
        self._hint_items: list[dict[str, str]] = []
        self._hint_selected = -1
        super().__init__(parent)
        self._manager.start()

    # -- 策略加载 ------------------------------------------------------
    def _storage_root(self) -> Path | None:
        """应用数据目录；取不到时返回 None（策略持久化会被跳过）。"""
        workspace = getattr(self._controller, "workspace", None)
        store = getattr(workspace, "store", None)
        root = getattr(store, "root_dir", None)
        return Path(root) if root else None

    def _load_policy_config(self) -> PolicyConfig:
        """读取审查策略；读不到就用默认（balanced）。"""
        root = self._storage_root()
        if root is None:
            return PolicyConfig()
        try:
            return load_config(root)
        except Exception:  # noqa: BLE001 - 策略读取失败不该让终端不可用
            log.exception("读取审查策略失败，使用默认策略")
            return PolicyConfig()

    def _persist_policy(self) -> None:
        root = self._storage_root()
        if root is None:
            return
        try:
            save_config(root, self._policy_config)
        except Exception:  # noqa: BLE001 - 保存失败不该影响当前会话
            log.exception("保存审查策略失败")

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

    @Property(str, notify=timelineChanged)
    def activeTimeline(self) -> str:
        """当前会话带时间戳的输出时间线。"""
        return self._active_timeline

    @Property(bool, notify=autoAnswerChanged)
    def autoAnswer(self) -> bool:
        """是否自动应答选择菜单（由审查模式决定，不再单独切换）。"""
        return self._auto_answer

    @autoAnswer.setter
    def autoAnswer(self, value: bool) -> None:
        self.setAutoAnswer(bool(value))

    # -- 风险审查 ------------------------------------------------------
    @Property(str, notify=reviewModeChanged)
    def reviewMode(self) -> str:
        """当前审查模式：off / strict / balanced / observe / full。"""
        return self._policy_config.mode

    @Property(str, notify=reviewModeChanged)
    def reviewModeLabel(self) -> str:
        return MODE_LABELS.get(self._policy_config.mode, self._policy_config.mode)

    @Property("QVariantList", notify=reviewModeChanged)
    def reviewModes(self) -> list[dict[str, str]]:
        """全部可选模式（含说明），供界面渲染分段控件。"""
        return [
            {
                "value": mode,
                "label": MODE_LABELS.get(mode, mode),
                "description": MODE_DESCRIPTIONS.get(mode, ""),
            }
            for mode in MODES
        ]

    @Property("QVariantMap", notify=reviewModeChanged)
    def reviewPolicySummary(self) -> dict[str, Any]:
        """策略摘要：供界面展示超时、预算、声音等当前生效值。"""
        return dict(self._manager.policy.describe())

    @Property("QVariantList", notify=reviewChanged)
    def pendingReviews(self) -> list[dict[str, Any]]:
        """全部等待授权的项（可能来自多个会话）。"""
        return [dict(item) for item in self._reviews.values()]

    @Property(int, notify=reviewChanged)
    def reviewPendingCount(self) -> int:
        return len(self._reviews)

    @Property(bool, notify=reviewChanged)
    def reviewPending(self) -> bool:
        return bool(self._reviews)

    @Property("QVariantMap", notify=reviewChanged)
    def activeReview(self) -> dict[str, Any]:
        """当前选中会话的待授权项；没有则为空对象。"""
        item = self._reviews.get(self._active_id)
        return dict(item) if item else {}

    @Property("QVariantMap", notify=reviewChanged)
    def zoomedReview(self) -> dict[str, Any]:
        item = self._reviews.get(self._zoomed_id)
        return dict(item) if item else {}

    @Property("QVariantMap", notify=reviewChanged)
    def lastReviewNotice(self) -> dict[str, Any]:
        """最近一次"仅通知"的自动应答，供提示条展示。"""
        return dict(self._last_notice)

    @Property(bool, notify=choiceChanged)
    def awaitingChoice(self) -> bool:
        return self._awaiting_choice

    @Property("QVariantList", notify=choiceChanged)
    def choices(self) -> list[str]:
        return list(self._choices)

    @Property(int, notify=choiceChanged)
    def selectedIndex(self) -> int:
        """菜单当前高亮项下标；-1 表示看不出选中在哪。"""
        return self._selected_index

    @Property(str, notify=choiceChanged)
    def choiceKind(self) -> str:
        """菜单种类：confirm / numbered / list。

        页面据此决定提示文案：list 类菜单（codex resume）只能用方向键选，
        点按钮时界面要发 ↑↓ 而不是数字。
        """
        return self._choice_kind

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

    @Property(int, notify=zoomChanged)
    def zoomedSelectedIndex(self) -> int:
        return self._zoomed_selected_index

    @Property(str, notify=zoomChanged)
    def zoomedChoiceKind(self) -> str:
        return self._zoomed_choice_kind

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

    # -- 输入辅助（历史 / 指令提示）------------------------------------
    @Property(bool, notify=inputAssistChanged)
    def hintVisible(self) -> bool:
        """是否应该显示指令候选条。"""
        return self._hint_visible

    @Property("QVariantList", notify=inputAssistChanged)
    def hintItems(self) -> list[dict[str, str]]:
        return [dict(item) for item in self._hint_items]

    @Property(int, notify=inputAssistChanged)
    def hintSelected(self) -> int:
        return self._hint_selected

    @Property(int, notify=inputAssistChanged)
    def historyLength(self) -> int:
        """当前会话已记录的历史条数，供界面提示 ↑ 可用。"""
        return len(self._history.entries(self._active_id))

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
    @Slot(bool)
    def setAutoAnswer(self, value: bool) -> None:
        """开启/关闭选择菜单的自动应答。

        兼容旧界面的一键开关："关闭"等价于把模式切到 off，重新开启则回到
        默认的 balanced——而不是简单地置一个布尔量绕过审查。
        """
        enabled = bool(value)
        if enabled == self._auto_answer:
            return
        self._apply_mode("balanced" if enabled else MODE_OFF)

    @Slot()
    def toggleAutoAnswer(self) -> None:
        """无参槽：QML 调用 ``toggleAutoAnswer()`` 时不传参数。

        原签名写成 ``@Slot(bool)``，与实现不符；一旦这个槽被 QML 调用就会
        因为匹配不到签名而静默失效。
        """
        self.setAutoAnswer(not self._auto_answer)

    @Slot(str)
    def setReviewMode(self, mode: str) -> None:
        """切换审查模式（关闭 / 严格 / 平衡 / 只通知 / 完全放行）。"""
        self._apply_mode(mode)

    def _apply_mode(self, mode: str) -> None:
        """应用新模式：热更新策略、持久化，并把变化告知界面。

        切到"关闭"时如果还有等待授权的菜单，一并清掉——那些请求是在旧模式下
        产生的，留着会弹出一个已经不该存在的授权框。
        """
        target = normalize_mode(mode)
        changed_mode = target != self._policy_config.mode
        if changed_mode:
            self._policy_config.mode = target
            self._manager.set_policy(ReviewPolicy(self._policy_config))
            self._persist_policy()
        self._sync_auto_answer()
        self._on_policy_changed()
        if changed_mode:
            self.reviewModeChanged.emit()
            description = MODE_DESCRIPTIONS.get(target, "")
            self._controller.showToast(
                f"自动应答模式：{MODE_LABELS.get(target, target)}。{description}",
                "warning" if target == "full" else "info",
            )
            log.info("审查模式切换为 %s", target)

    def _sync_auto_answer(self) -> None:
        """把"是否自动应答"映射成 manager 的开关，并在关闭时清空待审项。"""
        enabled = self._policy_config.mode != MODE_OFF
        if enabled != self._auto_answer:
            self._auto_answer = enabled
            self.autoAnswerChanged.emit()
        self._manager.auto_answer = enabled
        if not enabled:
            # 关闭后不该再有任何东西冒出来问用户。
            for session_id in list(self._reviews.keys()):
                self._manager.dismiss_review(session_id, "自动应答已关闭")
            if self._reviews:
                self._reviews.clear()
                self.reviewChanged.emit()

    # -- 授权 ----------------------------------------------------------
    @Slot(str)
    def approveReview(self, session_id: str) -> None:
        """允许本次：只发这一次按键。"""
        self.resolveReview(session_id, "approve")

    @Slot(str)
    def allowReviewKind(self, session_id: str) -> None:
        """本会话允许此类：本会话内同签名菜单不再询问（不落盘）。"""
        self.resolveReview(session_id, "allow_kind")

    @Slot(str)
    def denyReview(self, session_id: str) -> None:
        """拒绝：不发送，且同一菜单不再重复提示。"""
        self.resolveReview(session_id, "deny")

    @Slot(str, str)
    def resolveReview(self, session_id: str, decision: str) -> None:
        """处理一个待授权项；``decision`` 取 approve / allow_kind / deny。

        这是**唯一**的授权入口：controller 的授权弹窗与 QML 的按钮都走这里，
        保证"清空待授权项 + 推进队列"这两件事不会被某条路径漏掉。
        """
        target = str(session_id or "")
        if not target:
            return
        approve = decision != "deny"
        self._manager.resolve_review(
            target, approve, allow_kind=decision == "allow_kind"
        )
        # 事件会经 _dispatch_manager_event 回到这里刷新状态；
        # 这里再同步一次，避免没有事件时界面停在旧状态。
        self._reviews.pop(target, None)
        self._sync_review_prompt()
        self.reviewChanged.emit()

    @Slot()
    def clearReviewNotice(self) -> None:
        """关闭"仅通知"提示条。"""
        if not self._last_notice:
            return
        self._last_notice = {}
        self.reviewChanged.emit()

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
        # 接上该项目以前的提示词，这样一按 ↑ 就能翻到历史，
        # 而不是从零开始（新会话本身没有任何历史）。
        self._seed_project_history(session_id)

    def _seed_project_history(self, session_id: str) -> int:
        """把会话所在目录的项目级历史接进输入历史。

        读的是 CLI 自己存的会话记录（codex 与 claude 各有一套存储）。
        读不到时静默跳过——历史只是便利功能，绝不该影响终端本身可用。
        """
        session = self._manager.session(session_id)
        if session is None:
            return 0
        cwd = str(session.cwd or "").strip()
        if not cwd:
            return 0
        cli = detect_cli(str(session.command or ""))
        try:
            prompts = self._cli_history.prompts_for(cwd, cli)
        except Exception:  # noqa: BLE001 - 读历史失败不该影响终端
            log.exception("读取项目历史失败 cwd=%s cli=%s", cwd, cli)
            return 0
        added = self._history.seed(session_id, prompts)
        if added:
            log.info(
                "已接入项目历史 id=%s 条数=%s cli=%s cwd=%s",
                session_id, added, cli or "(未知)", cwd,
            )
            self.inputAssistChanged.emit()
        return added

    @Slot(result=int)
    def reloadProjectHistory(self) -> int:
        """手动重新读取项目历史（界面按钮用）。"""
        added = self._seed_project_history(self._active_id)
        self._controller.showToast(
            f"已载入 {added} 条历史提示词。" if added else "没有新的历史提示词。",
            "info",
        )
        return added

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
        # 记入历史后再发送：失败也要记，用户会想重试同一条。
        self._history.record(self._active_id, text)
        self._update_hints("")
        # 行结束的 CRLF 由 manager 统一追加，保持业务层单一职责。
        self._manager.send_input(self._active_id, str(text or ""))

    # -- 输入辅助 ------------------------------------------------------
    @Slot(str)
    def updateInputHints(self, text: str) -> None:
        """输入框内容变化时刷新指令候选。"""
        self._update_hints(text)

    def _update_hints(self, text: str) -> None:
        hint = command_hints(text)
        if (
            hint.visible == self._hint_visible
            and hint.items == self._hint_items
            and hint.selected == self._hint_selected
        ):
            return
        self._hint_visible = hint.visible
        self._hint_items = [dict(item) for item in hint.items]
        self._hint_selected = hint.selected
        self.inputAssistChanged.emit()

    @Slot(str, result=str)
    def historyPrevious(self, draft: str) -> str:
        """↑：把更早的一条历史填回输入框（当前会话）。

        返回空字符串表示"没有更早的了"，调用方据此保持输入框不变。
        用返回值而不是直接改输入框：QML 的 TextField 由界面掌控，
        业务层只负责算出该显示什么。
        """
        return self._history_previous_for(self._active_id, draft)

    @Slot(result=str)
    def historyNext(self) -> str:
        """↓：回到更近的一条；已到最新则回到开始翻历史前的草稿。"""
        return self._history_next_for(self._active_id)

    def _history_previous_for(self, session_id: str, draft: str) -> str:
        if not session_id:
            return ""
        value = self._history.previous(session_id, str(draft or ""))
        self.inputAssistChanged.emit()
        return value if value is not None else ""

    def _history_next_for(self, session_id: str) -> str:
        if not session_id:
            return ""
        value = self._history.next(session_id)
        self.inputAssistChanged.emit()
        return value if value is not None else ""

    @Slot(str, result=str)
    def zoomHistoryPrevious(self, draft: str) -> str:
        """↑（放大浮窗）：历史必须取自被放大的那个会话。

        早期实现统一用 activeId，结果放大窗口里按 ↑ 翻到的是另一个会话的
        消息——发出去就串了会话。
        """
        return self._history_previous_for(self._zoomed_id, draft)

    @Slot(result=str)
    def zoomHistoryNext(self) -> str:
        return self._history_next_for(self._zoomed_id)

    @Slot()
    def resetHistoryCursor(self) -> None:
        """用户手动编辑输入框：退出翻历史状态。"""
        if self._active_id:
            self._history.reset_cursor(self._active_id)

    @Slot(int, result=str)
    def applyHint(self, index: int) -> str:
        """把第 index 个候选补全进输入框（Tab 或点击候选）。

        返回补全后的文本；空字符串表示没有该候选，调用方保持输入框不变。
        """
        if not self._hint_visible or not (0 <= index < len(self._hint_items)):
            return ""
        return str(self._hint_items[index].get("name") or "")

    @Slot(int)
    def selectHint(self, index: int) -> None:
        """在候选条里上下移动高亮。"""
        if not self._hint_items:
            return
        count = len(self._hint_items)
        value = int(index) % count
        if value == self._hint_selected:
            return
        self._hint_selected = value
        self.inputAssistChanged.emit()

    @Slot()
    def hideHints(self) -> None:
        self._update_hints("")

    @Slot(str)
    def sendZoomInput(self, text: str) -> None:
        if not self._zoomed_id:
            return
        # 历史按会话记录，放大窗口发的消息也该进它自己的历史。
        self._history.record(self._zoomed_id, text)
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
        """选中某个选项。

        交给 manager 决定发送方式：编号菜单直接发编号，无编号菜单（如 codex 的
        resume 列表）必须用方向键移动——发数字会被 TUI 当成搜索关键词，
        结果就是"能看到选项却选不中"。
        """
        if not (0 <= idx < len(choices)):
            return
        self._manager.select_choice(session_id, int(idx))

    @Slot(str)
    def sendKey(self, key: str) -> None:
        """向当前会话发送特殊按键（方向键 / Enter / Esc / Tab / Ctrl-C）。"""
        if not self._active_id:
            return
        if self._manager.send_key(self._active_id, str(key or "")):
            # 方向键会移动 TUI 的选中项，屏幕随后由轮询刷新。
            log.debug("发送按键 %s -> %s", key, self._active_id)

    @Slot(str)
    def sendZoomKey(self, key: str) -> None:
        if not self._zoomed_id:
            return
        self._manager.send_key(self._zoomed_id, str(key or ""))

    # -- 附加图片 ------------------------------------------------------
    #
    # AI CLI 收图只有一条通道：**图片进系统剪贴板 + 向 PTY 发 Ctrl+V**，
    # 由 CLI 自己读剪贴板（codex 实测会随即显示 `[Image #1]`）。
    # PTY 是纯文本流，无法直接传二进制，所以"发送图片"本质上就是这两步。
    #
    # 剪贴板的读写是 Qt 的事，因此集中在这里；业务层只负责发键。
    @Slot(str, result=bool)
    def attachImage(self, file_path: str) -> bool:
        """把一张图片附加到当前会话（先校验，再写剪贴板，最后发 Ctrl+V）。"""
        return self._attach_image(self._active_id, file_path)

    @Slot(result=bool)
    def attachImageFromClipboard(self, ) -> bool:
        """直接把剪贴板里已有的图片附加过去（例如刚截图）。

        这条路径**不改写剪贴板**，适合"我刚截了图"的常见场景。
        """
        return self._attach_clipboard(self._active_id)

    @Slot(str, result=bool)
    def attachZoomImage(self, file_path: str) -> bool:
        """放大窗口的附加图片（放大视图是独立会话视图）。"""
        return self._attach_image(self._zoomed_id, file_path)

    @Slot(result=bool)
    def attachZoomImageFromClipboard(self) -> bool:
        return self._attach_clipboard(self._zoomed_id)

    @Slot(str, result=bool)
    def attachImageFromDataUrl(self, data_url: str) -> bool:
        """从拖拽/粘贴进来的 data: URL 附加图片。

        QML 的 DropArea 给出的通常是 ``data:image/png;base64,...``，
        这里解码后**直接放进剪贴板**（不落临时文件，避免留下一堆垃圾）。
        """
        return self._attach_data_url(self._active_id, data_url)

    @Slot(str, result=bool)
    def attachZoomImageFromDataUrl(self, data_url: str) -> bool:
        return self._attach_data_url(self._zoomed_id, data_url)

    @Slot(result=str)
    def imageFileFilter(self) -> str:
        """文件对话框的过滤器（供 QML 的 FileDialog 使用）。"""
        return FILE_DIALOG_FILTER

    def _attach_image(self, session_id: str, file_path: str) -> bool:
        """校验文件 → 写入剪贴板 → 发 Ctrl+V。"""
        target = str(session_id or "")
        if not target:
            self._controller.showToast("请先选择一个会话。", "warning")
            return False
        try:
            image = prepare_image(file_path)
        except ValueError as exc:
            # 校验失败给出明确原因，而不是让用户面对"点了没反应"。
            self._controller.showToast(str(exc), "error")
            log.info("附加图片被拒绝：%s", exc)
            return False
        if not self._write_clipboard_file(image):
            return False
        return self._finish_attach(target, image.name)

    def _attach_clipboard(self, session_id: str) -> bool:
        """直接附加剪贴板里已有的图片（不改写剪贴板）。"""
        target = str(session_id or "")
        if not target:
            self._controller.showToast("请先选择一个会话。", "warning")
            return False
        if not self._clipboard_has_image():
            self._controller.showToast("剪贴板里没有图片。可先复制或截图，或点「选择图片」。", "warning")
            return False
        return self._finish_attach(target, "剪贴板图片")

    def _attach_data_url(self, session_id: str, data_url: str) -> bool:
        """把 data: URL 解码后放进剪贴板再附加（拖拽/粘贴场景）。"""
        target = str(session_id or "")
        if not target:
            self._controller.showToast("请先选择一个会话。", "warning")
            return False
        if not self._write_clipboard_data_url(data_url):
            return False
        return self._finish_attach(target, "拖入的图片")

    def _finish_attach(self, session_id: str, label: str) -> bool:
        """发 Ctrl+V 让 CLI 取走剪贴板里的图片。"""
        if not self._manager.paste_clipboard_image(session_id):
            self._controller.showToast("会话已结束，无法附加图片。", "error")
            return False
        self._controller.showToast(f"已附加图片：{label}", "success")
        log.info("已请求 CLI 从剪贴板附加图片 id=%s label=%s", session_id, label)
        return True

    # -- 剪贴板（唯一接触 QClipboard 的地方）---------------------------
    def _clipboard(self):
        """取系统剪贴板；不可用时返回 None。"""
        try:
            from PySide6.QtGui import QGuiApplication

            app = QGuiApplication.instance()
            return app.clipboard() if app is not None else None
        except Exception:  # noqa: BLE001 - 无 Qt 环境下静默降级
            return None

    def _clipboard_has_image(self) -> bool:
        clipboard = self._clipboard()
        if clipboard is None:
            return False
        try:
            return bool(clipboard.mimeData().hasImage())
        except Exception:  # noqa: BLE001
            return False

    def _write_clipboard_file(self, image) -> bool:
        """把磁盘上的图片读进剪贴板。"""
        from PySide6.QtGui import QImage

        try:
            data = QImage(str(image.path))
        except Exception:  # noqa: BLE001
            data = QImage()
        if data.isNull():
            self._controller.showToast(f"无法解码这张图片：{image.name}", "error")
            return False
        return self._set_clipboard_image(data, image.name)

    def _write_clipboard_data_url(self, data_url: str) -> bool:
        """把 data: URL 解码成图片放进剪贴板。"""
        from PySide6.QtCore import QByteArray
        from PySide6.QtGui import QImage

        text = str(data_url or "")
        if not text.startswith("data:image/"):
            # 必须给出提示：静默返回 False 会让拖入文本文件的用户毫无头绪。
            self._controller.showToast("只支持图片文件。", "error")
            return False
        try:
            _, _, payload = text.partition(",")
            raw = QByteArray.fromBase64(payload.encode("ascii"))
            data = QImage()
            if not data.loadFromData(raw):
                self._controller.showToast("无法解码拖入的图片。", "error")
                return False
        except Exception as exc:  # noqa: BLE001
            self._controller.showToast(f"无法解码拖入的图片：{exc}", "error")
            return False
        return self._set_clipboard_image(data, "拖入的图片")

    def _set_clipboard_image(self, data, label: str) -> bool:
        clipboard = self._clipboard()
        if clipboard is None:
            self._controller.showToast("当前环境无法访问系统剪贴板，无法附加图片。", "error")
            return False
        try:
            clipboard.setImage(data)
        except Exception as exc:  # noqa: BLE001
            self._controller.showToast(f"写入剪贴板失败：{exc}", "error")
            return False
        return True

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
        # 会话没了，它的输入历史也没有意义；不清会随长时间使用越堆越多。
        self._history.forget(target)
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
        self._sync_reviews()

    def _sync_reviews(self) -> None:
        """用 manager 的权威状态校正本地待审集合。

        本地集合是事件驱动的，可能因为会话被清除等原因落后于 manager；
        这里以 manager 为准，避免界面显示一个已经不存在的授权请求。
        """
        authoritative = {
            str(item.get("sessionId") or ""): item for item in self._manager.pending_reviews()
        }
        # 会话已消失的待审项直接丢弃。
        alive = {row["sessionId"] for row in self._sessions}
        authoritative = {key: item for key, item in authoritative.items() if key in alive}
        if authoritative != self._reviews:
            self._reviews = authoritative
            self.reviewChanged.emit()
        # 会话可能被清除而连带丢掉待审项：队列也要跟着推进，
        # 否则弹窗会一直停在那个已经不存在的请求上。
        self._sync_review_prompt()

    def _refresh_screen(self) -> None:
        text = self._manager.screen_text(self._active_id) if self._active_id else ""
        if text != self._screen:
            self._screen = text
            self.screenChanged.emit()
        self._refresh_timeline()
        # 同步"等待选择"态
        awaiting = False
        choices: list[str] = []
        selected = -1
        kind = "numbered"
        for row in self._sessions:
            if row["sessionId"] == self._active_id:
                awaiting = row.get("awaitingChoice", False)
                choices = list(row.get("choices", []))
                selected = int(row.get("selectedIndex", -1))
                kind = str(row.get("kind", "numbered"))
                break
        if (
            awaiting != self._awaiting_choice
            or choices != self._choices
            or selected != self._selected_index
            or kind != self._choice_kind
        ):
            self._awaiting_choice = awaiting
            self._choices = choices
            self._selected_index = selected
            self._choice_kind = kind
            self.choiceChanged.emit()

    def _refresh_timeline(self) -> None:
        """刷新当前会话的带时间戳时间线。"""
        timeline = self._manager.timeline_text(self._active_id) if self._active_id else ""
        if timeline != self._active_timeline:
            self._active_timeline = timeline
            self.timelineChanged.emit()

    def _refresh_zoom(self) -> None:
        if not self._zoomed_id:
            return
        text = self._manager.screen_text(self._zoomed_id)
        awaiting = False
        choices: list[str] = []
        selected = -1
        kind = "numbered"
        for row in self._sessions:
            if row["sessionId"] == self._zoomed_id:
                awaiting = row.get("awaitingChoice", False)
                choices = list(row.get("choices", []))
                selected = int(row.get("selectedIndex", -1))
                kind = str(row.get("kind", "numbered"))
                break
        if (
            text != self._zoomed_screen
            or awaiting != self._zoomed_awaiting
            or choices != self._zoomed_choices
            or selected != self._zoomed_selected_index
            or kind != self._zoomed_choice_kind
        ):
            self._zoomed_screen = text
            self._zoomed_awaiting = awaiting
            self._zoomed_choices = choices
            self._zoomed_selected_index = selected
            self._zoomed_choice_kind = kind
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
        elif event == EVENT_TIMELINE:
            # 时间线新增了一段：立即刷新，否则面板会慢一拍。
            if session_id == self._active_id:
                self._refresh_timeline()
        elif event == EVENT_REVIEW:
            self._handle_review_event(session_id, payload)

    def _handle_review_event(self, session_id: str, payload: dict[str, Any]) -> None:
        """处理审查事件：维护待授权集合、提示条、系统通知与提示音。

        通知/提示音是**尽力而为**的旁路：失败只记日志，授权本身照常工作。
        """
        state = str(payload.get("state") or "")
        review = dict(payload.get("review") or {})
        if state == REVIEW_PENDING:
            self._reviews[session_id] = review
            self._notify_review(review, urgent=True)
            self._sync_review_prompt()
        elif state in (REVIEW_DENIED, REVIEW_EXPIRED, REVIEW_DISMISSED):
            self._reviews.pop(session_id, None)
            self._sync_review_prompt()
            reason = str(payload.get("reason") or "")
            if state == REVIEW_EXPIRED and reason:
                self._controller.showToast(reason, "warning")
        elif state == "notice":
            self._last_notice = review
            # "只通知"模式：照常按键，但让用户知道发生了什么。
            self._notify_review(review, urgent=False)
        self.reviewChanged.emit()

    def _notify_review(self, review: dict[str, Any], *, urgent: bool) -> None:
        """把一次审查推给系统通知与提示音（由 controller 持有 Qt 通道）。"""
        notify = getattr(self._controller, "notifyTerminalReview", None)
        if notify is None:
            return
        title = str(review.get("title") or "AI 终端")
        label = str(review.get("label") or review.get("payload") or "")
        reason = str(review.get("reason") or "")
        risk = str(review.get("riskLabel") or "")
        if urgent:
            body = f"需要授权：将自动发送 “{label}”"
        else:
            body = f"已自动应答 “{label}”"
        if reason:
            body += f"（{reason}）"
        elif risk:
            body += f"（{risk}）"
        try:
            notify(f"Codex Switch · {title}", body, urgent)
        except Exception:  # noqa: BLE001 - 通知失败不该影响审查流程
            log.exception("发送终端审查通知失败")

    def _sync_review_prompt(self) -> None:
        """把"最该展示的那一项"交给 controller 弹出授权框（一次一个）。

        多开会话时可能同时有多个待授权项，而弹窗只有一个：按会话顺序依次
        展示，先入先出。若让后来者直接覆盖，先出现的那个请求就会被无声地
        丢掉——用户永远等不到它的授权框。
        """
        pending = getattr(self._controller, "pendingTerminalReview", None)
        present = getattr(self._controller, "presentTerminalReview", None)
        clear = getattr(self._controller, "clearTerminalReview", None)
        if present is None or clear is None:
            return
        current = dict(pending() or {}) if callable(pending) else {}
        current_id = str(current.get("sessionId") or "")
        if current_id and current_id in self._reviews:
            # 已经在展示的那一项仍然有效，不要重复推送（否则每轮轮询都会重建弹窗）。
            return
        if not self._reviews:
            clear()
            return
        # 先入先出：_reviews 保持插入顺序。
        first = next(iter(self._reviews.values()))
        present(first)

    def _on_policy_changed(self) -> None:
        """把策略中只有界面层能处理的项推给 controller（提示音、抢焦点）。"""
        apply_policy = getattr(self._controller, "applyTerminalAudioPolicy", None)
        if apply_policy is None:
            return
        config = self._policy_config
        try:
            apply_policy(
                {
                    "soundEnabled": config.sound_enabled,
                    "soundStrong": config.sound_strong,
                    "soundCooldownSeconds": config.sound_cooldown_seconds,
                    "notifySystem": config.notify_system,
                    "stealFocus": config.steal_focus,
                }
            )
        except Exception:  # noqa: BLE001 - 同步失败不该影响终端
            log.exception("同步终端通知策略失败")

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
