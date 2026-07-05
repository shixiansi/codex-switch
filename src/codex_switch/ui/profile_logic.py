from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable

from codex_switch.models import Profile, ProjectRecord, VENDOR_CLAUDE, VENDOR_CODEX, VENDOR_OTHER


@dataclass(frozen=True)
class ProfileCollectionUpdate:
    profiles: list[Profile]
    selected_profile_id: str | None


def profile_initial_vendor(library_profile_view: str) -> str | None:
    if library_profile_view in {VENDOR_CODEX, VENDOR_CLAUDE, VENDOR_OTHER}:
        return library_profile_view
    return None


def profile_from_dialog_result(result: dict) -> Profile:
    return Profile.create(**result)


def updated_profile_from_dialog(profile: Profile, result: dict) -> Profile:
    return replace(
        profile,
        name=result["name"],
        base_url=result["base_url"],
        api_keys=result["api_keys"],
        active_api_key_index=result["active_api_key_index"],
        model=result["model"],
        vendor=result["vendor"],
        codex_model=result["codex_model"],
        claude_model=result["claude_model"],
        claude_fallback_model=result["claude_fallback_model"],
        provider_name=result["provider_name"],
        category=result["category"],
        api_provided=result["api_provided"],
        wire_api=result["wire_api"],
        custom_headers=result["custom_headers"],
        requires_sign_in=result["requires_sign_in"],
        sign_in_url=result["sign_in_url"],
        last_signed_date=result["last_signed_date"],
        notes=result["notes"],
    )


def profile_collection_after_add(
    profiles: list[Profile],
    profile: Profile,
) -> ProfileCollectionUpdate:
    return ProfileCollectionUpdate(
        profiles=[*profiles, profile],
        selected_profile_id=profile.id,
    )


def profile_collection_after_replace(
    profiles: list[Profile],
    updated_profile: Profile,
) -> ProfileCollectionUpdate:
    return ProfileCollectionUpdate(
        profiles=[updated_profile if item.id == updated_profile.id else item for item in profiles],
        selected_profile_id=updated_profile.id,
    )


def profile_delete_error(
    profile_id: str,
    projects: list[ProjectRecord],
    *,
    project_bound_profile_ids: Callable[[ProjectRecord], set[str]],
) -> str | None:
    bound_projects = [
        project.name
        for project in projects
        if profile_id in project_bound_profile_ids(project)
    ]
    if not bound_projects:
        return None
    return f"以下项目仍绑定此配置：\n{', '.join(bound_projects)}"


def profile_collection_after_delete(
    profiles: list[Profile],
    *,
    selected_profile_id: str | None,
    deleted_profile_id: str,
) -> ProfileCollectionUpdate:
    remaining_profiles = [profile for profile in profiles if profile.id != deleted_profile_id]
    resolved_selected_id = selected_profile_id
    if resolved_selected_id == deleted_profile_id:
        resolved_selected_id = remaining_profiles[0].id if remaining_profiles else None
    return ProfileCollectionUpdate(
        profiles=remaining_profiles,
        selected_profile_id=resolved_selected_id,
    )
