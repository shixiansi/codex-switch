from __future__ import annotations

import json

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable

from codex_switch.models import Profile, ProjectRecord, SkillDefinition, SkillGroup
from codex_switch.project_template import ProjectTemplateResult, ProjectTemplateStatus
from codex_switch.skills import SkillSource, resolve_selected_skill_sources, skill_selection_summary
from codex_switch.ui.utils import compact_text, project_start_script_paths

PROJECT_METADATA_RELATIVE_PATHS = (
    Path("codex-switch-project.json"),
    Path("project-skills.json"),
    Path(".codex-switch") / "project.json",
)


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
class CodexTemplateExecutionPlan:
    project_name: str
    project_root: Path
    codex_profile: Profile
    claude_profile: Profile | None
    global_mcp_toml: str
    project_mcp_toml: str
    agents_doc_text: str
    route_proxy_base_url: str | None
    codex_model_override: str | None
    claude_model_override: str | None
    claude_fallback_model_override: str | None
    skill_sources: list[SkillSource]
    skill_definitions: list[SkillDefinition]


@dataclass(frozen=True)
class ClaudeTemplateExecutionPlan:
    project_name: str
    project_root: Path
    claude_profile: Profile
    project_mcp_toml: str
    agents_doc_text: str
    route_proxy_base_url: str | None
    model_override: str | None
    fallback_model_override: str | None


@dataclass(frozen=True)
class ProjectTemplateRunSpec:
    method_name: str
    args: tuple[object, ...]
    kwargs: dict[str, object]
    success_status: str
    failure_status: str
    failure_message_prefix: str


@dataclass(frozen=True)
class ProjectTemplateDisplay:
    backup_text: str
    generated_text: str
    badge_text: str
    badge_state: str


@dataclass(frozen=True)
class ProjectDetailDisplay:
    selected_name_text: str
    selected_dir_text: str
    selected_codex_profile_text: str
    selected_claude_profile_text: str
    selected_codex_model_text: str
    selected_claude_model_text: str
    selected_codex_key_text: str
    selected_claude_key_text: str
    backup_text: str
    generated_text: str
    script_text: str
    run_text: str
    github_text: str
    github_update_text: str
    mcp_text: str
    skills_text: str
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


@dataclass(frozen=True)
class ProjectFileEditPlan:
    path: Path
    title: str
    missing_message: str


@dataclass(frozen=True)
class ProjectTextFileEditSession:
    path: Path
    title: str
    subtitle: str
    initial_text: str


@dataclass(frozen=True)
class ProjectLaunchPlan:
    command: tuple[str, ...]
    cwd: Path
    success_status: str
    required_path: Path | None = None
    missing_message: str | None = None


@dataclass(frozen=True)
class ProjectLaunchExecutionResult:
    launched: bool
    status_text: str | None = None
    missing_message: str | None = None
    failure_detail: str | None = None


@dataclass(frozen=True)
class ProjectEditUpdate:
    project: ProjectRecord
    codex_binding_changed: bool
    claude_binding_changed: bool


@dataclass(frozen=True)
class ProjectEditApplication:
    project: ProjectRecord
    sync_codex: bool
    sync_claude: bool


@dataclass(frozen=True)
class ProjectEditExecutionPlan:
    project: ProjectRecord
    collection: ProjectCollectionUpdate
    sync_codex: bool
    sync_claude: bool
    route_proxy_rules_changed: bool


@dataclass(frozen=True)
class ProjectAddExecutionPlan:
    project: ProjectRecord
    collection: ProjectCollectionUpdate
    status_text: str


@dataclass(frozen=True)
class ProjectDeleteExecutionPlan:
    collection: ProjectCollectionUpdate
    status_text: str


@dataclass(frozen=True)
class ProjectMetadataUpdateResult:
    handled: bool
    project: ProjectRecord
    changed: bool


@dataclass(frozen=True)
class ProjectCollectionUpdate:
    projects: list[ProjectRecord]
    selected_project_id: str | None


@dataclass(frozen=True)
class ProjectBindingSyncPlan:
    project_root: Path
    route_proxy_base_url: str | None
    codex_profile: Profile | None
    codex_model_override: str | None
    claude_profile: Profile | None
    claude_model_override: str | None
    claude_fallback_model_override: str | None
    sync_codex: bool
    sync_claude: bool


