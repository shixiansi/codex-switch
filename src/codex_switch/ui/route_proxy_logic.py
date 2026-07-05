from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from codex_switch.ui.utils import compact_text
from codex_switch.chat import (
    WIRE_API_ANTHROPIC_MESSAGES,
    WIRE_API_CHAT_COMPLETIONS,
    WIRE_API_RESPONSES,
    default_wire_api_for_profile,
)
from codex_switch.ui.account_pool_logic import account_pool_group_label
from codex_switch.models import (
    AccountPoolGroup,
    AccountPoolSettings,
    ACCOUNT_POOL_GROUP_TYPE_CLAUDE,
    DEFAULT_CLAUDE_FALLBACK_MODEL,
    DEFAULT_CLAUDE_MODEL,
    DEFAULT_CODEX_MODEL,
    Profile,
    ProjectRecord,
    RouteProxyRule,
    RouteProxySettings,
    ROUTE_PROXY_CLIENT_CLAUDE,
    ROUTE_PROXY_CLIENT_CODEX,
    ROUTE_PROXY_PROTOCOL_ANTHROPIC,
    ROUTE_PROXY_PROTOCOL_ANTHROPIC_TO_OPENAI,
    ROUTE_PROXY_PROTOCOL_OPENAI,
    ROUTE_PROXY_PROTOCOL_OPENAI_CHAT_TO_RESPONSES,
    ROUTE_PROXY_PROTOCOL_OPENAI_RESPONSES_TO_CHAT,
    ROUTE_PROXY_UPSTREAM_SOURCE_ACCOUNT_POOL,
    ROUTE_PROXY_UPSTREAM_SOURCE_PROFILE,
    normalize_route_proxy_account_pool_strategy,
    normalize_route_proxy_protocol,
    normalize_route_proxy_port,
    normalize_route_proxy_upstream_source,
    normalize_route_proxy_upstream_timeout_seconds,
)


CODEX_ROUTE_PROXY_PROTOCOLS = (
    ROUTE_PROXY_PROTOCOL_OPENAI,
    ROUTE_PROXY_PROTOCOL_OPENAI_CHAT_TO_RESPONSES,
    ROUTE_PROXY_PROTOCOL_OPENAI_RESPONSES_TO_CHAT,
)
CLAUDE_ROUTE_PROXY_PROTOCOLS = (
    ROUTE_PROXY_PROTOCOL_ANTHROPIC,
    ROUTE_PROXY_PROTOCOL_ANTHROPIC_TO_OPENAI,
)
CODEX_ROUTE_PROXY_UPSTREAM_SOURCES = (
    ROUTE_PROXY_UPSTREAM_SOURCE_PROFILE,
    ROUTE_PROXY_UPSTREAM_SOURCE_ACCOUNT_POOL,
)
CODEX_ROUTE_PROXY_UPSTREAM_SOURCE_LABELS = {
    ROUTE_PROXY_UPSTREAM_SOURCE_PROFILE: "默认配置",
    ROUTE_PROXY_UPSTREAM_SOURCE_ACCOUNT_POOL: "号池",
}
CODEX_ROUTE_PROXY_UPSTREAM_SOURCE_VALUES = {
    label: value
    for value, label in CODEX_ROUTE_PROXY_UPSTREAM_SOURCE_LABELS.items()
}


@dataclass(frozen=True)
class RouteProxyAccountPoolChoices:
    codex_choices: dict[str, str]
    claude_choices: dict[str, str]
    codex_labels: list[str]
    claude_labels: list[str]
    selected_codex_label: str
    selected_claude_label: str


@dataclass(frozen=True)
class RouteProxyDetailDisplay:
    selected_project_text: str
    selected_rules_text: str
    codex_upstream_source_label: str
    claude_upstream_source_label: str
    codex_protocol: str
    claude_protocol: str
    codex_compact_model: str
    codex_group_label: str
    claude_group_label: str


@dataclass(frozen=True)
class RouteProxyProjectRow:
    project_id: str
    values: tuple[str, str, str, str, str]


@dataclass(frozen=True)
class RouteProxySettingsForm:
    host: str
    port: int
    account_pool_strategy: str
    upstream_timeout_seconds: int


