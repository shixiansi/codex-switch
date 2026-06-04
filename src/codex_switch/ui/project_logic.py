from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from codex_switch.models import ProjectRecord
from codex_switch.skills import SkillSource, resolve_selected_skill_sources
from codex_switch.ui.utils import project_start_script_paths


@dataclass(frozen=True)
class CodexProjectTemplateOptions:
    project_root: Path
    global_mcp_toml: str
    project_mcp_toml: str
    agents_doc_text: str
    route_proxy_base_url: str | None
    skill_sources: list[SkillSource]


@dataclass(frozen=True)
class ClaudeProjectTemplateOptions:
    project_root: Path
    project_mcp_toml: str
    agents_doc_text: str
    route_proxy_base_url: str | None


def project_codex_profile_id(project: ProjectRecord) -> str:
    return project.codex_profile_id or project.profile_id


def project_claude_profile_id(project: ProjectRecord) -> str:
    return project.claude_profile_id or project.profile_id


def project_bound_profile_ids(project: ProjectRecord) -> set[str]:
    return {
        profile_id
        for profile_id in (
            project.profile_id,
            project.codex_profile_id,
            project.claude_profile_id,
        )
        if profile_id
    }


def project_codex_binding_changed(previous: ProjectRecord, updated: ProjectRecord) -> bool:
    return (
        updated.profile_id != previous.profile_id
        or updated.codex_profile_id != previous.codex_profile_id
        or updated.project_dir != previous.project_dir
    )


def project_claude_binding_changed(previous: ProjectRecord, updated: ProjectRecord) -> bool:
    return (
        updated.claude_profile_id != previous.claude_profile_id
        or updated.project_dir != previous.project_dir
    )


def project_root_path(project: ProjectRecord) -> Path:
    return Path(project.project_dir)


def project_text_file_path(project: ProjectRecord, relative_path: str) -> Path:
    return project_root_path(project) / relative_path


def codex_project_template_options(
    project: ProjectRecord,
    *,
    project_mcp_toml: str,
    agents_doc_text: str,
    route_proxy_base_url: str | None,
    available_skill_sources: list[SkillSource],
) -> CodexProjectTemplateOptions:
    return CodexProjectTemplateOptions(
        project_root=project_root_path(project),
        global_mcp_toml=project_mcp_toml,
        project_mcp_toml=project_mcp_toml,
        agents_doc_text=agents_doc_text,
        route_proxy_base_url=route_proxy_base_url,
        skill_sources=resolve_selected_skill_sources(available_skill_sources, project.skill_names),
    )


def claude_project_template_options(
    project: ProjectRecord,
    *,
    project_mcp_toml: str,
    agents_doc_text: str,
    route_proxy_base_url: str | None,
) -> ClaudeProjectTemplateOptions:
    return ClaudeProjectTemplateOptions(
        project_root=project_root_path(project),
        project_mcp_toml=project_mcp_toml,
        agents_doc_text=agents_doc_text,
        route_proxy_base_url=route_proxy_base_url,
    )


def project_codex_script_paths(project: ProjectRecord) -> tuple[Path, Path]:
    return project_start_script_paths(project.project_dir)


def preferred_project_script_path(project: ProjectRecord) -> Path:
    ps1_path, cmd_path = project_codex_script_paths(project)
    if cmd_path.exists():
        return cmd_path
    return ps1_path


def project_vscode_open_command(project: ProjectRecord) -> tuple[str, ...]:
    return ("cmd.exe", "/c", "code.cmd", str(project_root_path(project)))


def project_custom_run_command(project: ProjectRecord) -> tuple[str, ...] | None:
    run_command = project.run_command.strip()
    if not run_command:
        return None
    return ("cmd.exe", "/k", run_command)


def project_codex_vscode_command(ps1_path: Path) -> tuple[str, ...]:
    return ("powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps1_path))


def project_codex_cmd_command(cmd_path: Path) -> tuple[str, ...]:
    return ("cmd.exe", "/k", str(cmd_path))


def project_claude_cmd_command() -> tuple[str, ...]:
    return ("cmd.exe", "/k", "claude")
