from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import subprocess
from typing import Any, TypeVar

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


@dataclass(frozen=True)
class ManualHotUpdateSpec:
    scope: str
    target: str
    texts: HotUpdateDecisionTexts
    confirm_title: str
    confirm_message: str
    error_message_prefix: str
    current_info_message: str
    declined_status_message: str


@dataclass(frozen=True)
class HotUpdateBatchEvent:
    target: str
    status: str
    detail: str
    commit: str
    automatic: bool


@dataclass(frozen=True)
class HotUpdateBatchResult:
    updated_count: int
    pending_count: int
    errors: list[str]
    events: list[HotUpdateBatchEvent]


SKILL_REPO_HOT_UPDATE_TEXTS = HotUpdateDecisionTexts(
    current="\u8fdc\u7aef\u63d0\u4ea4\u672a\u53d8\u5316\u3002",
    auto_updated="\u81ea\u52a8\u62c9\u53d6\u5e76\u66f4\u65b0\u672c\u5730 Skills\u3002",
    auto_pending="\u81ea\u52a8\u66f4\u65b0\u672a\u5b8c\u6210\uff0c\u8bf7\u7a0d\u540e\u786e\u8ba4\u3002",
    manual_updated="\u7528\u6237\u786e\u8ba4\u540e\u62c9\u53d6\u5e76\u66f4\u65b0\u672c\u5730 Skills\u3002",
    manual_pending="\u624b\u52a8\u66f4\u65b0\u672a\u5b8c\u6210\uff0c\u8bf7\u7a0d\u540e\u786e\u8ba4\u3002",
    declined="\u7528\u6237\u6682\u4e0d\u62c9\u53d6\u3002",
    auto_disabled="\u672a\u914d\u7f6e\u4ed3\u5e93\u81ea\u52a8\u66f4\u65b0\u3002",
)

PROJECT_HOT_UPDATE_TEXTS = HotUpdateDecisionTexts(
    current="\u8fdc\u7aef\u63d0\u4ea4\u672a\u53d8\u5316\u3002",
    auto_updated="\u81ea\u52a8\u6267\u884c git pull --ff-only \u5e76\u540c\u6b65\u9879\u76ee\u5143\u6570\u636e\u3002",
    auto_pending="\u81ea\u52a8\u66f4\u65b0\u672a\u5b8c\u6210\uff0c\u8bf7\u7a0d\u540e\u786e\u8ba4\u3002",
    manual_updated="\u7528\u6237\u786e\u8ba4\u540e\u6267\u884c git pull --ff-only \u5e76\u540c\u6b65\u9879\u76ee\u5143\u6570\u636e\u3002",
    manual_pending="\u624b\u52a8\u66f4\u65b0\u672a\u5b8c\u6210\uff0c\u8bf7\u7a0d\u540e\u786e\u8ba4\u3002",
    declined="\u7528\u6237\u6682\u4e0d\u62c9\u53d6\u3002",
    auto_disabled="\u672a\u914d\u7f6e\u9879\u76ee\u81ea\u52a8\u66f4\u65b0\u3002",
)


def skill_repo_manual_hot_update_spec(repo_url: str, short_latest: str) -> ManualHotUpdateSpec:
    return ManualHotUpdateSpec(
        scope="skill_repo",
        target=repo_url,
        texts=SKILL_REPO_HOT_UPDATE_TEXTS,
        confirm_title="发现更新",
        confirm_message=f"发现更新：{short_latest}。是否拉取并重载到本地组？",
        error_message_prefix="无法检查仓库更新",
        current_info_message="当前已经最新。",
        declined_status_message=f"已保留待更新的 Skills 仓库：{short_latest}",
    )


def project_manual_hot_update_spec(project_name: str, short_latest: str) -> ManualHotUpdateSpec:
    return ManualHotUpdateSpec(
        scope="project",
        target=project_name,
        texts=PROJECT_HOT_UPDATE_TEXTS,
        confirm_title="发现更新",
        confirm_message=f"发现项目更新：{short_latest}。是否执行 git pull --ff-only？",
        error_message_prefix="无法检查项目更新",
        current_info_message="项目远端已经最新。",
        declined_status_message=f"已保留待更新的项目：{short_latest}",
    )


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


T = TypeVar("T")


def process_hot_update_targets(
    items: list[T],
    *,
    automatic: bool,
    fetch_update: Callable[[T], Any],
    get_target: Callable[[T], str],
    get_error_label: Callable[[T], str],
    get_auto_update_enabled: Callable[[T], bool],
    texts: HotUpdateDecisionTexts,
    apply_update: Callable[[T, str, bool], bool],
    set_current_commit: Callable[[T, str], None] | None = None,
    confirm_update: Callable[[T, str], bool] | None = None,
) -> HotUpdateBatchResult:
    updated_count = 0
    pending_count = 0
    errors: list[str] = []
    events: list[HotUpdateBatchEvent] = []

    for item in list(items):
        target = get_target(item)
        try:
            update = fetch_update(item)
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
            detail = str(exc)
            errors.append(f"{get_error_label(item)} {target}: {detail}")
            events.append(
                HotUpdateBatchEvent(
                    target=target,
                    status="error",
                    detail=detail,
                    commit="",
                    automatic=automatic,
                )
            )
            continue

        auto_update_enabled = get_auto_update_enabled(item)
        decision = process_hot_update_candidate(
            has_update=update.has_update,
            latest_commit=update.latest_commit,
            automatic=automatic,
            auto_update_enabled=auto_update_enabled,
            texts=texts,
            apply_update=lambda: apply_update(item, update.latest_commit, auto_update_enabled),
            set_current_commit=(
                (lambda commit, current=item: set_current_commit(current, commit))
                if set_current_commit is not None
                else None
            ),
            confirm_update=(
                (lambda current=item, latest=update.short_latest: confirm_update(current, latest))
                if confirm_update is not None and not automatic and not auto_update_enabled
                else None
            ),
        )
        updated_count += decision.updated_delta
        pending_count += decision.pending_delta
        if decision.event_status:
            events.append(
                HotUpdateBatchEvent(
                    target=target,
                    status=decision.event_status,
                    detail=decision.event_detail,
                    commit=decision.commit,
                    automatic=decision.event_automatic,
                )
            )

    return HotUpdateBatchResult(
        updated_count=updated_count,
        pending_count=pending_count,
        errors=errors,
        events=events,
    )
