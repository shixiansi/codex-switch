from __future__ import annotations

from typing import Any

from ..qt_compat import Property, Signal, Slot
from .base import SnapshotViewModel


class DashboardViewModel(SnapshotViewModel):
    """Home page: current configuration, health, project, proxy and activity."""

    summaryChanged = Signal()
    activityChanged = Signal()

    def __init__(self, controller, parent=None) -> None:
        self._controller = controller
        self._summary: dict[str, Any] = {}
        self._activity: list[dict[str, Any]] = []
        super().__init__(self._build_items, parent)

    @Property("QVariantMap", notify=summaryChanged)
    def summary(self) -> dict[str, Any]:
        return dict(self._summary)

    @Property("QVariantList", notify=activityChanged)
    def activity(self) -> list[dict[str, Any]]:
        return list(self._activity)

    def _build_items(self) -> list[dict[str, Any]]:
        state = dict(self._controller.snapshot() or {})
        profiles = list(state.get("profiles") or [])
        projects = list(state.get("projects") or [])
        proxy = dict(state.get("proxy") or {})
        pool = dict(state.get("account_pool") or {})
        health = dict(state.get("health") or {})

        current_profile = next((item for item in profiles if item.get("selected")), None)
        current_project = next((item for item in projects if item.get("selected")), None)
        current_codex = self._controller.session.global_codex_profile()
        current_claude = self._controller.session.global_claude_profile()

        self._summary = {
            "profileCount": len(profiles),
            "projectCount": len(projects),
            "healthyCount": int(health.get("healthy", 0)),
            "errorCount": int(health.get("error", 0)),
            "unknownCount": int(health.get("unknown", 0)),
            "currentProfileId": (current_profile or {}).get("id", ""),
            "currentProfileName": (current_profile or {}).get("name") or "未选择",
            "currentProfileHealth": (current_profile or {}).get("health", "unknown"),
            "currentProfileTone": (current_profile or {}).get("healthTone", "unknown"),
            "currentProjectId": (current_project or {}).get("id", ""),
            "currentProjectName": (current_project or {}).get("name") or "未选择",
            "currentProjectDir": (current_project or {}).get("projectDir", ""),
            "codexProfileName": current_codex.name if current_codex else "未写入",
            "claudeProfileName": current_claude.name if current_claude else "未写入",
            "proxyRunning": bool(proxy.get("running")),
            "proxyBaseUrl": str(proxy.get("baseUrl") or ""),
            "proxyTotalTokens": int(proxy.get("totalTokens") or 0),
            "proxyTodayTokens": int(proxy.get("todayTokens") or 0),
            "proxyRuleCount": int(proxy.get("ruleCount") or 0),
            "poolNormal": int(pool.get("normalChannels") or 0),
            "poolFailed": int(pool.get("failedChannels") or 0),
            "poolEnabled": bool(pool.get("enabled")),
        }

        activity = list(state.get("activity") or [])[:12]
        if activity != self._activity:
            self._activity = activity
            self.activityChanged.emit()

        self.summaryChanged.emit()
        return self._cards()

    def _cards(self) -> list[dict[str, Any]]:
        summary = self._summary
        proxy_tone = "success" if summary["proxyRunning"] else "warning"
        return [
            {
                "key": "profile",
                "icon": "profile",
                "label": "当前配置",
                "value": summary["currentProfileName"],
                "hint": f"共 {summary['profileCount']} 套配置",
                "tone": summary["currentProfileTone"],
            },
            {
                "key": "health",
                "icon": "pulse",
                "label": "API 健康",
                "value": f"{summary['healthyCount']} / {summary['profileCount']}",
                "hint": f"异常 {summary['errorCount']} · 未检测 {summary['unknownCount']}",
                "tone": "success" if summary["healthyCount"] else "warning",
            },
            {
                "key": "project",
                "icon": "folder",
                "label": "当前项目",
                "value": summary["currentProjectName"],
                "hint": f"共 {summary['projectCount']} 个项目",
                "tone": "info",
            },
            {
                "key": "proxy",
                "icon": "route",
                "label": "路由代理",
                "value": "运行中" if summary["proxyRunning"] else "未启动",
                "hint": summary["proxyBaseUrl"] or "未配置监听地址",
                "tone": proxy_tone,
            },
        ]

    @Slot()
    def refreshAll(self) -> None:
        self._controller.refreshAll()

    @Slot(str)
    def runHealthCheck(self, profile_id: str = "") -> None:
        self._controller.runHealthCheck(profile_id)

    @Slot()
    def runHealthCheckAll(self) -> None:
        self._controller.runHealthCheckAll()

    @Slot(str)
    def openProfile(self, profile_id: str) -> None:
        self._controller.navigateTo("profiles")
        self._controller.profiles.select(profile_id)

    @Slot(str)
    def openProject(self, project_id: str) -> None:
        self._controller.navigateTo("projects")
        self._controller.projects.select(project_id)

    @Slot()
    def toggleProxy(self) -> None:
        self._controller.toggleProxy()

    @Slot()
    def clearActivity(self) -> None:
        self._controller.clearEvents()


__all__ = ["DashboardViewModel"]
