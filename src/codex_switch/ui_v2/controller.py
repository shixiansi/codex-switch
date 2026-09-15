"""The single Qt/QML boundary over the headless :class:`Workspace`.

The controller owns:
* the active navigation section and drawer state,
* the background task runner and progress reporting,
* non-blocking toasts and the unified error channel,
* one view model per functional area.

All business rules live in ``workspace.py``; this module only adapts them to Qt.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from ..storage import ProfileStore
from .theme import ThemeController
from .qt_compat import Property, QObject, QTimer, Signal, Slot
from .viewmodels import (
    DashboardViewModel,
    ProfilesViewModel,
    ProjectsViewModel,
    ProxyViewModel,
    SettingsViewModel,
    ToolsViewModel,
)
from .workers import TaskContext, TaskResult, TaskRunner, TaskState
from .workspace import ActionResult, Workspace, WorkspaceError

SECTION_ORDER = ("dashboard", "profiles", "projects", "network", "system")
SECTION_TITLES = {
    "dashboard": "首页",
    "profiles": "配置中心",
    "projects": "项目工作区",
    "network": "网络与监控",
    "system": "系统",
}

TASK_REFRESH = "refresh"
TASK_HEALTH = "health"
TASK_HEALTH_ALL = "health-all"
TASK_MODEL_BATCH = "model-batch"
TASK_PROXY = "proxy"
TASK_POOL_TEST = "pool-test"
TASK_TEMPLATE = "template"
TASK_GIT_SYNC = "git-sync"
TASK_SKILL_REPO = "skill-repo"
TASK_CHAT = "chat"
TASK_UPDATE = "update-check"
TASK_SOFTWARE_UPDATE = "software-update"

PROXY_POLL_INTERVAL_MS = 2000


class AppController(QObject):
    """Exposes navigation, tasks, toasts and view models to QML."""

    currentSectionChanged = Signal()
    busyChanged = Signal()
    toastRequested = Signal(str, str, str)
    errorRaised = Signal(str)
    drawerChanged = Signal()
    confirmChanged = Signal()
    taskStateChanged = Signal()
    stateChanged = Signal()
    themeChanged = Signal()

    def __init__(self, workspace: Workspace | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.workspace = workspace or Workspace()
        self._section = "dashboard"
        self._busy = False
        self._drawer = ""
        self._active_task = ""
        self._status_text = "准备就绪"
        self._drawer_profile_id: str | None = None
        self._drawer_project_id: str | None = None
        self._drawer_pool_group_id = ""
        self._drawer_pool_channel_id = ""
        self._drawer_mcp_name = ""
        self._drawer_skill_group_id = ""
        self._drawer_skill_id = ""
        self._drawer_skill_repo_id = ""
        self._mcp_selected = ""
        self._confirm_spec: dict[str, Any] = {}
        self._confirm_action: Callable[[], None] | None = None
        self._runner = TaskRunner(self)
        self._runner.taskStarted.connect(self._on_task_started)
        self._runner.taskProgress.connect(self._on_task_progress)
        self._runner.taskFinished.connect(self._on_task_finished)
        self._runner.activeCountChanged.connect(self._on_active_count_changed)

        self.theme = ThemeController(
            self.workspace.session.dark_mode, on_change=self._persist_theme, parent=self
        )

        self.dashboard = DashboardViewModel(self, self)
        self.profiles = ProfilesViewModel(self, self)
        self.projects = ProjectsViewModel(self, self)
        self.proxy = ProxyViewModel(self, self)
        self.tools = ToolsViewModel(self, self)
        self.settings = SettingsViewModel(self, self)

        self._models = (
            self.dashboard,
            self.profiles,
            self.projects,
            self.proxy,
            self.tools,
            self.settings,
        )
        for model in self._models:
            model.errorRaised.connect(self._on_view_model_error)

        self._proxy_timer = QTimer(self)
        self._proxy_timer.setInterval(PROXY_POLL_INTERVAL_MS)
        self._proxy_timer.timeout.connect(self._poll_proxy_state)
        self._proxy_timer.start()

        self._refresh_models()
        if self.workspace.session.route_proxy.enabled:
            # Re-arm the proxy that was running when the app last exited.
            QTimer.singleShot(300, lambda: self._runner.submit(TASK_PROXY, self._start_proxy_task, label="启动路由代理"))

    # =====================================================================
    # Qt properties
    # =====================================================================
    @Property(str, notify=currentSectionChanged)
    def currentSection(self) -> str:
        return self._section

    @Property(str, notify=currentSectionChanged)
    def currentSectionTitle(self) -> str:
        return SECTION_TITLES.get(self._section, "首页")

    @Property(bool, notify=busyChanged)
    def busy(self) -> bool:
        return self._busy

    @Property(str, notify=taskStateChanged)
    def activeTask(self) -> str:
        return self._active_task

    @Property(str, notify=taskStateChanged)
    def statusText(self) -> str:
        return self._status_text

    @Property(str, notify=drawerChanged)
    def drawer(self) -> str:
        return self._drawer

    @Property(bool, notify=drawerChanged)
    def drawerOpen(self) -> bool:
        return bool(self._drawer)

    @Property(str, constant=True)
    def appTitle(self) -> str:
        return "Codex Switch"

    @Property(str, constant=True)
    def version(self) -> str:
        from .. import __version__

        return __version__

    # QObject-typed properties: `object` yields a null wrapper in QML, so the
    # concrete QObject type (or QObject itself) must be declared instead.
    @Property(ThemeController, constant=True)
    def themeController(self):
        return self.theme

    @Property(DashboardViewModel, constant=True)
    def dashboardModel(self):
        return self.dashboard

    @Property(ProfilesViewModel, constant=True)
    def profilesModel(self):
        return self.profiles

    @Property(ProjectsViewModel, constant=True)
    def projectsModel(self):
        return self.projects

    @Property(ProxyViewModel, constant=True)
    def proxyModel(self):
        return self.proxy

    @Property(ToolsViewModel, constant=True)
    def toolsModel(self):
        return self.tools

    @Property(SettingsViewModel, constant=True)
    def settingsModel(self):
        return self.settings

    @Property("QVariantList", notify=stateChanged)
    def contextInfo(self) -> list[dict[str, Any]]:
        state = self.snapshot()
        return [
            {"key": "profile", "label": "当前配置", "value": state["selected_profile_detail"].get("name") or "未选择"},
            {"key": "project", "label": "当前项目", "value": state["selected_project_detail"].get("name") or "未选择"},
        ]

    # =====================================================================
    # Destructive-action confirmation
    # =====================================================================
    # The pending action is a Python callable, not a QML closure: callables
    # passed through a JS object are not reliably invokable from QML. QML only
    # renders `pendingConfirm` and reports confirmed/cancelled back here.
    @Property("QVariantMap", notify=confirmChanged)
    def pendingConfirm(self) -> dict[str, Any]:
        return dict(self._confirm_spec)

    @Property(bool, notify=confirmChanged)
    def confirmOpen(self) -> bool:
        return bool(self._confirm_spec)

    def _request_confirm(
        self,
        *,
        title: str,
        message: str,
        action: Callable[[], None],
        detail: str = "",
        warning: str = "",
        confirm_text: str = "删除",
        danger: bool = True,
    ) -> None:
        self._confirm_action = action
        self._confirm_spec = {
            "title": str(title),
            "message": str(message),
            "detail": str(detail),
            "warning": str(warning),
            "confirmText": str(confirm_text),
            "danger": bool(danger),
        }
        self.confirmChanged.emit()

    @Slot()
    def confirmPending(self) -> None:
        """Run the pending action (called when the user confirms)."""
        action = self._confirm_action
        self._clear_confirm()
        if action is None:
            return
        self._run_sync(action)

    @Slot()
    def cancelPending(self) -> None:
        """Discard the pending action (called on cancel / dismiss)."""
        self._clear_confirm()

    def _clear_confirm(self) -> None:
        if not self._confirm_spec and self._confirm_action is None:
            return
        self._confirm_spec = {}
        self._confirm_action = None
        self.confirmChanged.emit()

    @Slot(str)
    def requestDeleteProfile(self, profile_id: str) -> None:
        """Ask before deleting a profile, explaining a blocking project binding."""
        profile_id = str(profile_id or "")
        profile = self.workspace.session.profile_by_id(profile_id)
        if profile is None:
            self.showToast("请先选择一个配置。", "warning")
            return
        self._request_confirm(
            title="删除配置",
            message=f"确定要删除配置「{profile.name}」吗？此操作无法撤销。",
            detail="删除后该配置的 API Key、模型与健康记录都会从本机移除。",
            warning=self.workspace.delete_profile_blocker(profile_id),
            action=lambda: self.workspace.delete_profile(profile_id),
        )

    @Slot(str)
    def requestDeleteProject(self, project_id: str) -> None:
        project_id = str(project_id or "")
        project = self.workspace.session.project_by_id(project_id)
        if project is None:
            self.showToast("请先选择一个项目。", "warning")
            return
        self._request_confirm(
            title="删除项目",
            message=f"确定要删除项目「{project.name}」吗？",
            detail="只会移除本工具中的项目记录，磁盘上的项目目录不会被删除。",
            action=lambda: self.workspace.delete_project(project_id),
        )

    @Slot(str)
    def requestDeletePoolChannel(self, channel_id: str) -> None:
        channel_id = str(channel_id or "")
        channel = next(
            (item for item in self.workspace.session.account_pool.channels if item.id == channel_id),
            None,
        )
        if channel is None:
            self.showToast("号池渠道不存在。", "warning")
            return
        self._request_confirm(
            title="删除号池渠道",
            message=f"确定要删除渠道「{channel.name}」吗？",
            detail=channel.base_url,
            action=lambda: self.workspace.delete_pool_channel(channel_id),
        )

    @Slot(str)
    def requestDeleteMcpServer(self, name: str) -> None:
        name = str(name or "")
        if name not in self.workspace.available_mcp_server_names():
            self.showToast("MCP 服务不存在。", "warning")
            return
        self._request_confirm(
            title="删除 MCP 服务",
            message=f"确定要删除 MCP 服务「{name}」吗？",
            detail="该项目模板中已写入的 MCP 配置需要重新生成模板才会更新。",
            action=lambda: self.workspace.delete_mcp(name),
        )

    @Slot(str)
    def requestDeleteSkillGroup(self, group_id: str) -> None:
        group_id = str(group_id or "")
        group = self.workspace.session.skill_group_by_id(group_id)
        if group is None:
            self.showToast("Skills 组不存在。", "warning")
            return
        self._request_confirm(
            title="删除 Skills 组",
            message=f"确定要删除 Skills 组「{group.name}」吗？",
            detail=f"组内 {len(group.skills)} 个 Skill，以及各项目对该组的引用都会被一并移除。",
            action=lambda: self.workspace.delete_skill_group(group_id),
        )

    @Slot(str, str)
    def requestDeleteSkill(self, group_id: str, skill_id: str) -> None:
        group_id = str(group_id or "")
        skill_id = str(skill_id or "")
        group = self.workspace.session.skill_group_by_id(group_id)
        skill = next((item for item in group.skills if item.id == skill_id), None) if group else None
        if group is None or skill is None:
            self.showToast("Skill 不存在。", "warning")
            return
        self._request_confirm(
            title="删除 Skill",
            message=f"确定要从组「{group.name}」中删除 Skill「{skill.name}」吗？",
            action=lambda: self.workspace.delete_skill(group_id, skill_id),
        )

    @Slot(str)
    def requestDeleteSkillRepo(self, repo_id: str) -> None:
        repo_id = str(repo_id or "")
        repo = self.workspace.session.skill_repo_by_id(repo_id)
        if repo is None:
            self.showToast("Skills 仓库不存在。", "warning")
            return
        self._request_confirm(
            title="删除 Skills 仓库",
            message=f"确定要删除仓库「{repo.url}」吗？",
            detail="仅移除本工具中的仓库记录，已安装到组里的 Skill 不会被删除。",
            action=lambda: self.workspace.delete_skill_repo(repo_id),
        )

    # =====================================================================
    # Navigation / drawer
    # =====================================================================
    @Slot(str)
    def navigateTo(self, section: str) -> None:
        value = str(section or "dashboard")
        if value not in SECTION_ORDER:
            value = "dashboard"
        if value != self._section:
            self._section = value
            self.currentSectionChanged.emit()

    @Slot()
    def openCommandPalette(self) -> None:
        self.showToast("使用左侧导航或按 Ctrl+1…5 快速切换区域。", "info")

    @Slot(str)
    def openDrawer(self, name: str) -> None:
        value = str(name or "")
        if value == self._drawer:
            return
        self._drawer = value
        self.drawerChanged.emit()

    @Slot()
    def closeDrawer(self) -> None:
        if self._drawer:
            self._drawer = ""
            self.drawerChanged.emit()

    # =====================================================================
    # Toasts / errors
    # =====================================================================
    @Slot(str, str)
    def showToast(self, message: str, level: str = "info") -> None:
        self.toastRequested.emit(str(message), str(level or "info"), "")

    def _toast(self, message: str, level: str = "info", detail: str = "") -> None:
        text = str(message or "").strip()
        if not text:
            return
        self.toastRequested.emit(text, str(level or "info"), str(detail or ""))

    def _on_view_model_error(self, message: str) -> None:
        self.errorRaised.emit(str(message))

    def _report_action(self, result: ActionResult) -> None:
        self._status_text = result.message or self._status_text
        self.taskStateChanged.emit()
        self._toast(result.message, result.level, result.detail)

    # =====================================================================
    # Snapshot
    # =====================================================================
    @property
    def session(self):
        """Python-level accessor for view models (not exposed to QML)."""
        return self.workspace.session

    def snapshot(self) -> dict[str, Any]:
        # The MCP selection lives here (it is pure UI state), so it must be
        # forwarded for the detail panel to follow the clicked row.
        return self.workspace.snapshot(selected_mcp_name=self._mcp_selected)

    def _refresh_models(self) -> None:
        for model in self._models:
            model.rebuild()
        self.stateChanged.emit()

    # =====================================================================
    # Task plumbing
    # =====================================================================
    def _submit(self, task_id: str, body: Callable[[TaskContext], Any], *, label: str = "") -> bool:
        return self._runner.submit(task_id, body, label=label or task_id)

    @Slot()
    def refreshAll(self) -> None:
        if not self._submit(TASK_REFRESH, self._refresh_task, label="刷新状态"):
            self.showToast("刷新已在进行中。", "info")

    def _refresh_task(self, context: TaskContext) -> str:
        context.report(None, "正在读取本地状态 …")
        result = self.workspace.reload()
        return result.message

    def _on_task_started(self, task_id: str, label: str) -> None:
        self._active_task = label or task_id
        self._status_text = f"{self._active_task} …"
        self.taskStateChanged.emit()

    def _on_task_progress(self, task_id: str, progress: object, detail: str) -> None:
        if detail:
            self._status_text = str(detail)
            self.taskStateChanged.emit()

    def _on_active_count_changed(self) -> None:
        busy = self._runner.active_count > 0
        if busy != self._busy:
            self._busy = busy
            self.busyChanged.emit()

    def _on_task_finished(self, task_id: str, result: TaskResult) -> None:
        self._active_task = ""
        if result.state is TaskState.CANCELLED:
            self._status_text = "任务已取消。"
            self.taskStateChanged.emit()
            self._toast("任务已取消。", "info")
            self._refresh_models()
            return

        if result.state is TaskState.FAILED:
            self._status_text = "操作失败。"
            self.taskStateChanged.emit()
            self.errorRaised.emit(result.error or "操作失败。")
            self._toast(result.error or "操作失败。", "error")
            return

        value = result.value
        if isinstance(value, ActionResult):
            self._status_text = value.message or "完成。"
            self.taskStateChanged.emit()
            self._toast(value.message, value.level, value.detail)
        elif isinstance(value, str) and value:
            self._status_text = value
            self.taskStateChanged.emit()
            self._toast(value, "success")

        if result.detail:
            self._status_text = result.detail
            self.taskStateChanged.emit()
        self._refresh_models()

    # -- background task bodies ------------------------------------------
    def _start_proxy_task(self, context: TaskContext) -> ActionResult:
        return self.workspace.start_proxy()

    def _poll_proxy_state(self) -> None:
        """Persist proxy-side changes without blocking the UI thread."""
        if not self.workspace.flush_proxy_state():
            return
        self._refresh_models()

    # =====================================================================
    # Profiles
    # =====================================================================
    def profileForm(self, profile_id: str) -> list[dict[str, Any]]:
        try:
            return self.workspace.profile_form_fields(str(profile_id))
        except WorkspaceError as exc:
            self.errorRaised.emit(str(exc))
            return []

    def selectProfile(self, profile_id: str) -> None:
        self.workspace.select_profile(str(profile_id))
        self._refresh_models()

    @Slot("QVariantMap")
    def saveProfileForm(self, payload) -> None:
        pending = dict(payload or {})
        # The drawer remembers which record it edits through setDrawerTarget.
        profile_id = self._drawer_profile_id or ""
        self._run_action(
            "save-profile",
            lambda context: self.workspace.save_profile(pending, profile_id=profile_id),
            label="保存配置",
        )

    @Slot(str)
    def deleteProfile(self, profile_id: str) -> None:
        self._run_action(
            f"delete-profile:{profile_id}",
            lambda context: self.workspace.delete_profile(str(profile_id)),
            label="删除配置",
        )

    @Slot(str, result=str)
    def profileDeleteBlocker(self, profile_id: str) -> str:
        """Why a profile cannot be deleted ('' when it can).

        Called by the confirmation dialog so a blocked delete is explained
        before the user commits to it.
        """
        return self.workspace.delete_profile_blocker(str(profile_id))

    @Slot()
    def applySelectedProfile(self) -> None:
        self._run_action("apply-profile", lambda context: self.workspace.apply_selected_profile(), label="切换配置")

    @Slot(str)
    def applyProfile(self, profile_id: str) -> None:
        self._run_action(
            f"apply-profile:{profile_id}",
            lambda context: self.workspace.apply_profile(str(profile_id)),
            label="切换配置",
        )

    @Slot()
    def applyGlobalProfiles(self) -> None:
        self._run_action("apply-globals", lambda context: self.workspace.apply_global_profiles(), label="写入全局配置")

    @Slot(str, str)
    def setGlobalProfileChoice(self, target: str, profile_id: str) -> None:
        self._run_sync(lambda: self.workspace.set_global_profile_choice(str(target), str(profile_id)))

    @Slot(str)
    def openSignInUrl(self, profile_id: str) -> None:
        self._run_sync(lambda: self.workspace.open_sign_in_url(str(profile_id)))

    @Slot(str)
    def markSignedIn(self, profile_id: str) -> None:
        self._run_sync(lambda: self.workspace.mark_signed_in(str(profile_id)))

    @Slot()
    def signInAll(self) -> None:
        """One-click sign-in for every pending profile.

        Opening browser tabs is fast (no network is awaited), so this runs on
        the UI thread and reports a single aggregated toast.
        """
        self._run_sync(self.workspace.open_all_sign_in_urls)

    # =====================================================================
    # Health
    # =====================================================================
    @Slot(str)
    def runHealthCheck(self, profile_id: str = "") -> None:
        target = str(profile_id or "")
        if not target:
            self.showToast("请先选择一个配置。", "warning")
            return
        self._run_action(
            f"{TASK_HEALTH}:{target}",
            lambda context: self.workspace.run_health_check(
                target, progress=lambda text: context.report(None, text)
            ).summary,
            label="健康检测",
        )

    @Slot()
    def runHealthCheckAll(self) -> None:
        self._run_action(
            TASK_HEALTH_ALL,
            lambda context: self.workspace.run_health_check_all(
                progress=lambda text: context.report(None, text)
            ).summary,
            label="批量健康检测",
        )

    # =====================================================================
    # Projects
    # =====================================================================
    def projectForm(self, project_id: str) -> list[dict[str, Any]]:
        try:
            return self.workspace.project_form_fields(str(project_id))
        except WorkspaceError as exc:
            self.errorRaised.emit(str(exc))
            return []

    def selectProject(self, project_id: str) -> None:
        self.workspace.select_project(str(project_id))
        self._refresh_models()

    @Slot("QVariantMap")
    def saveProjectForm(self, payload) -> None:
        pending = dict(payload or {})
        project_id = self._drawer_project_id or ""
        self._run_action(
            "save-project",
            lambda context: self.workspace.save_project(pending, project_id=project_id),
            label="保存项目",
        )

    @Slot(str)
    def deleteProject(self, project_id: str) -> None:
        self._run_action(
            f"delete-project:{project_id}",
            lambda context: self.workspace.delete_project(str(project_id)),
            label="删除项目",
        )

    @Slot()
    def generateCodexTemplate(self) -> None:
        self._run_action(
            f"{TASK_TEMPLATE}:codex",
            lambda context: self.workspace.generate_template(client="codex"),
            label="生成 Codex 模板",
        )

    @Slot()
    def generateClaudeTemplate(self) -> None:
        self._run_action(
            f"{TASK_TEMPLATE}:claude",
            lambda context: self.workspace.generate_template(client="claude"),
            label="生成 Claude 模板",
        )

    @Slot()
    def openProjectFolder(self) -> None:
        self._run_sync(lambda: self.workspace.open_project_folder())

    @Slot(str)
    def launchProject(self, action: str) -> None:
        self._run_sync(lambda: self.workspace.launch_project(str(action)))

    @Slot()
    def syncProjectRepo(self) -> None:
        self._run_action(
            f"{TASK_GIT_SYNC}:project",
            lambda context: self.workspace.sync_project_repo(),
            label="同步项目仓库",
        )

    @Slot()
    def syncProjectBinding(self) -> None:
        self._run_action(
            f"{TASK_GIT_SYNC}:binding",
            lambda context: self.workspace.sync_project_binding(),
            label="同步项目绑定",
        )

    @Slot(str, str)
    def setProjectBinding(self, target: str, profile_id: str) -> None:
        self._run_sync(lambda: self.workspace.set_project_binding(str(target), str(profile_id)))

    # =====================================================================
    # Route proxy
    # =====================================================================
    @Slot()
    def startProxy(self) -> None:
        self._run_action(TASK_PROXY, self._start_proxy_task, label="启动路由代理")

    @Slot()
    def stopProxy(self) -> None:
        self._run_sync(lambda: self.workspace.stop_proxy())

    @Slot()
    def toggleProxy(self) -> None:
        if self.workspace.proxy_running:
            self.stopProxy()
        else:
            self.startProxy()

    @Slot("QVariantMap")
    def saveProxySettingsForm(self, payload) -> None:
        data = dict(payload or {})
        self._run_sync(lambda: self.workspace.save_proxy_settings(data))

    @Slot(bool, str)
    def setProjectProxyEnabled(self, enabled: bool, project_id: str = "") -> None:
        self._run_sync(lambda: self.workspace.set_project_proxy_enabled(bool(enabled), str(project_id)))

    @Slot()
    def enableProxyForProject(self) -> None:
        self.setProjectProxyEnabled(True)

    @Slot()
    def disableProxyForProject(self) -> None:
        self.setProjectProxyEnabled(False)

    @Slot()
    def refreshProxyStatus(self) -> None:
        self.workspace.flush_proxy_state()
        self._refresh_models()

    @Slot()
    def clearEvents(self) -> None:
        self._run_sync(lambda: self.workspace.clear_events())

    # =====================================================================
    # Tools: model test / chat / pool / mcp / skills
    # =====================================================================
    @Slot()
    def runModelBatch(self) -> None:
        profile_id = self.workspace.session.selected_profile_id or ""
        if not profile_id:
            self.showToast("请先选择一个配置。", "warning")
            return

        def body(context: TaskContext) -> ActionResult:
            def progress(model: str, status: str, detail: str, duration_ms: int) -> None:
                label = "成功" if status == "success" else "失败"
                context.report(None, f"{model}：{label}")

            return self.workspace.run_model_batch(
                profile_id=profile_id,
                progress=progress,
                should_cancel=lambda: context.cancelled,
            )

        self._run_action(TASK_MODEL_BATCH, body, label="模型测试")

    @Slot()
    def cancelModelBatch(self) -> None:
        if self._runner.cancel(TASK_MODEL_BATCH):
            self.showToast("已请求取消模型测试。", "info")

    @Slot(str, str, str)
    def sendChat(self, prompt: str, model: str = "", wire_api: str = "") -> None:
        self._run_action(
            TASK_CHAT,
            lambda context: self.workspace.send_chat(str(prompt), str(model), str(wire_api)),
            label="聊天测试",
        )

    @Slot()
    def clearChat(self) -> None:
        self._run_sync(lambda: self.workspace.clear_chat())

    def poolGroupForm(self, group_id: str) -> list[dict[str, Any]]:
        try:
            return self.workspace.pool_group_form_fields(str(group_id))
        except WorkspaceError as exc:
            self.errorRaised.emit(str(exc))
            return []

    def poolChannelForm(self, group_id: str, channel_id: str = "") -> list[dict[str, Any]]:
        try:
            return self.workspace.pool_channel_form_fields(str(channel_id))
        except WorkspaceError as exc:
            self.errorRaised.emit(str(exc))
            return []

    def mcpForm(self, name: str) -> list[dict[str, Any]]:
        try:
            return self.workspace.mcp_form_fields(str(name))
        except WorkspaceError as exc:
            self.errorRaised.emit(str(exc))
            return []

    def skillGroupForm(self, group_id: str) -> list[dict[str, Any]]:
        try:
            return self.workspace.skill_group_form_fields(str(group_id))
        except WorkspaceError as exc:
            self.errorRaised.emit(str(exc))
            return []

    def skillForm(self, group_id: str, skill_id: str = "") -> list[dict[str, Any]]:
        try:
            return self.workspace.skill_form_fields(str(group_id), str(skill_id))
        except WorkspaceError as exc:
            self.errorRaised.emit(str(exc))
            return []

    def skillRepoForm(self, repo_id: str) -> list[dict[str, Any]]:
        try:
            return self.workspace.skill_repo_form_fields(str(repo_id))
        except WorkspaceError as exc:
            self.errorRaised.emit(str(exc))
            return []

    @Slot(str)
    def selectPoolGroup(self, group_id: str) -> None:
        self._run_sync(lambda: self.workspace.select_pool_group(str(group_id)))

    @Slot("QVariantMap")
    def savePoolGroupForm(self, payload) -> None:
        data = dict(payload or {})
        group_id = self._drawer_pool_group_id or ""
        self._run_sync(lambda: self.workspace.save_pool_group(data, group_id=group_id))

    @Slot(str)
    def deletePoolGroup(self, group_id: str) -> None:
        self._run_sync(lambda: self.workspace.delete_pool_group(str(group_id)))

    @Slot("QVariantMap")
    def savePoolChannelForm(self, payload) -> None:
        data = dict(payload or {})
        channel_id = self._drawer_pool_channel_id or ""
        self._run_sync(lambda: self.workspace.save_pool_channel(data, channel_id=channel_id))

    @Slot(str)
    def deletePoolChannel(self, channel_id: str) -> None:
        self._run_sync(lambda: self.workspace.delete_pool_channel(str(channel_id)))

    @Slot(str)
    def testPoolChannel(self, channel_id: str) -> None:
        self._run_action(
            f"{TASK_POOL_TEST}:{channel_id}",
            lambda context: self.workspace.test_pool_channel(str(channel_id)),
            label="渠道检测",
        )

    @Slot()
    def testAllPoolChannels(self) -> None:
        self._run_action(
            TASK_POOL_TEST,
            lambda context: self.workspace.test_all_pool_channels(
                progress=lambda text: context.report(None, text)
            ),
            label="号池检测",
        )

    @Slot(str)
    def selectMcpServer(self, name: str) -> None:
        self._mcp_selected = str(name)
        self._refresh_models()

    @Slot("QVariantMap")
    def saveMcpForm(self, payload) -> None:
        data = dict(payload or {})
        current = self._drawer_mcp_name or ""
        self._run_sync(lambda: self.workspace.save_mcp(data, current_name=current))

    @Slot(str)
    def deleteMcpServer(self, name: str) -> None:
        self._run_sync(lambda: self.workspace.delete_mcp(str(name)))

    @Slot()
    def restoreDefaultMcp(self) -> None:
        self._run_sync(lambda: self.workspace.restore_default_mcp())

    @Slot("QVariantMap")
    def saveSkillGroupForm(self, payload) -> None:
        data = dict(payload or {})
        group_id = self._drawer_skill_group_id or ""
        self._run_sync(lambda: self.workspace.save_skill_group(data, group_id=group_id))

    @Slot(str)
    def deleteSkillGroup(self, group_id: str) -> None:
        self._run_sync(lambda: self.workspace.delete_skill_group(str(group_id)))

    @Slot("QVariantMap")
    def saveSkillForm(self, payload) -> None:
        data = dict(payload or {})
        group_id = self._drawer_skill_group_id or ""
        skill_id = self._drawer_skill_id or ""
        self._run_sync(lambda: self.workspace.save_skill(data, group_id=group_id, skill_id=skill_id))

    @Slot(str, str)
    def deleteSkill(self, group_id: str, skill_id: str) -> None:
        self._run_sync(lambda: self.workspace.delete_skill(str(group_id), str(skill_id)))

    @Slot("QVariantMap")
    def saveSkillRepoForm(self, payload) -> None:
        data = dict(payload or {})
        repo_id = self._drawer_skill_repo_id or ""
        self._run_sync(lambda: self.workspace.save_skill_repo(data, repo_id=repo_id))

    @Slot(str)
    def deleteSkillRepo(self, repo_id: str) -> None:
        self._run_sync(lambda: self.workspace.delete_skill_repo(str(repo_id)))

    @Slot(str)
    def installSkillRepo(self, repo_id: str) -> None:
        self._run_action(
            f"{TASK_SKILL_REPO}:{repo_id}",
            lambda context: self.workspace.install_skill_repo(str(repo_id)),
            label="安装 Skills 仓库",
        )

    # =====================================================================
    # Settings
    # =====================================================================
    @Slot(bool)
    def setDarkMode(self, value: bool) -> None:
        self.theme.setDarkMode(bool(value))
        self._refresh_models()

    def _persist_theme(self, _dark_mode: bool) -> None:
        self.workspace.session.dark_mode = self.theme.darkMode
        self.workspace.persist()
        self.themeChanged.emit()

    @Slot("QVariantMap")
    def saveGeneralSettings(self, payload) -> None:
        data = dict(payload or {})
        self._run_sync(lambda: self.workspace.save_general_settings(data))

    @Slot(str)
    def saveAgentsDoc(self, text: str) -> None:
        value = str(text)
        self._run_sync(lambda: self.workspace.save_agents_doc(value))

    @Slot()
    def restoreAgentsDoc(self) -> None:
        self._run_sync(lambda: self.workspace.restore_agents_doc())

    @Slot()
    def checkHotUpdates(self) -> None:
        self._run_action(TASK_UPDATE, lambda context: self.workspace.check_hot_updates(), label="检查仓库更新")

    @Slot()
    def checkSoftwareUpdate(self) -> None:
        self._run_action(
            TASK_SOFTWARE_UPDATE,
            lambda context: self.workspace.check_software_update(),
            label="检查软件更新",
        )

    @Slot(str)
    def openLocalPath(self, path: str) -> None:
        self._run_sync(lambda: self.workspace.open_local_path(str(path)))

    # =====================================================================
    # Drawer-scoped record ids
    # =====================================================================
    @Slot(str, str)
    def setDrawerTarget(self, kind: str, record_id: str) -> None:
        """Remember which record a drawer edits before it opens."""
        value = str(record_id or "")
        if kind == "profile-form":
            self._drawer_profile_id = value or None
        elif kind == "project-form":
            self._drawer_project_id = value or None
        elif kind == "pool-group-form":
            self._drawer_pool_group_id = value
        elif kind == "pool-channel-form":
            self._drawer_pool_channel_id = value
        elif kind == "mcp-form":
            self._drawer_mcp_name = value
        elif kind == "skill-group-form":
            self._drawer_skill_group_id = value
        elif kind == "skill-form":
            group_id, _, skill_id = value.partition("|")
            self._drawer_skill_group_id = group_id
            self._drawer_skill_id = skill_id
        elif kind == "skill-repo-form":
            self._drawer_skill_repo_id = value

    # =====================================================================
    # Helpers
    # =====================================================================
    def _run_sync(self, action: Callable[[], ActionResult]) -> None:
        """Run a fast, local operation on the UI thread."""
        try:
            result = action()
        except WorkspaceError as exc:
            self.errorRaised.emit(str(exc))
            self._toast(str(exc), "error")
            return
        except Exception as exc:  # noqa: BLE001
            self.errorRaised.emit(f"操作失败：{exc}")
            self._toast(f"操作失败：{exc}", "error")
            return
        self._refresh_models()
        self._report_action(result)

    def _run_action(self, task_id: str, body: Callable[[TaskContext], Any], *, label: str = "") -> None:
        """Run a slow operation on the thread pool."""
        if not self._submit(task_id, body, label=label):
            self.showToast("该操作已在进行中。", "info")

    @Slot()
    def shutdown(self) -> None:
        """Stop background work and the proxy before the window closes."""
        self._proxy_timer.stop()
        self._runner.cancel_all()
        try:
            if self.workspace.proxy_running:
                self.workspace.stop_proxy()
        except Exception:  # noqa: BLE001 - never block shutdown
            pass


__all__ = ["AppController", "SECTION_ORDER", "SECTION_TITLES"]
