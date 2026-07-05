from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from codex_switch.chat import AccountPoolSessionValidator
from codex_switch.ui.utils import compact_text
from codex_switch.models import (
    AccountPoolChannel,
    AccountPoolGroup,
    AccountPoolSettings,
    ACCOUNT_POOL_CHANNEL_SOURCE_PROFILE,
    ACCOUNT_POOL_CHANNEL_SOURCE_TEMPORARY,
    ACCOUNT_POOL_GROUP_TYPE_CLAUDE,
    ACCOUNT_POOL_GROUP_TYPE_CODEX,
    ACCOUNT_POOL_GROUP_TYPE_LABELS,
    DEFAULT_CLAUDE_FALLBACK_MODEL,
    DEFAULT_CLAUDE_MODEL,
    DEFAULT_CODEX_MODEL,
    effective_account_pool_wire_api,
    HealthResult,
    Profile,
    ProjectRecord,
    RouteProxySettings,
    ROUTE_PROXY_UPSTREAM_SOURCE_ACCOUNT_POOL,
    VENDOR_CLAUDE,
    VENDOR_CODEX,
)


ACCOUNT_POOL_SOURCE_FILTER_ALL = "全部"
ACCOUNT_POOL_SOURCE_FILTER_TEMPORARY = "临时号池"
ACCOUNT_POOL_SOURCE_FILTER_PROFILE = "配置库号池"
ACCOUNT_POOL_SOURCE_LABEL_TEMPORARY = "临时号池"
ACCOUNT_POOL_SOURCE_LABEL_PROFILE = "配置库号池"


@dataclass(frozen=True)
class AccountPoolChannelSubmission:
    channel: AccountPoolChannel
    health_result: HealthResult


@dataclass(frozen=True)
class AccountPoolGroupSettingsUpdate:
    enabled: bool
    pool_type: str
    default_model: str
    claude_model: str
    claude_fallback_model: str


@dataclass(frozen=True)
class AccountPoolGroupFormDisplay:
    enabled: bool
    group_type_label: str
    default_model: str
    claude_model: str
    claude_fallback_model: str


@dataclass(frozen=True)
class AccountPoolGroupChoicesDisplay:
    choices: dict[str, str]
    labels: list[str]
    selected_label: str
    form: AccountPoolGroupFormDisplay | None


@dataclass(frozen=True)
class AccountPoolChannelRow:
    channel_id: str
    values: tuple[str, str, str, str, str, str, str, str]


@dataclass(frozen=True)
class AccountPoolDetailDisplay:
    selected_name: str
    detail_text: str


@dataclass(frozen=True)
class AccountPoolTabDisplay:
    group_display: AccountPoolGroupChoicesDisplay
    summary_text: str
    rows: list[AccountPoolChannelRow]
    selected_channel_id: str | None


def account_pool_group_type_from_label(label: str) -> str:
    for group_type, group_label in ACCOUNT_POOL_GROUP_TYPE_LABELS.items():
        if group_label == label:
            return group_type
    return ACCOUNT_POOL_GROUP_TYPE_CODEX


def account_pool_group_label(group: AccountPoolGroup, settings: AccountPoolSettings) -> str:
    state = "启用" if group.enabled else "停用"
    type_label = ACCOUNT_POOL_GROUP_TYPE_LABELS.get(group.pool_type, "Codex")
    normal_count = len(settings.normal_channels_for_group(group.id))
    failed_count = len(settings.failed_channels_for_group(group.id))
    return f"{group.name}    {type_label} / {state} / 正常 {normal_count} / 异常 {failed_count}"