@dataclass(frozen=True)
class ProjectBindingSyncTask:
    target: str
    profile: Profile | None
    model_override: str | None
    fallback_model_override: str | None
    missing_message: str
    failure_label: str
    failure_status: str


@dataclass(frozen=True)
class ProjectBindingSyncFailure:
    reason: str
    task: ProjectBindingSyncTask
    detail: str | None = None


@dataclass(frozen=True)
class ProjectBindingSyncExecutionResult:
    updated_paths: list[Path]
    failure: ProjectBindingSyncFailure | None = None


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


def project_codex_config_edit_plan(project: ProjectRecord) -> ProjectFileEditPlan:
    return ProjectFileEditPlan(
        path=project_text_file_path(project, ".codex/home/config.toml"),
        title="修改 config.toml",
        missing_message="未找到 .codex/home/config.toml，请先生成 Codex 模板。",
    )


def project_claude_settings_edit_plan(project: ProjectRecord) -> ProjectFileEditPlan:
    return ProjectFileEditPlan(
        path=project_text_file_path(project, ".claude/settings.local.json"),
        title="修改 settings.local.json",
        missing_message="未找到 .claude/settings.local.json，请先生成 Claude 模板。",
    )


def load_project_text_file_edit_session(
    plan: ProjectFileEditPlan,
    *,
    read_text: Callable[[Path], str],
) -> ProjectTextFileEditSession:
    return ProjectTextFileEditSession(
        path=plan.path,
        title=plan.title,
        subtitle=str(plan.path),
        initial_text=read_text(plan.path),
    )


def normalize_project_text_file_content(content: str) -> str:
    return content.rstrip("\n") + "\n"


def save_project_text_file_content(
    path: Path,
    content: str,
    *,
    write_text: Callable[[Path, str], None],
) -> str:
    write_text(path, normalize_project_text_file_content(content))
    return f"已保存：{path}"


def validate_project_claude_settings_json(content: str) -> dict:
    payload = json.loads(content)
    if not isinstance(payload, dict):
        raise ValueError("settings.local.json 必须是一个 JSON object。")
    return payload


def project_vscode_launch_plan(project: ProjectRecord) -> ProjectLaunchPlan:
    return ProjectLaunchPlan(
        command=project_vscode_open_command(project),
        cwd=project_root_path(project),
        success_status=f"使用 VS Code 打开项目：{project.name}",
    )


def project_custom_run_launch_plan(project: ProjectRecord) -> ProjectLaunchPlan | None:
    command = project_custom_run_command(project)
    if command is None:
        return None
    return ProjectLaunchPlan(
        command=command,
        cwd=project_root_path(project),
        success_status=f"已在新窗口运行项目命令：{project.name}",
    )


def project_codex_vscode_launch_plan(project: ProjectRecord) -> ProjectLaunchPlan:
    ps1_path, _cmd_path = project_codex_script_paths(project)
    return ProjectLaunchPlan(
        command=project_codex_vscode_command(ps1_path),
        cwd=project_root_path(project),
        success_status=f"已通过 PowerShell 启动项目：{project.name}",
        required_path=ps1_path,
        missing_message="未找到 start-codex.ps1，请先生成项目模板。",
    )


def project_codex_cmd_launch_plan(project: ProjectRecord) -> ProjectLaunchPlan:
    _ps1_path, cmd_path = project_codex_script_paths(project)
    return ProjectLaunchPlan(
        command=project_codex_cmd_command(cmd_path),
        cwd=project_root_path(project),
        success_status=f"已通过 CMD 启动项目：{project.name}",
        required_path=cmd_path,
        missing_message="未找到 start-codex.cmd，请先生成项目模板。",
    )


def project_claude_cmd_launch_plan(project: ProjectRecord) -> ProjectLaunchPlan:
    return ProjectLaunchPlan(
        command=project_claude_cmd_command(),
        cwd=project_root_path(project),
        success_status=f"已打开 Claude CMD：{project.name}",
    )


def project_add_prerequisite_error(
    profiles: list[Profile],
    *,
    supports_codex: Callable[[Profile], bool],
    supports_claude: Callable[[Profile], bool],
) -> str | None:
    if not profiles:
        return "请先添加至少一套可用配置。"
    if not any(supports_codex(profile) for profile in profiles) or not any(
        supports_claude(profile) for profile in profiles
    ):
        return "请先准备可用于 Codex 和 Claude 的配置。通用配置可同时用于两侧。"
    return None


