from __future__ import annotations

from dataclasses import dataclass

from codex_switch.models import CurrentCodexConfig, model_vendor_stats, models_by_vendor

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


@dataclass(frozen=True)
class GlobalTabDisplay:
    total_text: str
    healthy_text: str
    degraded_text: str
    error_text: str
    codex_current_api_text: str
    codex_current_models_text: str
    claude_current_api_text: str
    claude_current_models_text: str
    current_paths_text: str
    global_mcp_text: str


@dataclass(frozen=True)
class TestDetailDisplay:
    selected_name: str
    health_text: str
    provider_text: str
    model_text: str
    api_text: str
    key_text: str
    wire_text: str
    endpoint_text: str
    checked_text: str
    notes_text: str
    result_text: str
    success_models_text: str
    badge_state: str
    health_override_value: str
    health_override_note_text: str
    health_override_state: str


@dataclass(frozen=True)
class TestTreeRow:
    profile_id: str
    values: tuple[str, str]
    tag: str


@dataclass(frozen=True)
class TestTabDisplay:
    selected_profile_id: str | None
    rows: list[TestTreeRow]


@dataclass(frozen=True)
class LibraryModelTagsDisplay:
    normalized_models: list[str]
    visible_models: list[str]
    summary_text: str
    stats_button_text: str
    empty_text: str | None = None


@dataclass(frozen=True)
class LibraryModelTagLayout:
    column_count: int
    tag_count: int
    relayout_required: bool


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


def build_global_tab_display(
    current_config: CurrentCodexConfig,
    *,
    counts: tuple[int, int, int, int],
    claude_base_url: str,
    claude_model: str,
    claude_fallback_model: str,
    claude_settings_path: str,
    global_mcp_text: str,
) -> GlobalTabDisplay:
    total, healthy, degraded, error = counts
    model_lines: list[str] = []
    if current_config.model:
        model_lines.append(f"主模型：{current_config.model}")
    if current_config.review_model and current_config.review_model != current_config.model:
        model_lines.append(f"评审模型：{current_config.review_model}")
    codex_current_models_text = "\n".join(model_lines) if model_lines else "模型：-"
    return GlobalTabDisplay(
        total_text=str(total),
        healthy_text=str(healthy),
        degraded_text=str(degraded),
        error_text=str(error),
        codex_current_api_text=f"API 地址：{current_config.base_url or '-'}",
        codex_current_models_text=codex_current_models_text,
        claude_current_api_text=f"API 地址：{claude_base_url}",
        claude_current_models_text=f"主模型：{claude_model}\n兜底模型：{claude_fallback_model}",
        current_paths_text=(
            f"Codex config.toml\n{current_config.config_path}\n\n"
            f"Codex auth.json\n{current_config.auth_path}\n\n"
            f"Claude settings.json\n{claude_settings_path}"
        ),
        global_mcp_text=global_mcp_text,
    )


def build_test_detail_display(
    profile: Profile | None,
    *,
    status_text: dict[str, str],
    key_summary,
    model_summary,
    success_models_text: str,
    health_override_display_map: dict[str, str],
) -> TestDetailDisplay:
    if profile is None:
        return TestDetailDisplay(
            selected_name="未选择配置",
            health_text="未知",
            provider_text="-",
            model_text="-",
            api_text="-",
            key_text="-",
            wire_text="-",
            endpoint_text="-",
            checked_text="-",
            notes_text="暂无备注",
            result_text="未知",
            success_models_text="未执行测试",
            badge_state="unknown",
            health_override_value=health_override_display_map[""],
            health_override_note_text=health_override_note(None),
            health_override_state="disabled",
        )

    checked_text = profile.health.checked_at or "-"
    if profile.health.latency_ms is not None:
        checked_text = f"{checked_text}    {profile.health.latency_ms} ms"
    return TestDetailDisplay(
        selected_name=profile.name,
        health_text=health_status_text(profile, status_text),
        provider_text=profile.provider_name,
        model_text=model_summary(profile),
        api_text=profile.base_url,
        key_text=key_summary(profile),
        wire_text=profile.wire_api,
        endpoint_text=profile.health.endpoint or "-",
        checked_text=checked_text,
        notes_text=profile.notes or "暂无备注",
        result_text=profile.health.detail or "未知",
        success_models_text=success_models_text,
        badge_state=profile.effective_health_status,
        health_override_value=health_override_display_map.get(
            profile.manual_health_status or "",
            health_override_display_map[""],
        ),
        health_override_note_text=health_override_note(profile),
        health_override_state="readonly",
    )


def build_test_tab_display(
    profiles: list[Profile],
    *,
    hide_error_profiles: bool,
    selected_profile_id: str | None,
    status_text: dict[str, str],
) -> TestTabDisplay:
    visible_profiles = visible_profiles_for_filter(profiles, hide_error_profiles)
    if selected_profile_id and not any(profile.id == selected_profile_id for profile in visible_profiles):
        selected_profile_id = visible_profiles[0].id if visible_profiles else None
    if not selected_profile_id and visible_profiles:
        selected_profile_id = visible_profiles[0].id
    rows = [
        TestTreeRow(
            profile_id=profile.id,
            values=(profile.name, health_status_text(profile, status_text)),
            tag=profile.effective_health_status,
        )
        for profile in visible_profiles
    ]
    return TestTabDisplay(
        selected_profile_id=selected_profile_id,
        rows=rows,
    )


def build_library_model_tags_display(
    models: list[str],
    *,
    empty_text: str,
    model_vendor_keywords: dict[str, list[str]],
    expanded: bool,
) -> LibraryModelTagsDisplay:
    normalized_models = [str(model).strip() for model in models if str(model).strip()]
    if not normalized_models:
        return LibraryModelTagsDisplay(
            normalized_models=[],
            visible_models=[],
            summary_text=empty_text,
            stats_button_text="展开统计",
            empty_text=empty_text,
        )

    visible_models = normalized_models[:20]
    hidden_count = max(0, len(normalized_models) - len(visible_models))
    stats = model_vendor_stats(normalized_models, model_vendor_keywords)
    stats_summary = "；".join(f"{vendor} {count}" for vendor, count in stats.items())
    summary = f"共 {len(normalized_models)} 个模型；标签显示前 {len(visible_models)} 个"
    if hidden_count:
        summary += f"，隐藏 {hidden_count} 个"
    if stats_summary:
        summary += f"。{stats_summary}"
    return LibraryModelTagsDisplay(
        normalized_models=normalized_models,
        visible_models=visible_models,
        summary_text=summary,
        stats_button_text="收起统计" if expanded else "展开统计",
    )


def build_library_model_tag_layout(
    *,
    width: int,
    tag_count: int,
    previous_columns: int,
    previous_count: int,
) -> LibraryModelTagLayout:
    tag_width = 172
    gap = 8
    available_width = max(tag_width, width - 12)
    column_count = max(1, available_width // (tag_width + gap))
    return LibraryModelTagLayout(
        column_count=column_count,
        tag_count=tag_count,
        relayout_required=previous_columns != column_count or previous_count != tag_count,
    )


def library_model_stats_content(
    models: list[str],
    *,
    model_vendor_keywords: dict[str, list[str]],
) -> str:
    grouped = models_by_vendor(models, model_vendor_keywords)
    lines: list[str] = []
    for vendor, names in grouped.items():
        lines.append(f"{vendor}（{len(names)}）")
        lines.extend(f"  - {name}" for name in names)
    return "\n".join(lines) if lines else "暂无统计。"
