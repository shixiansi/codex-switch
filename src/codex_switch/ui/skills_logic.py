from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
import subprocess

from codex_switch.models import now_iso

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


from codex_switch.models import SKILL_TYPE_LABELS, normalize_skill_type
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


@dataclass(frozen=True)
class SkillRepoPreviewRow:
    source_path: str
    values: tuple[str, str]


@dataclass(frozen=True)
class SkillRepoPreviewDisplay:
    rows: list[SkillRepoPreviewRow]
    status_text: str


@dataclass(frozen=True)
class SkillMarketCardDisplay:
    title: str
    author_text: str
    repo_text: str


@dataclass(frozen=True)
class SkillMarketLayout:
    columns: int
    card_count: int
    relayout_required: bool


@dataclass(frozen=True)
class SkillGroupDialogCardDisplay:
    skill_id: str
    title: str
    type_version_text: str
    source_text: str


@dataclass(frozen=True)
class SkillGroupDialogLayout:
    columns: int
    card_count: int
    relayout_required: bool


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


def skill_group_choice_labels(groups: list[SkillGroup]) -> list[str]:
    return [f"{group.name}（{len(group.skills)} 个 Skills）" for group in groups]


def skill_repo_choice_labels(repos: list[SkillMarketRepo]) -> list[str]:
    return [f"{repo.url} @ {repo.branch}" for repo in repos]


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


def skill_market_card_displays(entries: list[SkillMarketEntry]) -> list[SkillMarketCardDisplay]:
    return [
        SkillMarketCardDisplay(
            title=compact_text(entry.source.display_name or entry.source.name, 28),
            author_text=f"作者：{entry.author}",
            repo_text=compact_text(entry.repo_url, 34),
        )
        for entry in entries
    ]