def project_duplicate_dir_error(
    duplicate: ProjectRecord | None,
    *,
    current_project_id: str | None = None,
) -> str | None:
    if duplicate is None:
        return None
    if current_project_id is None:
        return "该项目目录已经添加过了。"
    if duplicate.id != current_project_id:
        return "该项目目录已经绑定到另一个项目。"
    return None


def project_from_dialog_result(result: dict) -> ProjectRecord:
    return ProjectRecord.create(
        project_dir=result["project_dir"],
        profile_id=result["profile_id"],
        name=result["name"],
        run_command=result["run_command"],
        mcp_server_names=result["mcp_server_names"],
        skill_names=result["skill_names"],
        skill_group_ids=result["skill_group_ids"],
        skills=result["skills"],
        github_repo=result["github_repo"],
        github_ref=result["github_ref"],
        github_auto_update=result["github_auto_update"],
        codex_profile_id=result["codex_profile_id"],
        claude_profile_id=result["claude_profile_id"],
    )


def project_collection_after_add(
    projects: list[ProjectRecord],
    project: ProjectRecord,
) -> ProjectCollectionUpdate:
    return ProjectCollectionUpdate(
        projects=[*projects, project],
        selected_project_id=project.id,
    )


def project_collection_after_replace(
    projects: list[ProjectRecord],
    updated_project: ProjectRecord,
) -> ProjectCollectionUpdate:
    return ProjectCollectionUpdate(
        projects=[updated_project if project.id == updated_project.id else project for project in projects],
        selected_project_id=updated_project.id,
    )


def project_collection_after_delete(
    projects: list[ProjectRecord],
    *,
    selected_project_id: str | None,
    deleted_project_id: str,
) -> ProjectCollectionUpdate:
    remaining_projects = [project for project in projects if project.id != deleted_project_id]
    resolved_selected_id = selected_project_id
    if resolved_selected_id == deleted_project_id:
        resolved_selected_id = remaining_projects[0].id if remaining_projects else None
    return ProjectCollectionUpdate(
        projects=remaining_projects,
        selected_project_id=resolved_selected_id,
    )


def build_project_add_execution_plan(
    projects: list[ProjectRecord],
    result: dict,
) -> ProjectAddExecutionPlan:
    project = project_from_dialog_result(result)
    collection = project_collection_after_add(projects, project)
    return ProjectAddExecutionPlan(
        project=project,
        collection=collection,
        status_text=f"已新增项目：{project.name}",
    )


def build_project_delete_execution_plan(
    projects: list[ProjectRecord],
    *,
    selected_project_id: str | None,
    project: ProjectRecord,
) -> ProjectDeleteExecutionPlan:
    return ProjectDeleteExecutionPlan(
        collection=project_collection_after_delete(
            projects,
            selected_project_id=selected_project_id,
            deleted_project_id=project.id,
        ),
        status_text=f"已删除项目：{project.name}",
    )


def project_metadata_group_ids(payload: dict, known_group_ids: set[str]) -> list[str] | None:
    raw_group_ids = payload.get("skill_group_ids")
    if raw_group_ids is None:
        raw_group_ids = payload.get("skill_groups")
    if not isinstance(raw_group_ids, list):
        return None
    requested = [str(item).strip() for item in raw_group_ids if str(item).strip()]
    if any(group_id not in known_group_ids for group_id in requested):
        return None
    group_ids: list[str] = []
    for group_id in requested:
        if group_id not in group_ids:
            group_ids.append(group_id)
    return group_ids


def project_metadata_profile_id(
    payload: dict,
    key: str,
    current_id: str,
    profile_by_id: Callable[[str], Profile | None],
    supports_profile: Callable[[Profile], bool],
) -> str:
    raw_profile_id = payload.get(key)
    if raw_profile_id is None:
        raw_profile_id = payload.get("profile_id")
    candidate_id = str(raw_profile_id or "").strip()
    if not candidate_id:
        return current_id
    profile = profile_by_id(candidate_id)
    if profile is None or not supports_profile(profile):
        return current_id
    return profile.id


def project_metadata_profile_ids(
    payload: dict,
    project: ProjectRecord,
    *,
    profile_by_id: Callable[[str], Profile | None],
    supports_codex: Callable[[Profile], bool],
    supports_claude: Callable[[Profile], bool],
) -> tuple[str, str]:
    return (
        project_metadata_profile_id(
            payload,
            "codex_profile_id",
            project_codex_profile_id(project),
            profile_by_id,
            supports_codex,
        ),
        project_metadata_profile_id(
            payload,
            "claude_profile_id",
            project_claude_profile_id(project),
            profile_by_id,
            supports_claude,
        ),
    )