@dataclass(frozen=True)
class RouteProxyProjectRuleForm:
    codex_protocol: str
    codex_source: str
    codex_account_pool_group_id: str
    claude_protocol: str
    claude_source: str
    claude_account_pool_group_id: str
    compact_model: str
    codex_pool_model: str | None
    claude_pool_model: str | None


@dataclass(frozen=True)
class RouteProxyProjectEnablePlan:
    settings: RouteProxySettings
    codex_protocol: str
    claude_protocol: str


def route_proxy_codex_protocol_for_profile(profile: Profile) -> str:
    wire_api = default_wire_api_for_profile(profile)
    if wire_api == WIRE_API_RESPONSES:
        return ROUTE_PROXY_PROTOCOL_OPENAI
    if wire_api == WIRE_API_CHAT_COMPLETIONS:
        return ROUTE_PROXY_PROTOCOL_OPENAI_RESPONSES_TO_CHAT
    return ROUTE_PROXY_PROTOCOL_OPENAI


def route_proxy_claude_protocol_for_profile(profile: Profile) -> str:
    if default_wire_api_for_profile(profile) == WIRE_API_ANTHROPIC_MESSAGES:
        return ROUTE_PROXY_PROTOCOL_ANTHROPIC
    return ROUTE_PROXY_PROTOCOL_ANTHROPIC_TO_OPENAI


def route_proxy_rules_for_project(
    project: ProjectRecord,
    codex_profile: Profile,
    claude_profile: Profile,
    codex_protocol: str,
    claude_protocol: str,
    *,
    codex_upstream_source: str = ROUTE_PROXY_UPSTREAM_SOURCE_PROFILE,
    codex_account_pool_group_id: str = "",
    codex_compact_model: str = "",
    codex_manual_upstream_protocol: bool = False,
    claude_upstream_source: str = ROUTE_PROXY_UPSTREAM_SOURCE_PROFILE,
    claude_account_pool_group_id: str = "",
    claude_manual_upstream_protocol: bool = False,
) -> list[RouteProxyRule]:
    codex_conversion_protocols = {
        ROUTE_PROXY_PROTOCOL_OPENAI_CHAT_TO_RESPONSES,
        ROUTE_PROXY_PROTOCOL_OPENAI_RESPONSES_TO_CHAT,
    }
    codex_upstream_model = codex_profile.codex_display_model if codex_protocol in codex_conversion_protocols else ""
    claude_upstream_model = (
        claude_profile.claude_display_model
        if claude_protocol == ROUTE_PROXY_PROTOCOL_ANTHROPIC_TO_OPENAI
        else ""
    )
    return [
        RouteProxyRule.create(
            project_id=project.id,
            client_type=ROUTE_PROXY_CLIENT_CODEX,
            primary_profile_id=codex_profile.id,
            upstream_source=codex_upstream_source,
            account_pool_group_id=codex_account_pool_group_id,
            upstream_protocol=codex_protocol,
            upstream_model=codex_upstream_model,
            compact_model=codex_compact_model,
            manual_upstream_protocol=codex_manual_upstream_protocol,
        ),
        RouteProxyRule.create(
            project_id=project.id,
            client_type=ROUTE_PROXY_CLIENT_CLAUDE,
            primary_profile_id=claude_profile.id,
            upstream_source=claude_upstream_source,
            account_pool_group_id=claude_account_pool_group_id,
            upstream_protocol=claude_protocol,
            upstream_model=claude_upstream_model,
            manual_upstream_protocol=claude_manual_upstream_protocol,
        ),
    ]


def route_proxy_rules_for_project_profiles(
    project: ProjectRecord,
    codex_profile: Profile,
    claude_profile: Profile,
) -> list[RouteProxyRule]:
    return route_proxy_rules_for_project(
        project,
        codex_profile,
        claude_profile,
        route_proxy_codex_protocol_for_profile(codex_profile),
        route_proxy_claude_protocol_for_profile(claude_profile),
    )