def account_pool_group_form_display(group: AccountPoolGroup | None) -> AccountPoolGroupFormDisplay | None:
    if group is None:
        return None
    return AccountPoolGroupFormDisplay(
        enabled=group.enabled,
        group_type_label=ACCOUNT_POOL_GROUP_TYPE_LABELS.get(group.pool_type, ACCOUNT_POOL_GROUP_TYPE_LABELS[ACCOUNT_POOL_GROUP_TYPE_CODEX]),
        default_model=group.default_model or DEFAULT_CODEX_MODEL,
        claude_model=group.claude_model or DEFAULT_CLAUDE_MODEL,
        claude_fallback_model=group.claude_fallback_model or DEFAULT_CLAUDE_FALLBACK_MODEL,
    )


def account_pool_group_choices_display(settings: AccountPoolSettings) -> AccountPoolGroupChoicesDisplay:
    choices: dict[str, str] = {}
    labels: list[str] = []
    for group in settings.groups:
        label = account_pool_group_label(group, settings)
        labels.append(label)
        choices[label] = group.id
    selected_group = settings.group_by_id(settings.selected_group_id)
    selected_label = ""
    if selected_group is not None:
        selected_label = next((label for label, group_id in choices.items() if group_id == selected_group.id), "")
    return AccountPoolGroupChoicesDisplay(
        choices=choices,
        labels=labels,
        selected_label=selected_label,
        form=account_pool_group_form_display(selected_group),
    )


def account_pool_source_label(channel: AccountPoolChannel) -> str:
    if channel.source_type == ACCOUNT_POOL_CHANNEL_SOURCE_PROFILE:
        return ACCOUNT_POOL_SOURCE_LABEL_PROFILE
    return ACCOUNT_POOL_SOURCE_LABEL_TEMPORARY


def account_pool_visible_channels(
    settings: AccountPoolSettings,
    group_id: str,
    source_filter: str,
) -> list[AccountPoolChannel]:
    channels = settings.channels_for_group(group_id)
    if source_filter == ACCOUNT_POOL_SOURCE_FILTER_TEMPORARY:
        return [channel for channel in channels if channel.source_type == ACCOUNT_POOL_CHANNEL_SOURCE_TEMPORARY]
    if source_filter == ACCOUNT_POOL_SOURCE_FILTER_PROFILE:
        return [channel for channel in channels if channel.source_type == ACCOUNT_POOL_CHANNEL_SOURCE_PROFILE]
    return channels


def account_pool_summary_text(
    settings: AccountPoolSettings,
    *,
    group_id: str,
    project_count: int,
) -> str:
    return (
        f"连接号池项目 {project_count} 个，"
        f"当前组正常渠道 {len(settings.normal_channels_for_group(group_id))} 个，"
        f"异常渠道 {len(settings.failed_channels_for_group(group_id))} 个。"
    )


def account_pool_channel_rows(channels: list[AccountPoolChannel]) -> list[AccountPoolChannelRow]:
    return [
        AccountPoolChannelRow(
            channel_id=channel.id,
            values=(
                channel.name,
                account_pool_source_label(channel),
                compact_text(channel.base_url, 34),
                channel.wire_api,
                channel.api_key_masked,
                "正常" if channel.is_normal else "异常",
                channel.last_checked_at or "-",
                compact_text(channel.failure_reason or "-", 34),
            ),
        )
        for channel in channels
    ]


def account_pool_detail_display(channel: AccountPoolChannel) -> AccountPoolDetailDisplay:
    source_detail = "临时填写"
    if channel.source_type == ACCOUNT_POOL_CHANNEL_SOURCE_PROFILE:
        source_detail = f"配置库：{channel.source_profile_name or channel.source_profile_id or '-'} / Key {channel.source_api_key_index + 1}"
    detail = (
        f"API：{channel.base_url}\n"
        f"来源：{account_pool_source_label(channel)}（{source_detail}）\n"
        f"Wire API：{channel.wire_api}\n"
        f"默认模型：{channel.default_model}\n"
        f"自定义请求头：{len(channel.custom_headers)} 个\n"
        f"Key：{channel.api_key_masked}\n"
        f"状态：{'正常' if channel.is_normal else '异常'}\n"
        f"最后检测：{channel.last_checked_at or '-'}\n"
        f"最后成功：{channel.last_success_at or '-'}\n"
        f"失败原因：{channel.failure_reason or '-'}"
    )
    return AccountPoolDetailDisplay(selected_name=channel.name, detail_text=detail)


