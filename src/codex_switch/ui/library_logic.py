from __future__ import annotations

from dataclasses import dataclass

from codex_switch.models import Profile, VENDOR_CLAUDE, VENDOR_CODEX, VENDOR_GENERIC, VENDOR_OTHER
from codex_switch.ui.utils import compact_text, hidden_secret


@dataclass(frozen=True)
class LibraryTreeRow:
    item_id: str
    values: tuple[str, str, str, str, str, str]
    tag: str


@dataclass(frozen=True)
class LibraryTabDisplay:
    selected_profile_id: str | None
    display_columns: tuple[str, ...]
    rows: list[LibraryTreeRow]
    hint_text: str


@dataclass(frozen=True)
class LibraryDetailDisplay:
    selected_name: str
    provider_text: str
    category_text: str
    model_text: str
    api_text: str
    key_text: str
    wire_text: str
    sign_in_status_text: str
    sign_in_url_text: str
    notes_text: str
    badge_text: str
    badge_state: str
    model_tags: list[str]
    empty_tags_text: str


def visible_profiles_for_filter(profiles: list[Profile], hide_error_profiles: bool) -> list[Profile]:
    if not hide_error_profiles:
        return list(profiles)
    return [profile for profile in profiles if profile.effective_health_status != "error"]


def profiles_for_library_view(profiles: list[Profile], profile_view: str) -> list[Profile]:
    if profile_view == "all":
        return list(profiles)
    if profile_view == VENDOR_CODEX:
        return [profile for profile in profiles if profile.vendor in {VENDOR_CODEX, VENDOR_GENERIC}]
    if profile_view == VENDOR_CLAUDE:
        return [profile for profile in profiles if profile.vendor in {VENDOR_CLAUDE, VENDOR_GENERIC}]
    if profile_view == VENDOR_OTHER:
        return [profile for profile in profiles if profile.vendor == VENDOR_OTHER]
    return []


def profile_library_sort_key(profile: Profile) -> tuple[int, str, str]:
    sign_in_rank = {
        "未签到": 0,
        "已签到": 1,
        "无需签到": 2,
    }.get(profile.sign_in_status, 3)
    return sign_in_rank, profile.name.casefold(), profile.id


def profile_key_summary(profile: Profile) -> str:
    summary = hidden_secret(profile.api_key)
    key_count = len(profile.api_keys)
    if key_count > 1:
        return f"{summary}（Key {profile.effective_active_api_key_index + 1}/{key_count}）"
    return summary


def profile_model_summary(profile: Profile) -> str:
    if profile.vendor == VENDOR_CODEX:
        return f"Codex：{profile.codex_display_model}"
    if profile.vendor == VENDOR_CLAUDE:
        return f"Claude：{profile.claude_display_model} / 兜底：{profile.claude_display_fallback_model}"
    if profile.vendor == VENDOR_OTHER:
        return "-"
    return (
        f"Codex：{profile.codex_display_model}\n"
        f"Claude：{profile.claude_display_model} / 兜底：{profile.claude_display_fallback_model}"
    )


def profile_library_model_summary(profile: Profile, library_profile_view: str) -> str:
    if library_profile_view == VENDOR_CODEX:
        return profile.codex_display_model
    if library_profile_view == VENDOR_CLAUDE:
        return profile.claude_display_model
    if profile.vendor == VENDOR_CODEX:
        return profile.codex_display_model
    if profile.vendor == VENDOR_CLAUDE:
        return profile.claude_display_model
    if profile.vendor == VENDOR_GENERIC:
        return f"{profile.codex_display_model} / {profile.claude_display_model}"
    return "-"


def health_status_text(profile: Profile, status_text: dict[str, str]) -> str:
    label = status_text.get(profile.effective_health_status, "未知")
    return f"{label}（手动）" if profile.has_manual_health_override else label


def health_override_note(profile: Profile | None) -> str:
    if profile is None:
        return "自动健康状态基于连通性，可临时设置手动健康覆盖。"
    if profile.has_manual_health_override:
        return "当前以手动状态为准，自动健康结果仅用于检测显示。"
    return "当前使用自动健康状态，异常时可设置手动覆盖。"


