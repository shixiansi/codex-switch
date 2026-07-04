from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

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


@dataclass(frozen=True)
class HotUpdateDecisionTexts:
    current: str
    auto_updated: str
    auto_pending: str
    manual_updated: str
    manual_pending: str
    declined: str
    auto_disabled: str


@dataclass(frozen=True)
class HotUpdateDecision:
    updated_delta: int
    pending_delta: int
    event_status: str | None
    event_detail: str
    event_automatic: bool
    commit: str


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


def process_hot_update_candidate(
    *,
    has_update: bool,
    latest_commit: str,
    automatic: bool,
    auto_update_enabled: bool,
    texts: HotUpdateDecisionTexts,
    apply_update: Callable[[], bool],
    set_current_commit: Callable[[str], None] | None = None,
    confirm_update: Callable[[], bool] | None = None,
) -> HotUpdateDecision:
    if not has_update:
        if set_current_commit is not None and latest_commit:
            set_current_commit(latest_commit)
        if automatic:
            return HotUpdateDecision(
                updated_delta=0,
                pending_delta=0,
                event_status=None,
                event_detail=texts.current,
                event_automatic=False,
                commit=latest_commit,
            )
        return HotUpdateDecision(
            updated_delta=0,
            pending_delta=0,
            event_status="current",
            event_detail=texts.current,
            event_automatic=False,
            commit=latest_commit,
        )

    if auto_update_enabled:
        if apply_update():
            return HotUpdateDecision(
                updated_delta=1,
                pending_delta=0,
                event_status="updated",
                event_detail=texts.auto_updated,
                event_automatic=True,
                commit=latest_commit,
            )
        return HotUpdateDecision(
            updated_delta=0,
            pending_delta=1,
            event_status="pending",
            event_detail=texts.auto_pending,
            event_automatic=True,
            commit=latest_commit,
        )

    if not automatic:
        confirmed = confirm_update() if confirm_update is not None else False
        if confirmed:
            if apply_update():
                return HotUpdateDecision(
                    updated_delta=1,
                    pending_delta=0,
                    event_status="updated",
                    event_detail=texts.manual_updated,
                    event_automatic=False,
                    commit=latest_commit,
                )
            return HotUpdateDecision(
                updated_delta=0,
                pending_delta=1,
                event_status="pending",
                event_detail=texts.manual_pending,
                event_automatic=False,
                commit=latest_commit,
            )
        return HotUpdateDecision(
            updated_delta=0,
            pending_delta=1,
            event_status="pending",
            event_detail=texts.declined,
            event_automatic=False,
            commit=latest_commit,
        )

    return HotUpdateDecision(
        updated_delta=0,
        pending_delta=1,
        event_status="pending",
        event_detail=texts.auto_disabled,
        event_automatic=True,
        commit=latest_commit,
    )
