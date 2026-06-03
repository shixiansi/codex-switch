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
        ),
        RouteProxyRule.create(
            project_id=project.id,
            client_type=ROUTE_PROXY_CLIENT_CLAUDE,
            primary_profile_id=claude_profile.id,
            upstream_protocol=claude_protocol,
            upstream_model=claude_upstream_model,
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
    refreshed = settings.without_project_rules(project.id)
    refreshed.rules.extend(
        route_proxy_rules_for_project_profiles(
            project,
            codex_profile,
            claude_profile,
        )
    )
    return refreshed


def route_proxy_base_url_for_project(settings: RouteProxySettings, project: ProjectRecord) -> str | None:
    if not settings.project_enabled(project.id):
        return None
    return settings.project_base_url(project.id)