def account_pool_tab_display(
    settings: AccountPoolSettings,
    *,
    projects: Iterable[ProjectRecord],
    route_proxy_settings: RouteProxySettings,
    source_filter: str,
    selected_channel_id: str | None,
) -> AccountPoolTabDisplay:
    settings.ensure_default_group()
    group_display = account_pool_group_choices_display(settings)
    group_id = group_display.choices.get(group_display.selected_label, settings.selected_group_id)
    rows = account_pool_channel_rows(
        account_pool_visible_channels(
            settings,
            group_id,
            source_filter,
        )
    )
    resolved_selected_channel_id = (
        selected_channel_id
        if any(row.channel_id == selected_channel_id for row in rows)
        else None
    )
    return AccountPoolTabDisplay(
        group_display=group_display,
        summary_text=account_pool_summary_text(
            settings,
            group_id=group_id,
            project_count=account_pool_project_count(projects, route_proxy_settings),
        ),
        rows=rows,
        selected_channel_id=resolved_selected_channel_id,
    )


def project_uses_account_pool(route_proxy_settings: RouteProxySettings, project_id: str) -> bool:
    return any(
        rule.enabled
        and rule.project_id == project_id
        and rule.upstream_source == ROUTE_PROXY_UPSTREAM_SOURCE_ACCOUNT_POOL
        for rule in route_proxy_settings.rules
    )


def project_account_pool_group_name(
    route_proxy_settings: RouteProxySettings,
    account_pool_settings: AccountPoolSettings,
    project_id: str,
) -> str:
    rule = next(
        (
            item
            for item in route_proxy_settings.rules
            if item.enabled
            and item.project_id == project_id
            and item.upstream_source == ROUTE_PROXY_UPSTREAM_SOURCE_ACCOUNT_POOL
        ),
        None,
    )
    if rule is None:
        return "否"
    group = account_pool_settings.group_by_id(rule.account_pool_group_id)
    return group.name if group is not None else "已删除"


def account_pool_group_delete_error(settings: AccountPoolSettings, group_id: str) -> str | None:
    if len(settings.groups) <= 1:
        return "至少保留一个号池组。"
    if settings.channels_for_group(group_id):
        return "当前号池组还有渠道，请先删除或移动渠道。"
    return None


def account_pool_project_count(projects: Iterable[ProjectRecord], route_proxy_settings: RouteProxySettings) -> int:
    return sum(1 for project in projects if project_uses_account_pool(route_proxy_settings, project.id))


def account_pool_channel_by_id(settings: AccountPoolSettings, channel_id: str | None) -> AccountPoolChannel | None:
    return next((channel for channel in settings.channels if channel.id == channel_id), None)


def resolve_account_pool_group_settings_update(
    *,
    enabled: bool,
    group_type_label: str,
    default_model_value: str,
    claude_model_value: str,
    claude_fallback_model_value: str,
) -> AccountPoolGroupSettingsUpdate:
    return AccountPoolGroupSettingsUpdate(
        enabled=enabled,
        pool_type=account_pool_group_type_from_label(group_type_label),
        default_model=default_model_value.strip() or DEFAULT_CODEX_MODEL,
        claude_model=claude_model_value.strip() or DEFAULT_CLAUDE_MODEL,
        claude_fallback_model=claude_fallback_model_value.strip() or DEFAULT_CLAUDE_FALLBACK_MODEL,
    )


def apply_account_pool_group_settings(group: AccountPoolGroup, update: AccountPoolGroupSettingsUpdate) -> None:
    group.enabled = update.enabled
    group.pool_type = update.pool_type
    group.default_model = update.default_model
    group.claude_model = update.claude_model
    group.claude_fallback_model = update.claude_fallback_model