def refresh_route_proxy_rules_for_project(
    settings: RouteProxySettings,
    project: ProjectRecord,
    codex_profile: Profile,
    claude_profile: Profile,
) -> RouteProxySettings:
    if not settings.project_enabled(project.id):
        return settings
    existing_rules = settings.rules_for_project(project.id)
    existing_codex_rule = next(
        (rule for rule in existing_rules if rule.client_type == ROUTE_PROXY_CLIENT_CODEX),
        None,
    )
    existing_claude_rule = next(
        (rule for rule in existing_rules if rule.client_type == ROUTE_PROXY_CLIENT_CLAUDE),
        None,
    )
    codex_protocol = (
        existing_codex_rule.upstream_protocol
        if existing_codex_rule is not None and existing_codex_rule.manual_upstream_protocol
        else route_proxy_codex_protocol_for_profile(codex_profile)
    )
    claude_protocol = (
        existing_claude_rule.upstream_protocol
        if existing_claude_rule is not None and existing_claude_rule.manual_upstream_protocol
        else route_proxy_claude_protocol_for_profile(claude_profile)
    )
    refreshed = settings.without_project_rules(project.id)
    refreshed.rules.extend(
        route_proxy_rules_for_project(
            project,
            codex_profile,
            claude_profile,
            codex_protocol,
            claude_protocol,
            codex_upstream_source=(
                existing_codex_rule.upstream_source if existing_codex_rule is not None else ROUTE_PROXY_UPSTREAM_SOURCE_PROFILE
            ),
            codex_account_pool_group_id=(
                existing_codex_rule.account_pool_group_id if existing_codex_rule is not None else ""
            ),
            codex_compact_model=existing_codex_rule.compact_model if existing_codex_rule is not None else "",
            codex_manual_upstream_protocol=(
                existing_codex_rule.manual_upstream_protocol if existing_codex_rule is not None else False
            ),
            claude_upstream_source=(
                existing_claude_rule.upstream_source if existing_claude_rule is not None else ROUTE_PROXY_UPSTREAM_SOURCE_PROFILE
            ),
            claude_account_pool_group_id=(
                existing_claude_rule.account_pool_group_id if existing_claude_rule is not None else ""
            ),
            claude_manual_upstream_protocol=(
                existing_claude_rule.manual_upstream_protocol if existing_claude_rule is not None else False
            ),
        )
    )
    return refreshed


def route_proxy_base_url_for_project(settings: RouteProxySettings, project: ProjectRecord) -> str | None:
    if not settings.project_enabled(project.id):
        return None
    return settings.project_base_url(project.id)


def route_proxy_account_pool_choices(
    account_pool_settings: AccountPoolSettings,
    *,
    current_codex_label: str = "",
    current_claude_label: str = "",
) -> RouteProxyAccountPoolChoices:
    account_pool_settings.ensure_default_group()
    codex_choices: dict[str, str] = {}
    claude_choices: dict[str, str] = {}
    codex_labels: list[str] = []
    claude_labels: list[str] = []
    for group in account_pool_settings.groups:
        label = account_pool_group_label(group, account_pool_settings)
        if group.pool_type == ACCOUNT_POOL_GROUP_TYPE_CLAUDE:
            claude_labels.append(label)
            claude_choices[label] = group.id
        else:
            codex_labels.append(label)
            codex_choices[label] = group.id
    selected_codex_label = current_codex_label if current_codex_label in codex_choices else (codex_labels[0] if codex_labels else "")
    selected_claude_label = (
        current_claude_label if current_claude_label in claude_choices else (claude_labels[0] if claude_labels else "")
    )
    return RouteProxyAccountPoolChoices(
        codex_choices=codex_choices,
        claude_choices=claude_choices,
        codex_labels=codex_labels,
        claude_labels=claude_labels,
        selected_codex_label=selected_codex_label,
        selected_claude_label=selected_claude_label,
    )


def route_proxy_group_label_for_id(group_id: str, choices: dict[str, str]) -> str:
    return next((label for label, value in choices.items() if value == group_id), "")


def route_proxy_status_text(settings: RouteProxySettings, *, is_running: bool) -> str:
    if is_running:
        return f"代理运行中：{settings.base_url}"
    return f"代理未启动：{settings.base_url}"


