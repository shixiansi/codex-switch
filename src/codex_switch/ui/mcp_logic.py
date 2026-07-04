from __future__ import annotations

from codex_switch.codex_config import (
    PROJECT_ROOT_PLACEHOLDER,
    mcp_server_names_from_toml,
    render_mcp_servers_toml,
)
from codex_switch.ui.utils import compact_text


def safe_mcp_server_names(raw_toml: str | None) -> list[str]:
    try:
        return mcp_server_names_from_toml(raw_toml)
    except ValueError:
        return []


def mcp_summary(raw_toml: str | None) -> str:
    names = safe_mcp_server_names(raw_toml)
    if not names:
        return "\u672a\u914d\u7f6e"
    label = ", ".join(names[:4])
    suffix = " \u2026" if len(names) > 4 else ""
    return f"{len(names)} \u4e2a\u670d\u52a1\uff1a{label}{suffix}"


def mcp_contains_project_root(value) -> bool:
    if isinstance(value, str):
        return PROJECT_ROOT_PLACEHOLDER in value
    if isinstance(value, list):
        return any(mcp_contains_project_root(item) for item in value)
    if isinstance(value, dict):
        return any(mcp_contains_project_root(item) for item in value.values())
    return False


def mcp_list_summary(value, limit: int = 36) -> str:
    if not isinstance(value, list) or not value:
        return "-"
    return compact_text(" ".join(str(item) for item in value), limit)


def mcp_env_summary(value, limit: int = 28) -> str:
    if not isinstance(value, dict) or not value:
        return "-"
    return compact_text(", ".join(str(key) for key in value.keys()), limit)


def render_mcp_preview(server_name: str | None, page_servers: dict[str, dict]) -> str:
    if not server_name:
        return ""
    server_config = page_servers.get(server_name)
    if not isinstance(server_config, dict):
        return ""
    return render_mcp_servers_toml({server_name: server_config})
