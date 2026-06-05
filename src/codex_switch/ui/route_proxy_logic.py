from __future__ import annotations

from codex_switch.chat import (
    WIRE_API_ANTHROPIC_MESSAGES,
    WIRE_API_CHAT_COMPLETIONS,
    WIRE_API_RESPONSES,
    default_wire_api_for_profile,
)
from codex_switch.models import (
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
    codex_compact_model: str = "",
    codex_manual_upstream_protocol: bool = False,
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
            upstream_protocol=codex_protocol,
            upstream_model=codex_upstream_model,
            compact_model=codex_compact_model,
            manual_upstream_protocol=codex_manual_upstream_protocol,
        ),
        RouteProxyRule.create(
            project_id=project.id,
            client_type=ROUTE_PROXY_CLIENT_CLAUDE,
            primary_profile_id=claude_profile.id,
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
            codex_compact_model=existing_codex_rule.compact_model if existing_codex_rule is not None else "",
            codex_manual_upstream_protocol=(
                existing_codex_rule.manual_upstream_protocol if existing_codex_rule is not None else False
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