def account_pool_channel_from_result(
    result: dict,
    *,
    selected_group_id: str,
    existing: AccountPoolChannel | None = None,
) -> AccountPoolChannel:
    group_id = existing.group_id if existing is not None else selected_group_id
    channel = AccountPoolChannel.create(
        name=result["name"],
        base_url=result["base_url"],
        api_key=result["api_key"],
        group_id=group_id,
        source_type=result.get("source_type", existing.source_type if existing else ACCOUNT_POOL_CHANNEL_SOURCE_TEMPORARY),
        source_profile_id=result.get("source_profile_id", existing.source_profile_id if existing else ""),
        source_profile_name=result.get("source_profile_name", existing.source_profile_name if existing else ""),
        source_api_key_index=result.get("source_api_key_index", existing.source_api_key_index if existing else 0),
        wire_api=result["wire_api"],
        default_model=result["default_model"],
        custom_headers=result.get("custom_headers", existing.custom_headers if existing else None),
    )
    if existing is not None:
        channel.id = existing.id
    return channel


def mark_account_pool_channel_success(channel: AccountPoolChannel, result: HealthResult) -> None:
    checked_at = result.checked_at or ""
    channel.status = "normal"
    channel.failure_reason = ""
    channel.failed_at = None
    channel.last_checked_at = checked_at
    channel.last_success_at = checked_at


def check_account_pool_channel(
    channel: AccountPoolChannel,
    *,
    settings: AccountPoolSettings,
    validator=None,
) -> HealthResult:
    group = settings.group_by_id(channel.group_id)
    group_type = group.pool_type if group is not None else ACCOUNT_POOL_GROUP_TYPE_CODEX
    wire_api = effective_account_pool_wire_api(group_type, channel.wire_api)
    if group_type == ACCOUNT_POOL_GROUP_TYPE_CLAUDE:
        model = (group.claude_model if group is not None else channel.default_model).strip() or DEFAULT_CLAUDE_MODEL
        profile = Profile.create(
            channel.name,
            channel.base_url,
            channel.api_key,
            model=model,
            vendor=VENDOR_CLAUDE,
            claude_model=model,
            claude_fallback_model=(
                (group.claude_fallback_model if group is not None else "").strip()
                or DEFAULT_CLAUDE_FALLBACK_MODEL
            ),
            wire_api=wire_api,
            custom_headers=channel.custom_headers,
        )
    else:
        model = (group.default_model if group is not None else channel.default_model).strip() or DEFAULT_CODEX_MODEL
        profile = Profile.create(
            channel.name,
            channel.base_url,
            channel.api_key,
            model=model,
            vendor=VENDOR_CODEX,
            codex_model=model,
            wire_api=wire_api,
            custom_headers=channel.custom_headers,
        )
    if validator is not None:
        try:
            return validator.check(
                profile,
                model=model,
                wire_api=wire_api,
                allow_codex_client_restricted=(group_type == ACCOUNT_POOL_GROUP_TYPE_CODEX),
            )
        except TypeError:
            return validator.check(profile)
    return AccountPoolSessionValidator().check(
        profile,
        model=model,
        wire_api=wire_api,
        allow_codex_client_restricted=(group_type == ACCOUNT_POOL_GROUP_TYPE_CODEX),
    )


def prepare_account_pool_channel_submission(
    result: dict,
    *,
    selected_group_id: str,
    settings: AccountPoolSettings,
    existing: AccountPoolChannel | None = None,
    validator=None,
) -> AccountPoolChannelSubmission:
    channel = account_pool_channel_from_result(
        result,
        selected_group_id=selected_group_id,
        existing=existing,
    )
    health_result = check_account_pool_channel(
        channel,
        settings=settings,
        validator=validator,
    )
    if health_result.status == "healthy":
        mark_account_pool_channel_success(channel, health_result)
    return AccountPoolChannelSubmission(channel=channel, health_result=health_result)
