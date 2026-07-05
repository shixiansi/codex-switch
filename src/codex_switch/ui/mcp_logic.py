from __future__ import annotations

from dataclasses import dataclass

from codex_switch.codex_config import (
    PROJECT_ROOT_PLACEHOLDER,
    mcp_server_names_from_toml,
    render_mcp_servers_toml,
)
from codex_switch.ui.utils import compact_text


@dataclass(frozen=True)
class McpServerRow:
    server_name: str
    values: tuple[str, str, str, str, str, str, str]


@dataclass(frozen=True)
class McpTabDisplay:
    rows: list[McpServerRow]
    selected_name: str | None
    hint_text: str


@dataclass(frozen=True)
class McpDetailDisplay:
    selected_name_text: str
    summary_text: str
    preview_text: str


@dataclass(frozen=True)
class McpMutationResult:
    page_servers: dict[str, dict]
    selected_name: str | None


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


def mcp_server_rows(page_servers: dict[str, dict]) -> list[McpServerRow]:
    rows: list[McpServerRow] = []
    for server_name, server_config in sorted(page_servers.items()):
        rows.append(
            McpServerRow(
                server_name=server_name,
                values=(
                    server_name,
                    server_config.get("type", "-") or "-",
                    compact_text(str(server_config.get("command", "-") or "-"), 24),
                    mcp_list_summary(server_config.get("args")),
                    compact_text(str(server_config.get("cwd", "-") or "-"), 24),
                    mcp_env_summary(server_config.get("env")),
                    "是" if mcp_contains_project_root(server_config) else "否",
                ),
            )
        )
    return rows


def mcp_tab_display(
    page_servers: dict[str, dict],
    *,
    selected_name: str | None,
    global_mcp_opt_out: bool,
) -> McpTabDisplay:
    rows = mcp_server_rows(page_servers)
    if selected_name not in page_servers:
        selected_name = rows[0].server_name if rows else None
    hint_text = "全局 MCP 已显式关闭。" if global_mcp_opt_out else f"共 {len(page_servers)} 个 MCP 服务。"
    return McpTabDisplay(
        rows=rows,
        selected_name=selected_name,
        hint_text=hint_text,
    )


def mcp_detail_display(server_name: str | None, page_servers: dict[str, dict]) -> McpDetailDisplay:
    if not server_name:
        return McpDetailDisplay(
            selected_name_text="未选择 MCP 服务",
            summary_text="选择某个工具后查看配置预览。",
            preview_text="",
        )
    server_config = page_servers.get(server_name, {})
    args_count = len(server_config.get("args", [])) if isinstance(server_config.get("args"), list) else 0
    env_count = len(server_config.get("env", {})) if isinstance(server_config.get("env"), dict) else 0
    return McpDetailDisplay(
        selected_name_text=server_name,
        summary_text=f"type: {server_config.get('type', '-') or '-'}    args: {args_count}    env: {env_count}",
        preview_text=render_mcp_preview(server_name, page_servers),
    )


def mcp_name_conflict_error(
    page_servers: dict[str, dict],
    server_name: str,
    *,
    current_name: str | None = None,
) -> str | None:
    if server_name in page_servers and server_name != current_name:
        return f"MCP 工具“{server_name}”已经存在。"
    return None


def mcp_collection_after_upsert(
    page_servers: dict[str, dict],
    server_name: str,
    config: dict,
    *,
    current_name: str | None = None,
) -> McpMutationResult:
    updated_servers = dict(page_servers)
    if current_name and current_name != server_name:
        updated_servers.pop(current_name, None)
    updated_servers[server_name] = config
    return McpMutationResult(
        page_servers=updated_servers,
        selected_name=server_name,
    )


def mcp_collection_after_delete(
    page_servers: dict[str, dict],
    server_name: str,
) -> McpMutationResult:
    updated_servers = dict(page_servers)
    updated_servers.pop(server_name, None)
    next_name = next(iter(updated_servers), None)
    return McpMutationResult(
        page_servers=updated_servers,
        selected_name=next_name,
    )
