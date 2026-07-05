from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
import subprocess

from codex_switch.models import (
    PROFILE_CATEGORY_IMAGE_GENERATION,
    Profile,
    ProjectRecord,
    SkillDefinition,
    SkillGroup,
    SkillMarketRepo,
    VENDOR_CLAUDE,
    normalize_profile_category,
)
from codex_switch.skills import SkillSource, discover_skill_sources
from codex_switch.ui.utils import compact_text


MODEL_METADATA_RELATIVE_PATHS = (
    Path("codex-switch-model-metadata.json"),
    Path("model-metadata.json"),
    Path(".codex-switch") / "model-metadata.json",
)


@dataclass(frozen=True)
class SkillMarketEntry:
    repo_id: str
    repo_url: str
    author: str
    source: SkillSource


@dataclass(frozen=True)
class SkillRepoRow:
    repo_id: str
    values: tuple[str, str, str, str]


@dataclass(frozen=True)
class SkillGroupRow:
    group_id: str
    values: tuple[str, int, str]


@dataclass(frozen=True)
class SkillProjectRow:
    project_id: str
    values: tuple[str, str, str]


@dataclass(frozen=True)
class SkillsTabDisplay:
    repo_rows: list[SkillRepoRow]
    group_rows: list[SkillGroupRow]
    project_rows: list[SkillProjectRow]
    hint_text: str
    preview_status_text: str
    selected_repo_id: str | None = None
    selected_group_id: str | None = None


def github_repo_author(repo_url: str) -> str:
    normalized = str(repo_url or "").rstrip("/")
    parts = normalized.split("/")
    if len(parts) < 2:
        return "-"
    return parts[-2] or "-"


def skill_market_entry_text(entry: SkillMarketEntry) -> str:
    return " ".join(
        item
        for item in (
            entry.source.name,
            entry.source.display_name,
            entry.author,
            entry.repo_url,
            str(entry.source.source_path),
        )
        if item
    ).casefold()


def filter_skill_market_entries(entries: list[SkillMarketEntry], query: str) -> list[SkillMarketEntry]:
    normalized_query = query.strip().casefold()
    if not normalized_query:
        return entries
    return [entry for entry in entries if normalized_query in skill_market_entry_text(entry)]


def load_skill_market_entries(
    repos: list[SkillMarketRepo],
    *,
    sync_remote: bool,
    query: str,
    cache_dir_for_repo: Callable[[SkillMarketRepo], Path],
    sync_repo_cache: Callable[[SkillMarketRepo], Path],
    verify_repo_checksums: Callable[[Path, list[SkillSource]], bool],
) -> tuple[list[SkillMarketEntry], list[str]]:
    entries: list[SkillMarketEntry] = []
    errors: list[str] = []
    for repo in repos:
        try:
            cache_dir = sync_repo_cache(repo) if sync_remote else cache_dir_for_repo(repo)
            if not any(cache_dir.rglob("SKILL.md")):
                if sync_remote:
                    raise RuntimeError("Repository does not contain any skills.")
                continue
            sources = discover_skill_sources([cache_dir])
            verify_repo_checksums(cache_dir, sources)
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
            errors.append(f"{repo.url}: {exc}")
            continue
        author = github_repo_author(repo.url)
        entries.extend(
            SkillMarketEntry(
                repo_id=repo.id,
                repo_url=repo.url,
                author=author,
                source=source,
            )
            for source in sources
        )
    return filter_skill_market_entries(entries, query), errors