def build_project_edit_application(
    project: ProjectRecord,
    result: dict,
    *,
    updated_at: str,
) -> ProjectEditApplication:
    update = updated_project_from_dialog(project, result, updated_at=updated_at)
    return ProjectEditApplication(
        project=update.project,
        sync_codex=update.codex_binding_changed,
        sync_claude=update.claude_binding_changed,
    )


def build_project_edit_execution_plan(
    project: ProjectRecord,
    result: dict,
    *,
    projects: list[ProjectRecord],
    updated_at: str,
    refresh_route_proxy_rules: Callable[[ProjectRecord], bool],
) -> ProjectEditExecutionPlan:
    application = build_project_edit_application(project, result, updated_at=updated_at)
    route_proxy_rules_changed = False
    if application.sync_codex or application.sync_claude:
        route_proxy_rules_changed = refresh_route_proxy_rules(application.project)
    return ProjectEditExecutionPlan(
        project=application.project,
        collection=project_collection_after_replace(projects, application.project),
        sync_codex=application.sync_codex,
        sync_claude=application.sync_claude,
        route_proxy_rules_changed=route_proxy_rules_changed,
    )


def project_with_metadata_update(
    project: ProjectRecord,
    *,
    skill_group_ids: list[str] | None,
    skills: list[SkillDefinition],
    skill_names: list[str] | None,
    codex_profile_id: str,
    claude_profile_id: str,
    updated_at: str,
) -> ProjectRecord | None:
    profile_id = codex_profile_id or claude_profile_id or project.profile_id
    if (
        project.skill_group_ids == skill_group_ids
        and project.skills == skills
        and project.skill_names == skill_names
        and project_codex_profile_id(project) == codex_profile_id
        and project_claude_profile_id(project) == claude_profile_id
        and project.profile_id == profile_id
    ):
        return None
    return replace(
        project,
        profile_id=profile_id,
        codex_profile_id=codex_profile_id,
        claude_profile_id=claude_profile_id,
        skill_group_ids=skill_group_ids,
        skills=skills,
        skill_names=skill_names,
        updated_at=updated_at,
    )


def resolve_project_metadata_update(
    payload: dict,
    project: ProjectRecord,
    *,
    known_group_ids: set[str],
    expand_skills_for_group_ids: Callable[[list[str]], tuple[list[SkillDefinition], list[str] | None]],
    profile_by_id: Callable[[str], Profile | None],
    supports_codex: Callable[[Profile], bool],
    supports_claude: Callable[[Profile], bool],
    updated_at: str,
) -> ProjectMetadataUpdateResult:
    has_group_metadata = "skill_group_ids" in payload or "skill_groups" in payload
    has_profile_metadata = any(key in payload for key in ("profile_id", "codex_profile_id", "claude_profile_id"))
    if not has_group_metadata and not has_profile_metadata:
        return ProjectMetadataUpdateResult(handled=False, project=project, changed=False)

    if has_group_metadata:
        group_ids = project_metadata_group_ids(payload, known_group_ids)
        if group_ids is None:
            return ProjectMetadataUpdateResult(handled=False, project=project, changed=False)
        skills, names = expand_skills_for_group_ids(group_ids)
    else:
        group_ids = project.skill_group_ids
        skills = list(project.skills)
        names = None if project.skill_names is None else list(project.skill_names)

    codex_profile_id, claude_profile_id = project_metadata_profile_ids(
        payload,
        project,
        profile_by_id=profile_by_id,
        supports_codex=supports_codex,
        supports_claude=supports_claude,
    )
    updated = project_with_metadata_update(
        project,
        skill_group_ids=group_ids,
        skills=skills,
        skill_names=names,
        codex_profile_id=codex_profile_id,
        claude_profile_id=claude_profile_id,
        updated_at=updated_at,
    )
    if updated is None:
        return ProjectMetadataUpdateResult(handled=True, project=project, changed=False)
    return ProjectMetadataUpdateResult(handled=True, project=updated, changed=True)

