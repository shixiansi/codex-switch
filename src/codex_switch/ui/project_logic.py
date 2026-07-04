from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from codex_switch.models import Profile, ProjectRecord, SkillDefinition, SkillGroup
from codex_switch.project_template import ProjectTemplateStatus
from codex_switch.skills import SkillSource, resolve_selected_skill_sources, skill_selection_summary
from codex_switch.ui.utils import compact_text, project_start_script_paths


@dataclass(frozen=True)
class CodexProjectTemplateOptions:
    project_root: Path
    global_mcp_toml: str
    project_mcp_toml: str
    agents_doc_text: str
    route_proxy_base_url: str | None
    skill_sources: list[SkillSource]
    skill_definitions: list[SkillDefinition]


@dataclass(frozen=True)
class ClaudeProjectTemplateOptions:
    project_root: Path
    project_mcp_toml: str
    agents_doc_text: str
    route_proxy_base_url: str | None


@dataclass(frozen=True)
class ProjectTemplateDisplay:
    backup_text: str
    generated_text: str
    badge_text: str
    badge_state: str


@dataclass(frozen=True)
class ProjectTreeRow:
    project_id: str
    values: tuple[str, str, str, str, str]


@dataclass(frozen=True)
class ProjectTabDisplay:
    selected_project_id: str | None
    rows: list[ProjectTreeRow]
    generated_count: int
    hint_text: str


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


def resolve_selected_project_id(projects: list[ProjectRecord], selected_project_id: str | None) -> str | None:
    if selected_project_id and any(project.id == selected_project_id for project in projects):
        return selected_project_id
    return projects[0].id if projects else None


def project_github_label(project: ProjectRecord, *, default_ref: str) -> str:
    if not project.github_repo:
        return "未配置"
    github_ref = (project.github_ref or "").strip() or default_ref
    return f"{project.github_repo} @ {github_ref}"


def project_github_update_label(project: ProjectRecord) -> str:
    commit = project.github_last_sync_commit[:12] if project.github_last_sync_commit else "未同步"
    mode = "自动" if project.github_auto_update else "手动"
    return f"{mode} / {commit}"


def project_mcp_selection_summary(
    project: ProjectRecord | None,
    *,
    effective_project_mcp_toml: str,
    mcp_summary: Callable[[str | None], str],
) -> str:
    if not project:
        return "-"
    if project.mcp_server_names is None:
        return mcp_summary(effective_project_mcp_toml)
    if not project.mcp_server_names:
        return "未配置"
    label = ", ".join(project.mcp_server_names[:4])
    suffix = " …" if len(project.mcp_server_names) > 4 else ""
    return f"{len(project.mcp_server_names)} 个服务：{label}{suffix}"


def project_skill_selection_summary(
    project: ProjectRecord | None,
    *,
    groups: list[SkillGroup],
    available_skill_sources: list[SkillSource],
) -> str:
    if not project:
        return "-"
    if project.skill_group_ids is not None:
        group_by_id = {group.id: group for group in groups}
        selected_groups = [
            group_by_id[group_id]
            for group_id in project.skill_group_ids
            if group_id in group_by_id
        ]
        if not selected_groups:
            return "未配置"
        skill_count = sum(len(group.skills) for group in selected_groups)
        names = ", ".join(group.name for group in selected_groups[:4])
        suffix = " ..." if len(selected_groups) > 4 else ""
        return f"{len(selected_groups)} 组 / {skill_count} 个技能：{names}{suffix}"
    return skill_selection_summary(available_skill_sources, project.skill_names)


def project_codex_profile_texts(
    profile: Profile | None,
    *,
    key_summary: Callable[[Profile], str],
) -> tuple[str, str, str]:
    if profile is None:
        return "绑定配置已删除", "-", "-"
    return (
        f"{profile.name} / {profile.vendor_label}",
        profile.codex_display_model,
        key_summary(profile),
    )


def project_claude_profile_texts(
    profile: Profile | None,
    *,
    key_summary: Callable[[Profile], str],
) -> tuple[str, str, str]:
    if profile is None:
        return "绑定配置已删除", "-", "-"
    return (
        f"{profile.name} / {profile.vendor_label}",
        f"{profile.claude_display_model} / 兜底：{profile.claude_display_fallback_model}",
        key_summary(profile),
    )


def project_template_display(
    *,
    project_root_exists: bool,
    status: ProjectTemplateStatus | None,
) -> ProjectTemplateDisplay:
    if not project_root_exists:
        return ProjectTemplateDisplay(
            backup_text="项目目录不存在",
            generated_text="项目目录不存在，尚未生成模板。",
            badge_text="目录缺失",
            badge_state="warning",
        )
    if status is None:
        return ProjectTemplateDisplay(
            backup_text="暂无备份",
            generated_text="尚未生成项目模板。",
            badge_text="未生成",
            badge_state="neutral",
        )
    backup_text = str(status.backup_dir) if status.backup_dir else "暂无备份"
    if status.generated_paths:
        preview = ", ".join(path.name for path in status.generated_paths[:4])
        suffix = " …" if len(status.generated_paths) > 4 else ""
        return ProjectTemplateDisplay(
            backup_text=backup_text,
            generated_text=f"{len(status.generated_paths)} 个文件：{preview}{suffix}",
            badge_text="已生成",
            badge_state="success",
        )
    return ProjectTemplateDisplay(
        backup_text=backup_text,
        generated_text="尚未生成项目模板。",
        badge_text="未生成",
        badge_state="neutral",
    )


def project_tab_display(
    projects: list[ProjectRecord],
    *,
    selected_project_id: str | None,
    profile_by_id: Callable[[str | None], Profile | None],
    project_codex_profile_id: Callable[[ProjectRecord], str],
    project_claude_profile_id: Callable[[ProjectRecord], str],
    project_mcp_summary: Callable[[ProjectRecord], str],
    project_status: Callable[[ProjectRecord], ProjectTemplateStatus | None],
) -> ProjectTabDisplay:
    resolved_selected_id = resolve_selected_project_id(projects, selected_project_id)
    rows: list[ProjectTreeRow] = []
    generated_count = 0

    for project in projects:
        codex_profile = profile_by_id(project_codex_profile_id(project))
        claude_profile = profile_by_id(project_claude_profile_id(project))
        codex_name = codex_profile.name if codex_profile else "绑定配置已删除"
        claude_name = claude_profile.name if claude_profile else "绑定配置已删除"
        rows.append(
            ProjectTreeRow(
                project_id=project.id,
                values=(
                    project.name,
                    compact_text(project.project_dir, 42),
                    compact_text(codex_name, 16),
                    compact_text(claude_name, 16),
                    compact_text(project_mcp_summary(project), 16),
                ),
            )
        )
        status = project_status(project)
        if status is not None and status.generated_paths:
            generated_count += 1

    return ProjectTabDisplay(
        selected_project_id=resolved_selected_id,
        rows=rows,
        generated_count=generated_count,
        hint_text=f"共 {len(projects)} 个项目，已生成模板 {generated_count} 个。",
    )


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
        skill_definitions=list(project.skills),
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