def route_proxy_project_rows(
    settings: RouteProxySettings,
    projects: list[ProjectRecord],
    *,
    profile_by_id: Callable[[str | None], Profile | None],
    project_codex_profile_id: Callable[[ProjectRecord], str],
    project_claude_profile_id: Callable[[ProjectRecord], str],
    project_account_pool_group_name: Callable[[str], str],
) -> list[RouteProxyProjectRow]:
    rows: list[RouteProxyProjectRow] = []
    for project in projects:
        codex_profile = profile_by_id(project_codex_profile_id(project))
        claude_profile = profile_by_id(project_claude_profile_id(project))
        rows.append(
            RouteProxyProjectRow(
                project_id=project.id,
                values=(
                    project.name,
                    compact_text(codex_profile.name if codex_profile else "绑定配置已删除", 16),
                    compact_text(claude_profile.name if claude_profile else "绑定配置已删除", 16),
                    compact_text(project_account_pool_group_name(project.id), 14),
                    "已启用" if settings.project_enabled(project.id) else "未启用",
                ),
            )
        )
    return rows


def normalize_route_proxy_settings_form(
    settings: RouteProxySettings,
    *,
    host_value: str,
    port_value: str,
    strategy_label: str,
    strategy_values: dict[str, str],
    upstream_timeout_value,
) -> RouteProxySettingsForm:
    host = host_value.strip() or settings.host
    raw_port = port_value.strip() or str(settings.port)
    try:
        int(raw_port)
    except ValueError as exc:
        raise ValueError("路由端口必须是数字。") from exc
    return RouteProxySettingsForm(
        host=host,
        port=normalize_route_proxy_port(raw_port),
        account_pool_strategy=normalize_route_proxy_account_pool_strategy(
            strategy_values.get(strategy_label, strategy_label)
        ),
        upstream_timeout_seconds=normalize_route_proxy_upstream_timeout_seconds(upstream_timeout_value),
    )


def apply_route_proxy_settings_form(
    settings: RouteProxySettings,
    form: RouteProxySettingsForm,
) -> None:
    settings.host = form.host
    settings.port = form.port
    settings.account_pool_strategy = form.account_pool_strategy
    settings.upstream_timeout_seconds = form.upstream_timeout_seconds


def resolve_route_proxy_project_rule_form(
    account_pool_settings: AccountPoolSettings,
    *,
    codex_protocol: str,
    codex_source_label: str,
    codex_source_values: dict[str, str],
    codex_group_label: str,
    codex_group_choices: dict[str, str],
    claude_protocol: str,
    claude_source_label: str,
    claude_source_values: dict[str, str],
    claude_group_label: str,
    claude_group_choices: dict[str, str],
    compact_model: str,
) -> RouteProxyProjectRuleForm:
    codex_source = codex_source_values.get(codex_source_label, codex_source_label)
    codex_account_pool_group_id = codex_group_choices.get(codex_group_label, "")
    if codex_source == ROUTE_PROXY_UPSTREAM_SOURCE_ACCOUNT_POOL and not codex_account_pool_group_id:
        group = account_pool_settings.group_by_id(account_pool_settings.selected_group_id)
        if group is None or group.pool_type == ACCOUNT_POOL_GROUP_TYPE_CLAUDE:
            group = next(
                (item for item in account_pool_settings.groups if item.pool_type != ACCOUNT_POOL_GROUP_TYPE_CLAUDE),
                None,
            )
        codex_account_pool_group_id = group.id if group is not None else ""

    claude_source = claude_source_values.get(claude_source_label, claude_source_label)
    claude_account_pool_group_id = claude_group_choices.get(claude_group_label, "")
    if claude_source == ROUTE_PROXY_UPSTREAM_SOURCE_ACCOUNT_POOL and not claude_account_pool_group_id:
        group = next(
            (item for item in account_pool_settings.groups if item.pool_type == ACCOUNT_POOL_GROUP_TYPE_CLAUDE),
            None,
        )
        claude_account_pool_group_id = group.id if group is not None else ""

    codex_pool_group = (
        account_pool_settings.group_by_id(codex_account_pool_group_id)
        if codex_source == ROUTE_PROXY_UPSTREAM_SOURCE_ACCOUNT_POOL
        else None
    )
    codex_pool_model = (
        (codex_pool_group.default_model or DEFAULT_CODEX_MODEL).strip() or DEFAULT_CODEX_MODEL
        if codex_pool_group is not None
        else None
    )

    claude_pool_group = (
        account_pool_settings.group_by_id(claude_account_pool_group_id)
        if claude_source == ROUTE_PROXY_UPSTREAM_SOURCE_ACCOUNT_POOL
        else None
    )
    claude_pool_model = (
        (claude_pool_group.claude_model or DEFAULT_CLAUDE_MODEL).strip() or DEFAULT_CLAUDE_MODEL
        if claude_pool_group is not None
        else None
    )

    return RouteProxyProjectRuleForm(
        codex_protocol=codex_protocol,
        codex_source=codex_source,
        codex_account_pool_group_id=codex_account_pool_group_id,
        claude_protocol=claude_protocol,
        claude_source=claude_source,
        claude_account_pool_group_id=claude_account_pool_group_id,
        compact_model=compact_model,
        codex_pool_model=codex_pool_model,
        claude_pool_model=claude_pool_model,
    )


