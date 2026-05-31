from __future__ import annotations

from collections.abc import Callable

from codex_switch.models import Profile


def resolve_global_profile_id(
    stored_profile_id: str | None,
    legacy_profile_id: str | None,
    profiles: list[Profile],
    supports_profile: Callable[[Profile], bool],
) -> str | None:
    profiles_by_id = {profile.id: profile for profile in profiles}
    for profile_id in (stored_profile_id, legacy_profile_id):
        profile = profiles_by_id.get(profile_id or "")
        if profile is not None and supports_profile(profile):
            return profile.id
    return None


def resolve_global_mcp_server_names(
    selected_names: list[str] | None,
    *,
    opt_out: bool,
    available_names: list[str],
) -> list[str]:
    if opt_out:
        return []
    if selected_names is None:
        return list(available_names)
    available = set(available_names)
    return [name for name in selected_names if name in available]


def global_profile_choice_names(profiles: list[Profile]) -> tuple[str, ...]:
    return tuple(profile.name for profile in profiles)


def profile_for_choice_index(profiles: list[Profile], index: int) -> Profile | None:
    if 0 <= index < len(profiles):
        return profiles[index]
    return None


def claude_settings_env_values(
    settings: dict,
    *,
    base_url_key: str,
    model_key: str,
    fallback_model_key: str,
) -> tuple[str, str, str]:
    env = settings.get("env", {})
    if not isinstance(env, dict):
        env = {}
    return (
        _clean_display_value(env.get(base_url_key)),
        _clean_display_value(env.get(model_key)),
        _clean_display_value(env.get(fallback_model_key)),
    )


def _clean_display_value(value) -> str:
    text = str(value or "").strip()
    return text or "-"
