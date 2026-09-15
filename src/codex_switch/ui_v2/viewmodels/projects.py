from __future__ import annotations

from typing import Any

from ..qt_compat import Property, Signal, Slot
from .base import SnapshotViewModel


class ProjectsViewModel(SnapshotViewModel):
    """项目工作区: project list/detail, template generation and launching."""

    selectedIdChanged = Signal()
    filterChanged = Signal()
    detailChanged = Signal()
    formChanged = Signal()

    def __init__(self, controller, parent=None) -> None:
        self._controller = controller
        self._selected_id = ""
        self._filter = ""
        self._detail: dict[str, Any] = {}
        self._form: list[dict[str, Any]] = []
        self._formTitle = ""
        super().__init__(self._build_items, parent)

    # -- properties ------------------------------------------------------
    @Property(str, notify=selectedIdChanged)
    def selectedId(self) -> str:
        return self._selected_id

    @Property(str, notify=filterChanged)
    def filterText(self) -> str:
        return self._filter

    @filterText.setter
    def filterText(self, value: str) -> None:
        self.setFilter(value)

    @Property("QVariantMap", notify=detailChanged)
    def selectedDetail(self) -> dict[str, Any]:
        return dict(self._detail)

    @Property(bool, notify=detailChanged)
    def hasSelection(self) -> bool:
        return bool(self._detail)

    @Property("QVariantList", notify=formChanged)
    def formFields(self) -> list[dict[str, Any]]:
        return list(self._form)

    @Property(str, notify=formChanged)
    def formTitle(self) -> str:
        return self._formTitle

    @Property("QVariantList", notify=detailChanged)
    def availableMcp(self) -> list[str]:
        return list(self._controller.snapshot().get("mcp_server_names") or [])

    @Property("QVariantList", notify=detailChanged)
    def availableSkillGroups(self) -> list[dict[str, Any]]:
        return list(self._controller.snapshot().get("skill_groups") or [])

    # -- building --------------------------------------------------------
    def _build_items(self) -> list[dict[str, Any]]:
        state = dict(self._controller.snapshot() or {})
        selected_id = str(state.get("selected_project_id") or "")
        if selected_id != self._selected_id:
            self._selected_id = selected_id
            self.selectedIdChanged.emit()

        needle = self._filter.casefold().strip()
        rows: list[dict[str, Any]] = []
        detail: dict[str, Any] = {}
        for project in state.get("projects") or []:
            item = dict(project)
            if needle:
                blob = " ".join(
                    str(item.get(key, "")) for key in ("name", "projectDir", "githubRepo", "runCommand")
                ).casefold()
                if needle not in blob:
                    continue
            if item.get("selected"):
                detail = dict(state.get("selected_project_detail") or item)
            rows.append(item)

        if detail != self._detail:
            self._detail = detail
            self.detailChanged.emit()
        return rows

    # -- selection / filter ----------------------------------------------
    @Slot(str)
    def select(self, project_id: str) -> None:
        self._controller.selectProject(str(project_id))

    @Slot(str)
    def setFilter(self, text: str) -> None:
        value = str(text or "")
        if value != self._filter:
            self._filter = value
            self.filterChanged.emit()
            self.refresh()

    @Slot()
    def clearFilter(self) -> None:
        self.setFilter("")

    # -- CRUD ------------------------------------------------------------
    @Slot()
    def beginCreate(self) -> None:
        self._form = self._controller.projectForm("")
        self._formTitle = "新增项目"
        self.formChanged.emit()
        self._controller.openDrawer("project-form")

    @Slot(str)
    def beginEdit(self, project_id: str) -> None:
        self._form = self._controller.projectForm(str(project_id))
        if not self._form:
            self.report_error("项目不存在或已被删除。")
            return
        self._formTitle = "编辑项目"
        self.formChanged.emit()
        self._controller.openDrawer("project-form")

    @Slot("QVariantMap")
    def submitForm(self, payload) -> None:
        self._controller.saveProjectForm(dict(payload or {}))

    @Slot(str)
    def remove(self, project_id: str) -> None:
        self._controller.deleteProject(str(project_id))

    # -- templates -------------------------------------------------------
    @Slot()
    def generateCodexTemplate(self) -> None:
        self._controller.generateCodexTemplate()

    @Slot()
    def generateClaudeTemplate(self) -> None:
        self._controller.generateClaudeTemplate()

    # -- launching -------------------------------------------------------
    @Slot()
    def openFolder(self) -> None:
        self._controller.openProjectFolder()

    @Slot()
    def openVsCode(self) -> None:
        self._controller.launchProject("vscode")

    @Slot()
    def runProject(self) -> None:
        self._controller.launchProject("run")

    @Slot()
    def openCodexCmd(self) -> None:
        self._controller.launchProject("codex-cmd")

    @Slot()
    def openClaudeCmd(self) -> None:
        self._controller.launchProject("claude-cmd")

    # -- git -------------------------------------------------------------
    @Slot()
    def syncRepo(self) -> None:
        self._controller.syncProjectRepo()

    @Slot()
    def syncBinding(self) -> None:
        self._controller.syncProjectBinding()

    @Slot(str, str)
    def setProjectBinding(self, target: str, profile_id: str) -> None:
        self._controller.setProjectBinding(str(target), str(profile_id))


__all__ = ["ProjectsViewModel"]