def updated_project_from_dialog(project: ProjectRecord, result: dict, *, updated_at: str) -> ProjectEditUpdate:
    updated = replace(
        project,
        name=result["name"],
        project_dir=result["project_dir"],
        profile_id=result["profile_id"],
        codex_profile_id=result["codex_profile_id"],
        claude_profile_id=result["claude_profile_id"],
        run_command=result["run_command"],
        mcp_server_names=result["mcp_server_names"],
        skill_names=result["skill_names"],
        skill_group_ids=result["skill_group_ids"],
        skills=result["skills"],
        github_repo=result["github_repo"],
        github_ref=result["github_ref"],
        github_last_sync_commit=(
            ""
            if result["github_repo"] != project.github_repo or result["github_ref"] != project.github_ref
            else project.github_last_sync_commit
        ),
        github_auto_update=result["github_auto_update"],
        updated_at=updated_at,
    )
    return ProjectEditUpdate(
        project=updated,
        codex_binding_changed=project_codex_binding_changed(project, updated),
        claude_binding_changed=project_claude_binding_changed(project, updated),
    )


def build_project_binding_sync_plan(
    project: ProjectRecord,
    *,
    route_proxy_base_url: str | None,
    codex_profile: Profile | None,
    codex_model_override: str | None,
    claude_profile: Profile | None,
    claude_model_override: str | None,
    claude_fallback_model_override: str | None,
    sync_codex: bool,
    sync_claude: bool,
) -> ProjectBindingSyncPlan:
    return ProjectBindingSyncPlan(
        project_root=project_root_path(project),
        route_proxy_base_url=route_proxy_base_url,
        codex_profile=codex_profile,
        codex_model_override=codex_model_override,
        claude_profile=claude_profile,
        claude_model_override=claude_model_override,
        claude_fallback_model_override=claude_fallback_model_override,
        sync_codex=sync_codex,
        sync_claude=sync_claude,
    )


def project_binding_sync_tasks(plan: ProjectBindingSyncPlan) -> list[ProjectBindingSyncTask]:
    tasks: list[ProjectBindingSyncTask] = []
    if plan.sync_codex:
        tasks.append(
            ProjectBindingSyncTask(
                target="codex",
                profile=plan.codex_profile,
                model_override=plan.codex_model_override,
                fallback_model_override=None,
                missing_message="当前项目绑定的 Codex 配置已经不存在。",
                failure_label="Codex API 配置",
                failure_status="Codex API 配置同步失败",
            )
        )
    if plan.sync_claude:
        tasks.append(
            ProjectBindingSyncTask(
                target="claude",
                profile=plan.claude_profile,
                model_override=plan.claude_model_override,
                fallback_model_override=plan.claude_fallback_model_override,
                missing_message="当前项目绑定的 Claude 配置已经不存在。",
                failure_label="Claude settings.local.json",
                failure_status="Claude settings.local.json 同步失败",
            )
        )
    return tasks


def execute_project_binding_sync(
    plan: ProjectBindingSyncPlan,
    *,
    sync_codex_binding: Callable[[ProjectBindingSyncPlan, ProjectBindingSyncTask], list[Path]],
    sync_claude_binding: Callable[[ProjectBindingSyncPlan, ProjectBindingSyncTask], list[Path]],
) -> ProjectBindingSyncExecutionResult:
    updated_paths: list[Path] = []
    for task in project_binding_sync_tasks(plan):
        if task.profile is None:
            return ProjectBindingSyncExecutionResult(
                updated_paths=updated_paths,
                failure=ProjectBindingSyncFailure(reason="missing_profile", task=task),
            )
        try:
            if task.target == "codex":
                updated_paths.extend(sync_codex_binding(plan, task))
            else:
                updated_paths.extend(sync_claude_binding(plan, task))
        except Exception as exc:
            return ProjectBindingSyncExecutionResult(
                updated_paths=updated_paths,
                failure=ProjectBindingSyncFailure(reason="sync_failed", task=task, detail=str(exc)),
            )
    return ProjectBindingSyncExecutionResult(updated_paths=updated_paths)


def project_binding_sync_status(project_name: str, updated_paths: list[Path]) -> str:
    if updated_paths:
        return f"已同步项目配置：{project_name}"
    return f"已更新项目：{project_name}"


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


