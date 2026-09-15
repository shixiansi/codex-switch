from __future__ import annotations

from typing import Any

from ..qt_compat import Property, Signal, Slot
from .base import SnapshotViewModel


class ProxyViewModel(SnapshotViewModel):
    """网络与监控: route proxy control, token statistics and event log."""

    statusChanged = Signal()
    eventsChanged = Signal()
    usageChanged = Signal()
    formChanged = Signal()

    def __init__(self, controller, parent=None) -> None:
        self._controller = controller
        self._status: dict[str, Any] = {}
        self._events: list[dict[str, Any]] = []
        self._daily: list[dict[str, Any]] = []
        self._projects: list[dict[str, Any]] = []
        self._apis: list[dict[str, Any]] = []
        self._rules: list[dict[str, Any]] = []
        self._filter = ""
        super().__init__(self._build_items, parent)

    # -- properties ------------------------------------------------------
    @Property("QVariantMap", notify=statusChanged)
    def status(self) -> dict[str, Any]:
        return dict(self._status)

    @Property("QVariantList", notify=eventsChanged)
    def events(self) -> list[dict[str, Any]]:
        return list(self._events)

    @Property("QVariantList", notify=usageChanged)
    def dailyUsage(self) -> list[dict[str, Any]]:
        return list(self._daily)

    @Property("QVariantList", notify=usageChanged)
    def projectUsage(self) -> list[dict[str, Any]]:
        return list(self._projects)

    @Property("QVariantList", notify=usageChanged)
    def apiUsage(self) -> list[dict[str, Any]]:
        return list(self._apis)

    @Property("QVariantList", notify=statusChanged)
    def rules(self) -> list[dict[str, Any]]:
        return list(self._rules)

    @Property(str, notify=eventsChanged)
    def eventFilter(self) -> str:
        return self._filter

    @eventFilter.setter
    def eventFilter(self, value: str) -> None:
        self.setEventFilter(value)

    @Property(str, notify=statusChanged)
    def host(self) -> str:
        return str(self._status.get("host") or "127.0.0.1")

    @Property(str, notify=statusChanged)
    def port(self) -> str:
        return str(self._status.get("port") or "")

    @Property(str, notify=statusChanged)
    def upstreamTimeout(self) -> str:
        return str(self._status.get("upstreamTimeoutSeconds") or "")

    # -- building --------------------------------------------------------
    def _build_items(self) -> list[dict[str, Any]]:
        state = dict(self._controller.snapshot() or {})
        proxy = dict(state.get("proxy") or {})

        self._status = {
            "enabled": bool(proxy.get("enabled")),
            "running": bool(proxy.get("running")),
            "host": str(proxy.get("host") or "127.0.0.1"),
            "port": proxy.get("port") or "",
            "baseUrl": str(proxy.get("baseUrl") or ""),
            "strategy": str(proxy.get("strategy") or ""),
            "strategyLabel": str(proxy.get("strategyLabel") or ""),
            "upstreamTimeoutSeconds": proxy.get("upstreamTimeoutSeconds") or "",
            "totalTokens": int(proxy.get("totalTokens") or 0),
            "todayTokens": int(proxy.get("todayTokens") or 0),
            "projectCount": int(proxy.get("projectCount") or 0),
            "apiCount": int(proxy.get("apiCount") or 0),
            "ruleCount": int(proxy.get("ruleCount") or 0),
            "eventCount": int(proxy.get("eventCount") or 0),
        }
        self.statusChanged.emit()

        events = list(state.get("proxy_events") or [])
        needle = self._filter.casefold().strip()
        if needle:
            events = [
                item
                for item in events
                if needle
                in " ".join(str(item.get(key, "")) for key in ("level", "message", "detail", "target")).casefold()
            ]
        if events != self._events:
            self._events = events
            self.eventsChanged.emit()

        daily = list(proxy.get("dailyUsage") or [])
        projects = list(proxy.get("projectUsage") or [])
        apis = list(proxy.get("apiUsage") or [])
        if (daily, projects, apis) != (self._daily, self._projects, self._apis):
            self._daily, self._projects, self._apis = daily, projects, apis
            self.usageChanged.emit()

        rules = list(proxy.get("rules") or [])
        self._rules = rules

        return [
            {"key": "status", "label": "运行状态", "value": "运行中" if self._status["running"] else "未启动",
             "tone": "success" if self._status["running"] else "warning"},
            {"key": "listen", "label": "监听地址", "value": self._status["baseUrl"] or "-", "tone": "info"},
            {"key": "strategy", "label": "号池策略", "value": self._status["strategyLabel"] or "-", "tone": "info"},
            {"key": "total", "label": "累计 Token", "value": str(self._status["totalTokens"]), "tone": "accent"},
            {"key": "today", "label": "今日 Token", "value": str(self._status["todayTokens"]), "tone": "accent"},
            {"key": "rules", "label": "项目路由", "value": str(self._status["ruleCount"]), "tone": "info"},
        ]

    # -- actions ---------------------------------------------------------
    @Slot()
    def start(self) -> None:
        self._controller.startProxy()

    @Slot()
    def stop(self) -> None:
        self._controller.stopProxy()

    @Slot()
    def toggle(self) -> None:
        self._controller.toggleProxy()

    @Slot("QVariantMap")
    def submitSettings(self, payload) -> None:
        self._controller.saveProxySettingsForm(dict(payload or {}))

    @Slot(str)
    def setEventFilter(self, text: str) -> None:
        value = str(text or "")
        if value != self._filter:
            self._filter = value
            self.refresh()

    @Slot()
    def clearEvents(self) -> None:
        self._controller.clearEvents()

    @Slot()
    def enableForProject(self) -> None:
        self._controller.setProjectProxyEnabled(True)

    @Slot()
    def disableForProject(self) -> None:
        self._controller.setProjectProxyEnabled(False)

    @Slot(str, bool)
    def setProjectProxy(self, project_id: str, enabled: bool) -> None:
        self._controller.setProjectProxyEnabled(bool(enabled), str(project_id))

    @Slot()
    def refreshStatus(self) -> None:
        self._controller.refreshProxyStatus()


__all__ = ["ProxyViewModel"]
