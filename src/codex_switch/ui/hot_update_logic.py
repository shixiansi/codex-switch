from __future__ import annotations

from codex_switch.models import HOT_UPDATE_EVENT_LIMIT, HotUpdateEvent
from codex_switch.ui.update_logic import software_update_error_detail


HOT_UPDATE_SCOPE_LABELS = {
    "software": "软件",
    "skill_repo": "Skills仓库",
    "project": "项目",
    "check": "检查",
}

HOT_UPDATE_STATUS_LABELS = {
    "available": "发现新版本",
    "current": "已是最新",
    "updated": "已更新",
    "opened": "已打开下载页",
    "pending": "待确认",
    "error": "错误",
    "summary": "完成",
}


def append_hot_update_event(
    events: list[HotUpdateEvent],
    *,
    scope: str,
    target: str,
    status: str,
    detail: str = "",
    commit: str = "",
    automatic: bool = False,
) -> list[HotUpdateEvent]:
    return [
        *events,
        HotUpdateEvent.create(
            scope=scope,
            target=target,
            status=status,
            detail=detail,
            commit=commit,
            automatic=automatic,
        ),
    ][-HOT_UPDATE_EVENT_LIMIT:]


def hot_update_event_line(event: HotUpdateEvent) -> str:
    scope = HOT_UPDATE_SCOPE_LABELS.get(event.scope, event.scope or "-")
    status = HOT_UPDATE_STATUS_LABELS.get(event.status, event.status or "-")
    mode = "自动" if event.automatic else "手动"
    commit = f" @{event.commit[:12]}" if event.commit else ""
    detail_text = event.detail
    if event.scope == "software" and event.status == "error":
        detail_text = software_update_error_detail(detail_text)
    detail = f" - {detail_text}" if detail_text else ""
    return f"{event.timestamp} [{mode}][{scope}][{status}] {event.target}{commit}{detail}"


def hot_update_summary_text(
    *,
    repo_updates: int,
    project_updates: int,
    pending_repo_updates: int,
    pending_project_updates: int,
    error_count: int,
) -> str:
    pending_text = ""
    if pending_repo_updates or pending_project_updates:
        pending_text = f"，待确认仓库 {pending_repo_updates}、项目 {pending_project_updates}"
    if error_count:
        return f"仓库同步检查完成，仓库 {repo_updates}、项目 {project_updates}{pending_text}，错误 {error_count} 条"
    return f"仓库同步检查完成，仓库 {repo_updates}、项目 {project_updates}{pending_text}。"
