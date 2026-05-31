from __future__ import annotations

from codex_switch.models import ProjectRecord


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