def project_detail_display(
    project: ProjectRecord | None,
    *,
    github_text: str = "-",
    github_update_text: str = "-",
    script_text: str = "-",
    run_text: str = "-",
    mcp_text: str = "-",
    skills_text: str = "-",
    codex_profile_texts: tuple[str, str, str] = ("-", "-", "-"),
    claude_profile_texts: tuple[str, str, str] = ("-", "-", "-"),
    template_display: ProjectTemplateDisplay | None = None,
) -> ProjectDetailDisplay:
    if project is None:
        return ProjectDetailDisplay(
            selected_name_text="未选择项目",
            selected_dir_text="-",
            selected_codex_profile_text="-",
            selected_claude_profile_text="-",
            selected_codex_model_text="-",
            selected_claude_model_text="-",
            selected_codex_key_text="-",
            selected_claude_key_text="-",
            backup_text="-",
            generated_text="-",
            script_text="-",
            run_text="-",
            github_text="-",
            github_update_text="-",
            mcp_text="-",
            skills_text="-",
            badge_text="未生成",
            badge_state="neutral",
        )

    codex_profile_text, codex_model_text, codex_key_text = codex_profile_texts
    claude_profile_text, claude_model_text, claude_key_text = claude_profile_texts
    template = template_display or ProjectTemplateDisplay(
        backup_text="-",
        generated_text="-",
        badge_text="未生成",
        badge_state="neutral",
    )
    return ProjectDetailDisplay(
        selected_name_text=project.name,
        selected_dir_text=project.project_dir,
        selected_codex_profile_text=codex_profile_text,
        selected_claude_profile_text=claude_profile_text,
        selected_codex_model_text=codex_model_text,
        selected_claude_model_text=claude_model_text,
        selected_codex_key_text=codex_key_text,
        selected_claude_key_text=claude_key_text,
        backup_text=template.backup_text,
        generated_text=template.generated_text,
        script_text=script_text,
        run_text=run_text,
        github_text=github_text,
        github_update_text=github_update_text,
        mcp_text=mcp_text,
        skills_text=skills_text,
        badge_text=template.badge_text,
        badge_state=template.badge_state,
    )


def build_project_detail_display_for_project(
    project: ProjectRecord | None,
    *,
    profile_by_id: Callable[[str], Profile | None],
    key_summary: Callable[[Profile], str],
    github_text: Callable[[ProjectRecord], str],
    github_update_text: Callable[[ProjectRecord], str],
    script_text: Callable[[ProjectRecord], str],
    mcp_text: Callable[[ProjectRecord], str],
    skills_text: Callable[[ProjectRecord], str],
    inspect_template_status: Callable[[Path], ProjectTemplateStatus | None],
) -> ProjectDetailDisplay:
    if project is None:
        return project_detail_display(None)

    codex_profile = profile_by_id(project_codex_profile_id(project))
    claude_profile = profile_by_id(project_claude_profile_id(project))
    codex_profile_texts = project_codex_profile_texts(
        codex_profile,
        key_summary=key_summary,
    )
    claude_profile_texts = project_claude_profile_texts(
        claude_profile,
        key_summary=key_summary,
    )
    project_root = project_root_path(project)
    template = project_template_display(
        project_root_exists=project_root.exists(),
        status=inspect_template_status(project_root) if project_root.exists() else None,
    )
    return project_detail_display(
        project,
        github_text=github_text(project),
        github_update_text=github_update_text(project),
        script_text=script_text(project),
        run_text=project.run_command or "未配置",
        mcp_text=mcp_text(project),
        skills_text=skills_text(project),
        codex_profile_texts=codex_profile_texts,
        claude_profile_texts=claude_profile_texts,
        template_display=template,
    )


def build_codex_template_execution_plan(
    project: ProjectRecord,
    codex_profile: Profile,
    claude_profile: Profile | None,
    *,
    project_mcp_toml: str,
    agents_doc_text: str,
    route_proxy_base_url: str | None,
    available_skill_sources: list[SkillSource],
    codex_model_override: str | None,
    claude_model_override: str | None,
    claude_fallback_model_override: str | None,
) -> CodexTemplateExecutionPlan:
    options = codex_project_template_options(
        project,
        project_mcp_toml=project_mcp_toml,
        agents_doc_text=agents_doc_text,
        route_proxy_base_url=route_proxy_base_url,
        available_skill_sources=available_skill_sources,
    )
    return CodexTemplateExecutionPlan(
        project_name=project.name,
        project_root=options.project_root,
        codex_profile=codex_profile,
        claude_profile=claude_profile,
        global_mcp_toml=options.global_mcp_toml,
        project_mcp_toml=options.project_mcp_toml,
        agents_doc_text=options.agents_doc_text,
        route_proxy_base_url=options.route_proxy_base_url,
        codex_model_override=codex_model_override,
        claude_model_override=claude_model_override,
        claude_fallback_model_override=claude_fallback_model_override,
        skill_sources=options.skill_sources,
        skill_definitions=options.skill_definitions,
    )


