from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from codex_switch.models import Profile


@dataclass
class GlobalApplyResult:
    codex_backup_dir: Path | None = None
    claude_backup_dir: Path | None = None
    claude_settings_path: Path | None = None


@dataclass(frozen=True)
class GlobalProfileChoiceDisplay:
    labels: tuple[str, ...]
    state: str
    selected_label: str
    selected_index: int | None


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


def global_profile_choice_display(
    profiles: list[Profile],
    selected_profile: Profile | None,
) -> GlobalProfileChoiceDisplay:
    labels = global_profile_choice_names(profiles)
    if selected_profile not in profiles:
        selected_profile = profiles[0] if profiles else None
    if selected_profile is None:
        return GlobalProfileChoiceDisplay(
            labels=labels,
            state="readonly" if labels else "disabled",
            selected_label="",
            selected_index=None,
        )
    return GlobalProfileChoiceDisplay(
        labels=labels,
        state="readonly" if labels else "disabled",
        selected_label=selected_profile.name,
        selected_index=profiles.index(selected_profile),
    )


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


def global_profile_apply_error(*, supports_codex: bool, supports_claude: bool) -> str | None:
    if not supports_codex and not supports_claude:
        return "当前配置不能写入 Codex 或 Claude 全局配置。"
    return None


def global_apply_targets(result: GlobalApplyResult) -> str:
    targets = []
    if result.codex_backup_dir is not None:
        targets.append("Codex")
    if result.claude_backup_dir is not None:
        targets.append("Claude")
    return " / ".join(targets)


def global_apply_detail(result: GlobalApplyResult) -> str:
    parts: list[str] = []
    if result.codex_backup_dir is not None:
        parts.append(f"Codex 备份位置：\n{result.codex_backup_dir}")
    if result.claude_backup_dir is not None:
        parts.append(f"Claude settings：\n{result.claude_settings_path}\nClaude 备份位置：\n{result.claude_backup_dir}")
    return "\n\n".join(parts)


def _clean_display_value(value) -> str:
    text = str(value or "").strip()
    return text or "-"