def current_status_counts(profiles: list[Profile]) -> tuple[int, int, int, int]:
    total = len(profiles)
    healthy = sum(1 for profile in profiles if profile.effective_health_status == "healthy")
    degraded = sum(1 for profile in profiles if profile.effective_health_status == "degraded")
    error = sum(1 for profile in profiles if profile.effective_health_status == "error")
    return total, healthy, degraded, error


def build_library_tab_display(
    profiles: list[Profile],
    *,
    hide_error_profiles: bool,
    library_profile_view: str,
    selected_profile_id: str | None,
    library_view_all: str,
    library_tree_columns: tuple[str, ...],
    library_tree_columns_with_vendor: tuple[str, ...],
    profile_tree_iid,
    scope_label_map: dict[str, str],
    status_text: dict[str, str],
) -> LibraryTabDisplay:
    visible_profiles = visible_profiles_for_filter(profiles, hide_error_profiles)
    scope_profiles = profiles_for_library_view(visible_profiles, library_profile_view)
    scope_label = scope_label_map.get(library_profile_view, "全部")
    display_columns = (
        library_tree_columns_with_vendor if library_profile_view == library_view_all else library_tree_columns
    )
    if selected_profile_id and not any(profile.id == selected_profile_id for profile in scope_profiles):
        selected_profile_id = scope_profiles[0].id if scope_profiles else None
    rows = [
        LibraryTreeRow(
            item_id=profile_tree_iid(library_profile_view, profile),
            values=(
                profile.name,
                profile.vendor_label,
                compact_text(profile.base_url, 42),
                compact_text(profile_library_model_summary(profile, library_profile_view) or "-", 18),
                profile.sign_in_status,
                health_status_text(profile, status_text),
            ),
            tag=profile.effective_health_status,
        )
        for profile in sorted(scope_profiles, key=profile_library_sort_key)
    ]
    visible_healthy = sum(1 for profile in scope_profiles if profile.effective_health_status == "healthy")
    if hide_error_profiles:
        hint_text = f"{scope_label} 显示 {len(scope_profiles)} 个配置，健康可用 {visible_healthy} 个。"
    else:
        hint_text = f"{scope_label} 共 {len(scope_profiles)} 个配置，健康可用 {visible_healthy} 个。"
    return LibraryTabDisplay(
        selected_profile_id=selected_profile_id if selected_profile_id else (scope_profiles[0].id if scope_profiles else None),
        display_columns=display_columns,
        rows=rows,
        hint_text=hint_text,
    )


def build_library_detail_display(profile: Profile | None, *, status_text: dict[str, str]) -> LibraryDetailDisplay:
    if profile is None:
        return LibraryDetailDisplay(
            selected_name="未选择配置",
            provider_text="-",
            category_text="-",
            model_text="-",
            api_text="-",
            key_text="-",
            wire_text="-",
            sign_in_status_text="-",
            sign_in_url_text="-",
            notes_text="暂无备注",
            badge_text="未知",
            badge_state="unknown",
            model_tags=[],
            empty_tags_text="当前配置尚未返回模型列表。",
        )

    return LibraryDetailDisplay(
        selected_name=profile.name,
        provider_text=f"{profile.vendor_label} / {profile.provider_name}",
        category_text=profile.category_label,
        model_text=profile_model_summary(profile),
        api_text=profile.base_url if profile.api_provided else "未提供 API",
        key_text=profile_key_summary(profile) if profile.api_provided else "未提供 API",
        wire_text=profile.wire_api,
        sign_in_status_text=profile.sign_in_status,
        sign_in_url_text=profile.sign_in_url or "-",
        notes_text=profile.notes or "暂无备注",
        badge_text=health_status_text(profile, status_text),
        badge_state=profile.effective_health_status,
        model_tags=list(profile.health.models),
        empty_tags_text="当前配置尚未返回模型列表。",
    )
