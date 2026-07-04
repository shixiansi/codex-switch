from __future__ import annotations

from collections.abc import Iterable

from codex_switch.chat import AccountPoolSessionValidator
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


def account_pool_project_count(projects: Iterable[ProjectRecord], route_proxy_settings: RouteProxySettings) -> int:
    return sum(1 for project in projects if project_uses_account_pool(route_proxy_settings, project.id))


def account_pool_channel_by_id(settings: AccountPoolSettings, channel_id: str | None) -> AccountPoolChannel | None:
    return next((channel for channel in settings.channels if channel.id == channel_id), None)


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