def build_skills_tab_display(
    *,
    all_repos: list[SkillMarketRepo],
    visible_repos: list[SkillMarketRepo],
    groups: list[SkillGroup],
    projects: list[ProjectRecord],
    market_entries_count: int,
    market_errors_count: int,
    repo_filter_active: bool,
    selected_repo_id: str | None = None,
    selected_group_id: str | None = None,
) -> SkillsTabDisplay:
    repo_rows = [
        SkillRepoRow(
            repo_id=repo.id,
            values=(
                repo.url,
                repo.branch,
                compact_text(repo.last_sync_commit or "-", 12),
                "是" if repo.auto_update else "否",
            ),
        )
        for repo in visible_repos
    ]

    group_rows = [
        SkillGroupRow(
            group_id=group.id,
            values=(group.name, len(group.skills), compact_text(group.description or "-", 54)),
        )
        for group in groups
    ]

    group_by_id = {group.id: group for group in groups}
    project_rows: list[SkillProjectRow] = []
    for project in projects:
        group_names = [
            group_by_id[group_id].name
            for group_id in (project.skill_group_ids or [])
            if group_id in group_by_id
        ]
        skill_names = [skill.name for skill in project.skills] or list(project.skill_names or [])
        project_rows.append(
            SkillProjectRow(
                project_id=project.id,
                values=(
                    project.name,
                    compact_text(", ".join(group_names) if group_names else "未配置", 36),
                    compact_text(", ".join(skill_names) if skill_names else "未配置", 48),
                ),
            )
        )

    repo_filter_text = ""
    if repo_filter_active:
        repo_filter_text = f"；仓库筛选 {len(visible_repos)}/{len(all_repos)}"
    hint_text = f"{len(all_repos)} 个仓库{repo_filter_text}；{len(groups)} 个本地组，{len(projects)} 个项目。"
    error_text = f"；{market_errors_count} 个仓库读取失败" if market_errors_count else ""
    preview_status_text = f"市场显示 {market_entries_count} 个 Skills{error_text}。"
    resolved_repo_id = selected_repo_id if any(row.repo_id == selected_repo_id for row in repo_rows) else None
    resolved_group_id = selected_group_id if any(row.group_id == selected_group_id for row in group_rows) else None
    return SkillsTabDisplay(
        repo_rows=repo_rows,
        group_rows=group_rows,
        project_rows=project_rows,
        hint_text=hint_text,
        preview_status_text=preview_status_text,
        selected_repo_id=resolved_repo_id,
        selected_group_id=resolved_group_id,
    )


def existing_repo_files(repo_root: Path, relative_paths: tuple[Path, ...]) -> list[Path]:
    return [
        repo_root / relative_path
        for relative_path in relative_paths
        if (repo_root / relative_path).is_file()
    ]


def skill_repo_checksum_required_paths(repo_root: Path, sources: list[SkillSource]) -> list[Path]:
    required_paths: list[Path] = []
    root = repo_root.resolve()
    for source in sources:
        skill_file = source.source_path / "SKILL.md"
        if not skill_file.is_file():
            continue
        try:
            skill_file.resolve().relative_to(root)
        except ValueError:
            continue
        required_paths.append(skill_file)
    required_paths.extend(existing_repo_files(repo_root, MODEL_METADATA_RELATIVE_PATHS))
    return required_paths


def metadata_text(payload: dict, key: str, default: str) -> str:
    if key not in payload:
        return default
    value = str(payload.get(key) or "").strip()
    return value or default


def metadata_bool(payload: dict, key: str, default: bool) -> bool:
    if key not in payload:
        return default
    value = payload.get(key)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return bool(value)


def metadata_model_names(payload: object) -> list[str]:
    if not isinstance(payload, list):
        return []
    models: list[str] = []
    for item in payload:
        if isinstance(item, dict):
            raw_name = item.get("name") or item.get("id") or item.get("model")
        else:
            raw_name = item
        name = str(raw_name or "").strip()
        if name and name not in models:
            models.append(name)
    return models


def profile_metadata_entries(payload: dict) -> list[dict]:
    entries: list[dict] = []
    for key in ("profiles", "profile_metadata", "profile_models"):
        raw_entries = payload.get(key)
        if isinstance(raw_entries, list):
            entries.extend(item for item in raw_entries if isinstance(item, dict))
        elif isinstance(raw_entries, dict):
            for profile_key, value in raw_entries.items():
                if isinstance(value, dict):
                    entry = dict(value)
                    entry.setdefault("id", profile_key)
                    entry.setdefault("name", profile_key)
                else:
                    entry = {"id": profile_key, "name": profile_key, "models": value}
                entries.append(entry)
    return entries


