from __future__ import annotations

from typing import Any

from ..qt_compat import Property, Signal, Slot
from .base import SnapshotViewModel


class ProfilesViewModel(SnapshotViewModel):
    """配置库: list, filter, detail and profile CRUD / apply actions."""

    selectedIdChanged = Signal()
    filterChanged = Signal()
    detailChanged = Signal()
    formChanged = Signal()
    globalTargetsChanged = Signal()
    signInChanged = Signal()

    def __init__(self, controller, parent=None) -> None:
        self._controller = controller
        self._selected_id = ""
        self._filter = ""
        self._detail: dict[str, Any] = {}
        self._form: list[dict[str, Any]] = []
        self._formTitle = ""
        self._codex_choices: list[dict[str, Any]] = []
        self._claude_choices: list[dict[str, Any]] = []
        self._global_codex_id = ""
        self._global_claude_id = ""
        self._sign_in: dict[str, Any] = {}
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

    @Property("QVariantList", notify=formChanged)
    def formFields(self) -> list[dict[str, Any]]:
        return list(self._form)

    @Property(str, notify=formChanged)
    def formTitle(self) -> str:
        return self._formTitle

    @Property(bool, notify=detailChanged)
    def hasSelection(self) -> bool:
        return bool(self._detail)

    @Property("QVariantList", notify=globalTargetsChanged)
    def codexChoices(self) -> list[dict[str, Any]]:
        return [{"value": "", "label": "未选择"}] + [
            {"value": item["id"], "label": item["name"]} for item in self._codex_choices
        ]

    @Property("QVariantList", notify=globalTargetsChanged)
    def claudeChoices(self) -> list[dict[str, Any]]:
        return [{"value": "", "label": "未选择"}] + [
            {"value": item["id"], "label": item["name"]} for item in self._claude_choices
        ]

    @Property(str, notify=globalTargetsChanged)
    def globalCodexId(self) -> str:
        return self._global_codex_id

    @Property(str, notify=globalTargetsChanged)
    def globalClaudeId(self) -> str:
        return self._global_claude_id

    @Property("QVariantMap", notify=signInChanged)
    def signIn(self) -> dict[str, Any]:
        return dict(self._sign_in)

    @Property(bool, notify=signInChanged)
    def hasPendingSignIn(self) -> bool:
        return int(self._sign_in.get("pending") or 0) > 0

    # -- building --------------------------------------------------------
    def _build_items(self) -> list[dict[str, Any]]:
        state = dict(self._controller.snapshot() or {})
        selected_id = str(state.get("selected_profile_id") or "")
        if selected_id != self._selected_id:
            self._selected_id = selected_id
            self.selectedIdChanged.emit()

        needle = self._filter.casefold().strip()
        rows: list[dict[str, Any]] = []
        detail: dict[str, Any] = {}
        for profile in state.get("profiles") or []:
            item = dict(profile)
            if needle:
                blob = " ".join(
                    str(item.get(key, ""))
                    for key in ("name", "vendorLabel", "model", "codexModel", "claudeModel", "baseUrl", "notes")
                ).casefold()
                if needle not in blob:
                    continue
            if item.get("selected"):
                detail = dict(state.get("selected_profile_detail") or item)
            rows.append(item)

        if detail != self._detail:
            self._detail = detail
            self.detailChanged.emit()

        codex_choices = list(state.get("codex_choices") or [])
        claude_choices = list(state.get("claude_choices") or [])
        global_codex = str(state.get("global_codex_profile_id") or "")
        global_claude = str(state.get("global_claude_profile_id") or "")
        if (codex_choices, claude_choices, global_codex, global_claude) != (
            self._codex_choices,
            self._claude_choices,
            self._global_codex_id,
            self._global_claude_id,
        ):
            self._codex_choices = codex_choices
            self._claude_choices = claude_choices
            self._global_codex_id = global_codex
            self._global_claude_id = global_claude
            self.globalTargetsChanged.emit()

        sign_in = dict(state.get("sign_in") or {})
        if sign_in != self._sign_in:
            self._sign_in = sign_in
            self.signInChanged.emit()

        return rows

    # -- actions ---------------------------------------------------------
    @Slot(str)
    def select(self, profile_id: str) -> None:
        self._controller.selectProfile(str(profile_id))

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

    @Slot()
    def beginCreate(self) -> None:
        self._form = self._controller.profileForm("")
        self._formTitle = "新增配置"
        self.formChanged.emit()
        self._controller.openDrawer("profile-form")

    @Slot(str)
    def beginEdit(self, profile_id: str) -> None:
        self._form = self._controller.profileForm(str(profile_id))
        if not self._form:
            self.report_error("配置不存在或已被删除。")
            return
        self._formTitle = "编辑配置"
        self.formChanged.emit()
        self._controller.openDrawer("profile-form")

    @Slot("QVariantMap")
    def submitForm(self, payload) -> None:
        self._controller.saveProfileForm(dict(payload or {}))

    @Slot(str)
    def remove(self, profile_id: str) -> None:
        self._controller.deleteProfile(str(profile_id))

    @Slot()
    def applySelected(self) -> None:
        self._controller.applySelectedProfile()

    @Slot(str)
    def applyProfile(self, profile_id: str) -> None:
        self._controller.applyProfile(str(profile_id))

    @Slot()
    def applyGlobals(self) -> None:
        self._controller.applyGlobalProfiles()

    @Slot(str, str)
    def setGlobalChoice(self, target: str, profile_id: str) -> None:
        self._controller.setGlobalProfileChoice(str(target), str(profile_id))

    @Slot(str)
    def runHealthCheck(self, profile_id: str) -> None:
        self._controller.runHealthCheck(str(profile_id))

    @Slot()
    def runHealthCheckAll(self) -> None:
        self._controller.runHealthCheckAll()

    @Slot()
    def runHealthCheckSelected(self) -> None:
        self._controller.runHealthCheck(self._selected_id)

    @Slot(str)
    def openSignIn(self, profile_id: str) -> None:
        self._controller.openSignInUrl(str(profile_id))

    @Slot(str)
    def markSignedIn(self, profile_id: str) -> None:
        self._controller.markSignedIn(str(profile_id))

    @Slot()
    def signInAll(self) -> None:
        """Open every pending sign-in page and mark those profiles as signed."""
        self._controller.signInAll()


__all__ = ["ProfilesViewModel"]