def build_route_proxy_project_enable_plan(
    settings: RouteProxySettings,
    account_pool_settings: AccountPoolSettings,
    project: ProjectRecord,
    codex_profile: Profile,
    claude_profile: Profile,
) -> RouteProxyProjectEnablePlan:
    rules = route_proxy_rules_for_project_profiles(project, codex_profile, claude_profile)
    selected_group = account_pool_settings.group_by_id(account_pool_settings.selected_group_id)
    codex_protocol = ROUTE_PROXY_PROTOCOL_OPENAI
    claude_protocol = ROUTE_PROXY_PROTOCOL_ANTHROPIC
    for rule in rules:
        if rule.client_type == ROUTE_PROXY_CLIENT_CODEX:
            rule.account_pool_group_id = selected_group.id if selected_group is not None else ""
            codex_protocol = rule.upstream_protocol or ROUTE_PROXY_PROTOCOL_OPENAI
        elif rule.client_type == ROUTE_PROXY_CLIENT_CLAUDE:
            claude_protocol = rule.upstream_protocol or ROUTE_PROXY_PROTOCOL_ANTHROPIC
    updated_settings = settings.without_project_rules(project.id)
    updated_settings.rules.extend(rules)
    return RouteProxyProjectEnablePlan(
        settings=updated_settings,
        codex_protocol=codex_protocol,
        claude_protocol=claude_protocol,
    )


def route_proxy_rule_for_project_client(
    settings: RouteProxySettings,
    project: ProjectRecord,
    client_type: str,
) -> RouteProxyRule | None:
    return next(
        (
            rule
            for rule in settings.rules_for_project(project.id)
            if rule.client_type == client_type
        ),
        None,
    )


def account_pool_group_for_project_client(
    settings: RouteProxySettings,
    account_pool_settings: AccountPoolSettings,
    project: ProjectRecord,
    client_type: str,
) -> AccountPoolGroup | None:
    rule = route_proxy_rule_for_project_client(settings, project, client_type)
    if rule is None or rule.upstream_source != ROUTE_PROXY_UPSTREAM_SOURCE_ACCOUNT_POOL:
        return None
    group = account_pool_settings.group_by_id(rule.account_pool_group_id)
    if group is None or group.pool_type != client_type:
        return None
    return group


def codex_model_override_for_project(
    settings: RouteProxySettings,
    account_pool_settings: AccountPoolSettings,
    project: ProjectRecord,
) -> str | None:
    group = account_pool_group_for_project_client(
        settings,
        account_pool_settings,
        project,
        ROUTE_PROXY_CLIENT_CODEX,
    )
    if group is None:
        return None
    return (group.default_model or DEFAULT_CODEX_MODEL).strip() or DEFAULT_CODEX_MODEL


def claude_model_overrides_for_project(
    settings: RouteProxySettings,
    account_pool_settings: AccountPoolSettings,
    project: ProjectRecord,
) -> tuple[str | None, str | None]:
    group = account_pool_group_for_project_client(
        settings,
        account_pool_settings,
        project,
        ROUTE_PROXY_CLIENT_CLAUDE,
    )
    if group is None:
        return None, None
    model = (group.claude_model or DEFAULT_CLAUDE_MODEL).strip() or DEFAULT_CLAUDE_MODEL
    fallback = (group.claude_fallback_model or DEFAULT_CLAUDE_FALLBACK_MODEL).strip() or DEFAULT_CLAUDE_FALLBACK_MODEL
    return model, fallback