def build_skill_market_layout(
    *,
    width: int,
    card_count: int,
    previous_columns: int,
    previous_count: int,
) -> SkillMarketLayout:
    columns = max(1, width // 260)
    return SkillMarketLayout(
        columns=columns,
        card_count=card_count,
        relayout_required=previous_columns != columns or previous_count != card_count,
    )


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


def skill_repo_filter_text(
    repo: SkillMarketRepo,
    *,
    groups_by_id: dict[str, SkillGroup] | None = None,
) -> str:
    group = (groups_by_id or {}).get(repo.installed_group_id)
    group_name = group.name if group is not None else ""
    auto_label = "auto automatic 自动 是" if repo.auto_update else "manual 手动 否"
    return " ".join(
        item
        for item in (
            repo.url,
            repo.branch,
            repo.last_sync_commit,
            group_name,
            auto_label,
        )
        if item
    ).casefold()


def filter_skill_market_repos(
    repos: list[SkillMarketRepo],
    *,
    groups: list[SkillGroup],
    query: str,
) -> list[SkillMarketRepo]:
    normalized_query = query.strip().casefold()
    if not normalized_query:
        return list(repos)
    group_by_id = {group.id: group for group in groups}
    return [
        repo
        for repo in repos
        if normalized_query in skill_repo_filter_text(repo, groups_by_id=group_by_id)
    ]


def filter_skill_repo_preview_sources(
    sources: list[SkillSource],
    *,
    query: str,
) -> list[SkillSource]:
    normalized_query = query.strip().casefold()
    if not normalized_query:
        return list(sources)
    return [
        source
        for source in sources
        if normalized_query in source.name.casefold()
        or normalized_query in source.display_name.casefold()
        or normalized_query in str(source.source_path).casefold()
    ]


def skill_repo_preview_display(
    repo: SkillMarketRepo,
    all_sources: list[SkillSource],
    visible_sources: list[SkillSource],
    *,
    query: str,
) -> SkillRepoPreviewDisplay:
    rows = [
        SkillRepoPreviewRow(
            source_path=str(source.source_path),
            values=(source.name, compact_text(str(source.source_path), 54)),
        )
        for source in visible_sources
    ]
    total_count = len(all_sources)
    visible_count = len(visible_sources)
    normalized_query = query.strip()
    if normalized_query:
        status_text = f"{repo.url}：{visible_count} / {total_count} 个 Skills，筛选“{normalized_query}”。"
    else:
        status_text = f"{repo.url}：{total_count} 个 Skills。"
    return SkillRepoPreviewDisplay(rows=rows, status_text=status_text)


def skill_group_detail_text(group: SkillGroup | None) -> str:
    if group is None:
        return "未选择 Skills 组"
    skill_names = ", ".join(
        f"{skill.name}({SKILL_TYPE_LABELS.get(normalize_skill_type(skill.type), skill.type)})"
        for skill in group.skills[:5]
    )
    suffix = " ..." if len(group.skills) > 5 else ""
    return f"{group.name}: {skill_names or '暂无 Skill'}{suffix}"


def skill_group_dialog_card_displays(group: SkillGroup) -> list[SkillGroupDialogCardDisplay]:
    displays: list[SkillGroupDialogCardDisplay] = []
    for skill in group.skills:
        type_label = SKILL_TYPE_LABELS.get(normalize_skill_type(skill.type), skill.type)
        displays.append(
            SkillGroupDialogCardDisplay(
                skill_id=skill.id,
                title=compact_text(skill.name, 26),
                type_version_text=f"{type_label} / {skill.version}",
                source_text=compact_text(skill.source_path or "本地内容", 32),
            )
        )
    return displays


def build_skill_group_dialog_layout(
    *,
    width: int,
    card_count: int,
    previous_columns: int,
    previous_count: int,
) -> SkillGroupDialogLayout:
    columns = max(1, int(width) // 240)
    return SkillGroupDialogLayout(
        columns=columns,
        card_count=card_count,
        relayout_required=previous_columns != columns or previous_count != card_count,
    )


def expanded_skills_for_group_ids(
    groups: list[SkillGroup],
    group_ids: list[str] | None,
) -> tuple[list[SkillDefinition], list[str]]:
    if group_ids is None:
        return [], []
    group_by_id = {group.id: group for group in groups}
    skills: list[SkillDefinition] = []
    names: list[str] = []
    for group_id in group_ids:
        group = group_by_id.get(group_id)
        if group is None:
            continue
        for skill in group.skills:
            skills.append(skill)
            if skill.name and skill.name not in names:
                names.append(skill.name)
    return skills, names


def sync_projects_from_skill_groups(
    projects: list[ProjectRecord],
    groups: list[SkillGroup],
    *,
    updated_at: str | None = None,
) -> tuple[list[ProjectRecord], bool]:
    changed = False
    updated_projects: list[ProjectRecord] = []
    timestamp = updated_at or now_iso()
    for project in projects:
        if project.skill_group_ids is None:
            updated_projects.append(project)
            continue
        skills, names = expanded_skills_for_group_ids(groups, project.skill_group_ids)
        if project.skills != skills or project.skill_names != names:
            updated_projects.append(replace(project, skills=skills, skill_names=names, updated_at=timestamp))
            changed = True
        else:
            updated_projects.append(project)
    return updated_projects, changed


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


def replace_skill_group(groups: list[SkillGroup], updated_group: SkillGroup) -> list[SkillGroup]:
    return [updated_group if group.id == updated_group.id else group for group in groups]


def skill_group_name_error(name: str) -> str | None:
    if not name.strip():
        return "组名不能为空。"
    return None


def remove_skill_group(groups: list[SkillGroup], group_id: str) -> list[SkillGroup]:
    return [group for group in groups if group.id != group_id]


def skill_group_with_metadata(group: SkillGroup, *, name: str, description: str) -> SkillGroup:
    return replace(group, name=name.strip(), description=description.strip())


def skill_group_with_added_skill(group: SkillGroup, skill: SkillDefinition) -> SkillGroup:
    return replace(group, skills=[*group.skills, skill])


def skill_group_with_replaced_skill(
    group: SkillGroup,
    existing_skill_id: str,
    updated_skill: SkillDefinition,
) -> SkillGroup:
    return replace(
        group,
        skills=[updated_skill if skill.id == existing_skill_id else skill for skill in group.skills],
    )


def skill_group_with_deleted_skill(group: SkillGroup, skill_id: str) -> SkillGroup:
    return replace(group, skills=[skill for skill in group.skills if skill.id != skill_id])


def projects_after_skill_group_delete(projects: list[ProjectRecord], group_id: str) -> list[ProjectRecord]:
    updated_projects: list[ProjectRecord] = []
    for project in projects:
        if project.skill_group_ids and group_id in project.skill_group_ids:
            remaining = [item for item in project.skill_group_ids if item != group_id]
            updated_projects.append(replace(project, skill_group_ids=remaining, skills=[], skill_names=[]))
        else:
            updated_projects.append(project)
    return updated_projects
