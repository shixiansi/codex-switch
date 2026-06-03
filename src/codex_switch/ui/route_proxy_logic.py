from __future__ import annotations

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


def _route_proxy_protocol_for_project(
    settings: RouteProxySettings,
    project_id: str,
    client_type: str,
    default_protocol: str,
) -> str:
    for rule in settings.rules_for_project(project_id):
        if rule.client_type == client_type:
            return rule.upstream_protocol
    return default_protocol


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


def refresh_route_proxy_rules_for_project(
    settings: RouteProxySettings,
    project: ProjectRecord,
    codex_profile: Profile,
    claude_profile: Profile,
) -> RouteProxySettings:
    if not settings.project_enabled(project.id):
        return settings
    codex_protocol = _route_proxy_protocol_for_project(
        settings,
        project.id,
        ROUTE_PROXY_CLIENT_CODEX,
        ROUTE_PROXY_PROTOCOL_OPENAI,
    )
    claude_protocol = _route_proxy_protocol_for_project(
        settings,
        project.id,
        ROUTE_PROXY_CLIENT_CLAUDE,
        ROUTE_PROXY_PROTOCOL_ANTHROPIC,
    )
    refreshed = settings.without_project_rules(project.id)
    refreshed.rules.extend(
        route_proxy_rules_for_project(
            project,
            codex_profile,
            claude_profile,
            codex_protocol,
            claude_protocol,
        )
    )
    return refreshed


def route_proxy_base_url_for_project(settings: RouteProxySettings, project: ProjectRecord) -> str | None:
    if not settings.project_enabled(project.id):
        return None
    return settings.project_base_url(project.id)


def route_proxy_codex_wire_api_override(protocol: str) -> str | None:
    if protocol == ROUTE_PROXY_PROTOCOL_OPENAI_CHAT_TO_RESPONSES:
        return "chat_completions"
    if protocol == ROUTE_PROXY_PROTOCOL_OPENAI_RESPONSES_TO_CHAT:
        return "responses"
    return None


def route_proxy_codex_wire_api_override_for_project(
    settings: RouteProxySettings,
    project: ProjectRecord,
) -> str | None:
    for rule in settings.rules_for_project(project.id):
        if rule.enabled and rule.client_type == ROUTE_PROXY_CLIENT_CODEX:
            return route_proxy_codex_wire_api_override(rule.upstream_protocol)
    return None
