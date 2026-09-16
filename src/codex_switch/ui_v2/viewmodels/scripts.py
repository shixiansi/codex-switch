from __future__ import annotations

from typing import Any

from ..qt_compat import Property, Signal, Slot
from .base import SnapshotViewModel


class ScriptsViewModel(SnapshotViewModel):
    """脚本中心: script list/detail, editing and launching."""

    selectedIdChanged = Signal()
    detailChanged = Signal()
    formChanged = Signal()

    def __init__(self, controller, parent=None) -> None:
        self._controller = controller
        self._selected_id = ""
        self._detail: dict[str, Any] = {}
        self._form: list[dict[str, Any]] = []
        self._formTitle = ""
        super().__init__(self._build_items, parent)

    # -- properties ------------------------------------------------------
    @Property(str, notify=selectedIdChanged)
    def selectedId(self) -> str:
        return self._selected_id

    @Property("QVariantMap", notify=detailChanged)
    def selectedDetail(self) -> dict[str, Any]:
        return dict(self._detail)

    @Property("QVariantList", notify=formChanged)
    def form(self) -> list[dict[str, Any]]:
        return list(self._form)

    @Property(str, notify=formChanged)
    def formTitle(self) -> str:
        return self._formTitle

    # -- data ------------------------------------------------------------
    def _build_items(self) -> list[dict[str, Any]]:
        return self._controller.script_rows()

    @Slot()
    def refresh(self) -> None:
        super().refresh()
        self._build_detail()

    def rebuild(self) -> None:
        super().rebuild()
        self._build_detail()

    def _build_detail(self) -> None:
        detail = self._controller.script_detail(self._selected_id)
        if detail != self._detail:
            self._detail = detail
            self.detailChanged.emit()

    # -- actions ---------------------------------------------------------
    @Slot(str)
    def select(self, script_id: str) -> None:
        value = str(script_id or "")
        if value == self._selected_id:
            return
        self._selected_id = value
        self.selectedIdChanged.emit()
        self._build_detail()

    @Slot()
    def beginCreate(self) -> None:
        self._form = self._controller.scriptForm("")
        self._formTitle = "新增脚本"
        self.formChanged.emit()
        self._controller.openDrawer("script-form")

    @Slot(str)
    def beginEdit(self, script_id: str) -> None:
        self._form = self._controller.scriptForm(str(script_id))
        if not self._form:
            self.report_error("脚本不存在或已被删除。")
            return
        self._formTitle = "编辑脚本"
        self.formChanged.emit()
        self._controller.openDrawerWithTarget("script-form", str(script_id))

    @Slot("QVariantMap")
    def submitForm(self, payload) -> None:
        self._controller.saveScriptForm(dict(payload or {}))

    @Slot(str)
    def remove(self, script_id: str) -> None:
        self._controller.deleteScript(str(script_id))

    @Slot(str)
    def run(self, script_id: str) -> None:
        self._controller.runScript(str(script_id))