def refresh_route_proxy_upstream_models(
    settings: RouteProxySettings,
    project: ProjectRecord,
    codex_profile: Profile | None,
    claude_profile: Profile | None,
    *,
    codex_pool_model: str | None = None,
    claude_pool_model: str | None = None,
) -> None:
    codex_conversion_protocols = {
        ROUTE_PROXY_PROTOCOL_OPENAI_CHAT_TO_RESPONSES,
        ROUTE_PROXY_PROTOCOL_OPENAI_RESPONSES_TO_CHAT,
    }
    for rule in settings.rules_for_project(project.id):
        if rule.client_type == ROUTE_PROXY_CLIENT_CODEX and codex_profile is not None:
            rule.upstream_model = (
                codex_pool_model or codex_profile.codex_display_model
                if rule.upstream_protocol in codex_conversion_protocols
                else ""
            )
        elif rule.client_type == ROUTE_PROXY_CLIENT_CLAUDE and claude_profile is not None:
            rule.upstream_model = (
                claude_pool_model or claude_profile.claude_display_model
                if rule.upstream_protocol == ROUTE_PROXY_PROTOCOL_ANTHROPIC_TO_OPENAI
                else ""
            )


def apply_route_proxy_project_rules(
    settings: RouteProxySettings,
    project: ProjectRecord,
    *,
    codex_protocol: str,
    codex_source: str,
    codex_account_pool_group_id: str,
    claude_protocol: str,
    claude_source: str,
    claude_account_pool_group_id: str,
    compact_model: str,
    codex_profile: Profile | None,
    claude_profile: Profile | None,
    codex_pool_model: str | None = None,
    claude_pool_model: str | None = None,
) -> bool:
    changed = False
    normalized_codex_protocol = normalize_route_proxy_protocol(
        codex_protocol,
        ROUTE_PROXY_CLIENT_CODEX,
    )
    normalized_codex_source = normalize_route_proxy_upstream_source(codex_source)
    normalized_claude_protocol = normalize_route_proxy_protocol(
        claude_protocol,
        ROUTE_PROXY_CLIENT_CLAUDE,
    )
    normalized_claude_source = normalize_route_proxy_upstream_source(claude_source)

    for rule in settings.rules_for_project(project.id):
        if rule.client_type == ROUTE_PROXY_CLIENT_CODEX:
            rule.upstream_source = normalized_codex_source
            rule.account_pool_group_id = (
                codex_account_pool_group_id
                if normalized_codex_source == ROUTE_PROXY_UPSTREAM_SOURCE_ACCOUNT_POOL
                else ""
            )
            rule.upstream_protocol = normalized_codex_protocol
            rule.compact_model = compact_model
            rule.manual_upstream_protocol = True
            changed = True
        elif rule.client_type == ROUTE_PROXY_CLIENT_CLAUDE:
            rule.upstream_source = normalized_claude_source
            rule.account_pool_group_id = (
                claude_account_pool_group_id
                if normalized_claude_source == ROUTE_PROXY_UPSTREAM_SOURCE_ACCOUNT_POOL
                else ""
            )
            rule.upstream_protocol = normalized_claude_protocol
            rule.manual_upstream_protocol = True
            changed = True
    if changed:
        refresh_route_proxy_upstream_models(
            settings,
            project,
            codex_profile,
            claude_profile,
            codex_pool_model=codex_pool_model,
            claude_pool_model=claude_pool_model,
        )
    return changed


