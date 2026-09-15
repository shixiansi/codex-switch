from __future__ import annotations

from typing import Any

from ..qt_compat import Property, Signal, Slot
from .base import SnapshotViewModel


class SettingsViewModel(SnapshotViewModel):
    """系统: theme, documents template, updates and environment info."""

    summaryChanged = Signal()
    docsChanged = Signal()
    updateStateChanged = Signal()

    def __init__(self, controller, parent=None) -> None:
        self._controller = controller
        self._summary: dict[str, Any] = {}
        self._docs = ""
        self._updateState: dict[str, Any] = {}
        super().__init__(self._build_items, parent)

    # -- properties ------------------------------------------------------
    @Property("QVariantMap", notify=summaryChanged)
    def summary(self) -> dict[str, Any]:
        return dict(self._summary)

    @Property(str, notify=docsChanged)
    def agentsDocText(self) -> str:
        return self._docs

    @Property("QVariantMap", notify=updateStateChanged)
    def updateState(self) -> dict[str, Any]:
        return dict(self._updateState)

    @Property(bool, notify=summaryChanged)
    def darkMode(self) -> bool:
        return bool(self._summary.get("darkMode"))

    # -- building --------------------------------------------------------
    def _build_items(self) -> list[dict[str, Any]]:
        state = dict(self._controller.snapshot() or {})
        summary = dict(state.get("settings") or {})
        if summary != self._summary:
            self._summary = summary
            self.summaryChanged.emit()

        docs = str(summary.get("agentsDocText") or "")
        if docs != self._docs:
            self._docs = docs
            self.docsChanged.emit()

        update_state = dict(state.get("software_update") or {})
        if update_state != self._updateState:
            self._updateState = update_state
            self.updateStateChanged.emit()

        return [
            {"key": "theme", "label": "主题", "value": summary.get("themeLabel", "浅色"), "tone": "accent"},
            {
                "key": "hot-update",
                "label": "仓库自动同步",
                "value": "已开启" if summary.get("hotUpdateEnabled") else "未开启",
                "tone": "success" if summary.get("hotUpdateEnabled") else "warning",
            },
            {
                "key": "interval",
                "label": "同步间隔",
                "value": f"{summary.get('hotUpdateIntervalMinutes', 30)} 分钟",
                "tone": "info",
            },
            {
                "key": "concurrency",
                "label": "模型测试并发",
                "value": str(summary.get("modelBatchConcurrency", 3)),
                "tone": "info",
            },
            {"key": "profiles", "label": "配置数量", "value": str(summary.get("profileCount", 0)), "tone": "info"},
            {"key": "projects", "label": "项目数量", "value": str(summary.get("projectCount", 0)), "tone": "info"},
            {"key": "storage", "label": "数据目录", "value": summary.get("storagePath", ""), "tone": "unknown"},
            {"key": "version", "label": "版本", "value": summary.get("version", ""), "tone": "unknown"},
        ]

    # -- actions ---------------------------------------------------------
    @Slot()
    def toggleTheme(self) -> None:
        self._controller.setDarkMode(not self.darkMode)

    @Slot(bool)
    def setDarkMode(self, value: bool) -> None:
        self._controller.setDarkMode(bool(value))

    @Slot("QVariantMap")
    def saveGeneral(self, payload) -> None:
        self._controller.saveGeneralSettings(dict(payload or {}))

    @Slot(str)
    def saveAgentsDoc(self, text: str) -> None:
        self._controller.saveAgentsDoc(str(text))

    @Slot()
    def restoreAgentsDoc(self) -> None:
        self._controller.restoreAgentsDoc()

    @Slot()
    def checkHotUpdates(self) -> None:
        self._controller.checkHotUpdates()

    @Slot()
    def checkSoftwareUpdate(self) -> None:
        self._controller.checkSoftwareUpdate()

    @Slot(str)
    def openPath(self, path: str) -> None:
        self._controller.openLocalPath(str(path))


__all__ = ["SettingsViewModel"]
