"""插件中心视图模型。

只负责把注册表状态渲染成行、并把用户操作转成对宿主的调用；
真正的扫描/加载/卸载在 ``codex_switch.plugins`` 里，视图模型不碰文件系统。
"""

from __future__ import annotations

from typing import Any

from ..qt_compat import Property, Signal, Slot
from .base import SnapshotViewModel


class PluginsViewModel(SnapshotViewModel):
    """插件中心: installed plugins, permissions, enable/disable."""

    selectedIdChanged = Signal()
    detailChanged = Signal()

    def __init__(self, controller, parent=None) -> None:
        self._controller = controller
        self._selected_id = ""
        self._detail: dict[str, Any] = {}
        super().__init__(self._build_items, parent)

    # -- properties ------------------------------------------------------
    @Property(str, notify=detailChanged)
    def selectedId(self) -> str:
        return self._selected_id

    @Property("QVariantMap", notify=detailChanged)
    def selectedDetail(self) -> dict[str, Any]:
        return dict(self._detail)

    @Property(str, notify=detailChanged)
    def pluginRoot(self) -> str:
        return str(self._controller.plugin_root())

    @Property(int, notify=SnapshotViewModel.itemsChanged)
    def issueCount(self) -> int:
        return len(self._controller.plugin_issue_rows())

    @Property("QVariantList", notify=SnapshotViewModel.itemsChanged)
    def issues(self) -> list[dict[str, Any]]:
        return self._controller.plugin_issue_rows()

    # -- data ------------------------------------------------------------
    def _build_items(self) -> list[dict[str, Any]]:
        return self._controller.plugin_rows()

    @Slot()
    def refresh(self) -> None:
        super().refresh()
        self._build_detail()

    def rebuild(self) -> None:
        super().rebuild()
        self._build_detail()

    def _build_detail(self) -> None:
        detail = self._controller.plugin_detail(self._selected_id)
        if detail != self._detail:
            self._detail = detail
            self.detailChanged.emit()

    # -- actions ---------------------------------------------------------
    @Slot(str)
    def select(self, plugin_id: str) -> None:
        value = str(plugin_id or "")
        if value == self._selected_id:
            return
        self._selected_id = value
        self.selectedIdChanged.emit()
        self._build_detail()

    @Slot()
    def rescan(self) -> None:
        """重新扫描插件目录。用户往目录里放了新插件后点这个。"""
        self._controller.rescanPlugins()

    @Slot(str, bool)
    def setEnabled(self, plugin_id: str, enabled: bool) -> None:
        self._controller.setPluginEnabled(str(plugin_id), bool(enabled))

    @Slot(str)
    def openFolder(self) -> None:
        """打开插件目录，方便用户手动放入插件。"""
        self._controller.openPluginFolder()

    @Slot(str)
    def runAction(self, plugin_id: str, action_key: str) -> None:
        self._controller.runPluginAction(str(plugin_id), str(action_key))


__all__ = ["PluginsViewModel"]