def route_proxy_detail_display(
    project: ProjectRecord | None,
    settings: RouteProxySettings,
    account_pool_settings: AccountPoolSettings,
    *,
    profile_by_id: Callable[[str], Profile | None],
    codex_choices: dict[str, str],
    claude_choices: dict[str, str],
) -> RouteProxyDetailDisplay:
    default_source_label = CODEX_ROUTE_PROXY_UPSTREAM_SOURCE_LABELS[ROUTE_PROXY_UPSTREAM_SOURCE_PROFILE]
    if project is None:
        return RouteProxyDetailDisplay(
            selected_project_text="未选择项目",
            selected_rules_text="-",
            codex_upstream_source_label=default_source_label,
            claude_upstream_source_label=default_source_label,
            codex_protocol=ROUTE_PROXY_PROTOCOL_OPENAI,
            claude_protocol=ROUTE_PROXY_PROTOCOL_ANTHROPIC,
            codex_compact_model="",
            codex_group_label="",
            claude_group_label="",
        )

    rules = settings.rules_for_project(project.id)
    if not rules:
        return RouteProxyDetailDisplay(
            selected_project_text=f"{project.name}    {project.project_dir}",
            selected_rules_text="未配置代理规则",
            codex_upstream_source_label=default_source_label,
            claude_upstream_source_label=default_source_label,
            codex_protocol=ROUTE_PROXY_PROTOCOL_OPENAI,
            claude_protocol=ROUTE_PROXY_PROTOCOL_ANTHROPIC,
            codex_compact_model="",
            codex_group_label="",
            claude_group_label="",
        )

    summaries: list[str] = []
    codex_upstream_source_label = default_source_label
    claude_upstream_source_label = default_source_label
    codex_protocol = ROUTE_PROXY_PROTOCOL_OPENAI
    claude_protocol = ROUTE_PROXY_PROTOCOL_ANTHROPIC
    codex_compact_model = ""
    codex_group_label = ""
    claude_group_label = ""

    for rule in rules:
        source_label = CODEX_ROUTE_PROXY_UPSTREAM_SOURCE_LABELS.get(rule.upstream_source, "默认配置")
        group = account_pool_settings.group_by_id(rule.account_pool_group_id)
        if rule.client_type == ROUTE_PROXY_CLIENT_CODEX:
            codex_group_label = route_proxy_group_label_for_id(rule.account_pool_group_id, codex_choices)
            codex_upstream_source_label = CODEX_ROUTE_PROXY_UPSTREAM_SOURCE_LABELS.get(
                normalize_route_proxy_upstream_source(rule.upstream_source),
                default_source_label,
            )
            codex_protocol = rule.upstream_protocol or ROUTE_PROXY_PROTOCOL_OPENAI
            codex_compact_model = rule.compact_model
        elif rule.client_type == ROUTE_PROXY_CLIENT_CLAUDE:
            claude_group_label = route_proxy_group_label_for_id(rule.account_pool_group_id, claude_choices)
            claude_upstream_source_label = CODEX_ROUTE_PROXY_UPSTREAM_SOURCE_LABELS.get(
                normalize_route_proxy_upstream_source(rule.upstream_source),
                default_source_label,
            )
            claude_protocol = rule.upstream_protocol or ROUTE_PROXY_PROTOCOL_ANTHROPIC
        profile = profile_by_id(rule.primary_profile_id)
        profile_name = profile.name if profile is not None else "绑定配置已删除"
        compact_suffix = f" / compact: {rule.compact_model}" if rule.client_type == ROUTE_PROXY_CLIENT_CODEX and rule.compact_model else ""
        if rule.upstream_source == ROUTE_PROXY_UPSTREAM_SOURCE_ACCOUNT_POOL:
            group_name = group.name if group is not None else "号池组已删除"
            source_label = f"{source_label}:{group_name}"
            profile_name = group_name
        source_suffix = f" / {source_label}"
        summaries.append(f"{rule.client_type}{source_suffix} / {rule.model_pattern} / {rule.upstream_protocol}{compact_suffix} -> {profile_name}")

    return RouteProxyDetailDisplay(
        selected_project_text=f"{project.name}    {project.project_dir}",
        selected_rules_text="\n".join(summaries),
        codex_upstream_source_label=codex_upstream_source_label,
        claude_upstream_source_label=claude_upstream_source_label,
        codex_protocol=codex_protocol,
        claude_protocol=claude_protocol,
        codex_compact_model=codex_compact_model,
        codex_group_label=codex_group_label,
        claude_group_label=claude_group_label,
    )