def build_claude_template_execution_plan(
    project: ProjectRecord,
    claude_profile: Profile,
    *,
    project_mcp_toml: str,
    agents_doc_text: str,
    route_proxy_base_url: str | None,
    model_override: str | None,
    fallback_model_override: str | None,
) -> ClaudeTemplateExecutionPlan:
    options = claude_project_template_options(
        project,
        project_mcp_toml=project_mcp_toml,
        agents_doc_text=agents_doc_text,
        route_proxy_base_url=route_proxy_base_url,
    )
    return ClaudeTemplateExecutionPlan(
        project_name=project.name,
        project_root=options.project_root,
        claude_profile=claude_profile,
        project_mcp_toml=options.project_mcp_toml,
        agents_doc_text=options.agents_doc_text,
        route_proxy_base_url=options.route_proxy_base_url,
        model_override=model_override,
        fallback_model_override=fallback_model_override,
    )


def build_codex_template_run_spec(plan: CodexTemplateExecutionPlan) -> ProjectTemplateRunSpec:
    return ProjectTemplateRunSpec(
        method_name="generate",
        args=(plan.project_root, plan.codex_profile),
        kwargs={
            "global_mcp_toml": plan.global_mcp_toml,
            "project_mcp_toml": plan.project_mcp_toml,
            "agents_doc_text": plan.agents_doc_text,
            "claude_profile": plan.claude_profile,
            "route_proxy_base_url": plan.route_proxy_base_url,
            "codex_model_override": plan.codex_model_override,
            "claude_model_override": plan.claude_model_override,
            "claude_fallback_model_override": plan.claude_fallback_model_override,
            "skill_sources": plan.skill_sources,
            "skill_definitions": plan.skill_definitions,
        },
        success_status=f"已生成项目模板：{plan.project_name}",
        failure_status="项目模板生成失败",
        failure_message_prefix="写入项目模板失败",
    )


def build_claude_template_run_spec(plan: ClaudeTemplateExecutionPlan) -> ProjectTemplateRunSpec:
    return ProjectTemplateRunSpec(
        method_name="generate_claude_template",
        args=(plan.project_root, plan.claude_profile),
        kwargs={
            "project_mcp_toml": plan.project_mcp_toml,
            "agents_doc_text": plan.agents_doc_text,
            "route_proxy_base_url": plan.route_proxy_base_url,
            "model_override": plan.model_override,
            "fallback_model_override": plan.fallback_model_override,
        },
        success_status=f"已生成 Claude 项目模板：{plan.project_name}",
        failure_status="Claude 项目模板生成失败",
        failure_message_prefix="写入 Claude 项目模板失败",
    )


def codex_template_success_message(project_name: str, result: ProjectTemplateResult) -> str:
    return (
        f"已为项目“{project_name}”生成模板。\n\n"
        f"启动脚本：\n{result.start_script_path}\n\n"
        f"备份目录：\n{result.backup_dir}"
    )


def claude_template_success_message(project_name: str, result: ProjectTemplateResult) -> str:
    generated = "\n".join(str(path) for path in result.generated_paths)
    return (
        f"已为项目“{project_name}”生成 Claude 模板。\n\n"
        f"生成文件：\n{generated}\n\n"
        f"备份目录：\n{result.backup_dir}"
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


def execute_project_launch_plan(
    plan: ProjectLaunchPlan,
    *,
    popen: Callable[..., object],
    creationflags: int,
    env: dict[str, str] | None = None,
) -> ProjectLaunchExecutionResult:
    if plan.required_path is not None and not plan.required_path.exists():
        return ProjectLaunchExecutionResult(
            launched=False,
            missing_message=plan.missing_message,
        )
    kwargs: dict[str, object] = {
        "cwd": plan.cwd,
        "creationflags": creationflags,
    }
    if env is not None:
        kwargs["env"] = env
    try:
        popen(plan.command, **kwargs)
    except Exception as exc:
        return ProjectLaunchExecutionResult(
            launched=False,
            failure_detail=str(exc),
        )
    return ProjectLaunchExecutionResult(
        launched=True,
        status_text=plan.success_status,
    )