def profile_metadata_index(profiles: list[Profile], entry: dict) -> int | None:
    profile_id = str(entry.get("id") or entry.get("profile_id") or "").strip()
    if profile_id:
        for index, profile in enumerate(profiles):
            if profile.id == profile_id:
                return index
    profile_name = str(entry.get("name") or entry.get("profile_name") or "").strip()
    if not profile_name:
        return None
    matches = [
        index
        for index, profile in enumerate(profiles)
        if profile.name == profile_name
    ]
    return matches[0] if len(matches) == 1 else None


def profile_with_metadata(profile: Profile, entry: dict) -> Profile:
    category = (
        normalize_profile_category(entry.get("category"))
        if "category" in entry
        else normalize_profile_category(profile.category)
    )
    api_provided = metadata_bool(entry, "api_provided", profile.api_provided)
    if category != PROFILE_CATEGORY_IMAGE_GENERATION:
        api_provided = True

    model = metadata_text(entry, "model", "")
    codex_model = metadata_text(entry, "codex_model", "")
    claude_model = metadata_text(entry, "claude_model", "")
    claude_fallback_model = metadata_text(
        entry,
        "claude_fallback_model",
        profile.claude_fallback_model,
    )
    if not codex_model:
        codex_model = model if profile.vendor != VENDOR_CLAUDE and model else profile.codex_model
    if not claude_model:
        claude_model = model if profile.vendor == VENDOR_CLAUDE and model else profile.claude_model

    health = profile.health
    for models_key in ("models", "available_models", "model_list"):
        if models_key in entry:
            health = replace(health, models=metadata_model_names(entry.get(models_key)))
            break

    api_keys = list(profile.api_keys) if api_provided else []
    return replace(
        profile,
        model=codex_model,
        codex_model=codex_model,
        claude_model=claude_model,
        claude_fallback_model=claude_fallback_model,
        provider_name=metadata_text(entry, "provider_name", profile.provider_name),
        category=category,
        api_provided=api_provided,
        api_keys=api_keys,
        active_api_key_index=profile.active_api_key_index if api_keys else 0,
        health=health,
    )


def apply_profile_metadata(profiles: list[Profile], payload: dict) -> tuple[list[Profile], bool]:
    entries = profile_metadata_entries(payload)
    if not entries:
        return profiles, False

    updated_profiles = list(profiles)
    changed = False
    for entry in entries:
        index = profile_metadata_index(updated_profiles, entry)
        if index is None:
            continue
        updated = profile_with_metadata(updated_profiles[index], entry)
        if updated != updated_profiles[index]:
            updated_profiles[index] = updated
            changed = True
    return updated_profiles, changed
def import_skill_sources_to_group(
    group: SkillGroup,
    sources: list[SkillSource],
    *,
    replace_existing_from_root: Path | None = None,
) -> tuple[SkillGroup, int]:
    existing_skills = list(group.skills)
    if replace_existing_from_root is not None:
        root_text = str(replace_existing_from_root).casefold()
        existing_skills = [
            skill
            for skill in existing_skills
            if not skill.source_path or not str(skill.source_path).casefold().startswith(root_text)
        ]
    existing_names = {skill.name for skill in existing_skills}
    imported: list[SkillDefinition] = []
    for source in sources:
        if source.name in existing_names:
            continue
        try:
            content = (source.source_path / "SKILL.md").read_text(encoding="utf-8")
        except OSError:
            content = ""
        imported.append(
            SkillDefinition.create(
                source.name,
                content=content,
                source_path=str(source.source_path),
            )
        )
        existing_names.add(source.name)
    return replace(group, skills=[*existing_skills, *imported]), len(imported)
