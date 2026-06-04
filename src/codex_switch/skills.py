from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil


PROJECT_SKILLS_RELATIVE_DIR = Path(".codex") / "home" / "skills"
SKILL_MANAGED_MARKER = ".codex-switch-managed"


@dataclass(frozen=True)
class SkillSource:
    name: str
    display_name: str
    source_path: Path


def default_skill_roots(project_root: Path | None = None) -> list[Path]:
    roots: list[Path] = []
    if project_root is not None:
        roots.append(project_root / PROJECT_SKILLS_RELATIVE_DIR)
    roots.append(Path.home() / ".agents" / "skills")
    return roots


def discover_skill_sources(roots: list[Path]) -> list[SkillSource]:
    candidates: list[tuple[str, Path, Path, str]] = []
    for root in roots:
        if not root.exists() or not root.is_dir():
            continue
        try:
            skill_files = sorted(root.rglob("SKILL.md"), key=lambda path: str(path).casefold())
        except OSError:
            continue
        for skill_file in skill_files:
            skill_dir = skill_file.parent
            try:
                relative = skill_dir.relative_to(root)
            except ValueError:
                relative = Path(skill_dir.name)
            leaf_name = skill_dir.name
            relative_label = relative.as_posix()
            candidates.append((leaf_name, relative, skill_dir, relative_label))

    leaf_counts: dict[str, int] = {}
    for leaf_name, _relative, _skill_dir, _relative_label in candidates:
        leaf_counts[leaf_name.casefold()] = leaf_counts.get(leaf_name.casefold(), 0) + 1

    sources: list[SkillSource] = []
    used_names: set[str] = set()
    for leaf_name, relative, skill_dir, relative_label in candidates:
        has_duplicate_leaf = leaf_counts[leaf_name.casefold()] > 1
        name = leaf_name if not has_duplicate_leaf else _skill_name_from_relative(relative)
        if name.casefold() in used_names:
            name = _deduplicate_skill_name(name, used_names)
        used_names.add(name.casefold())
        display_name = leaf_name if not has_duplicate_leaf else f"{leaf_name} ({relative_label})"
        sources.append(SkillSource(name=name, display_name=display_name, source_path=skill_dir))

    return sorted(sources, key=lambda item: (item.display_name.casefold(), item.name.casefold()))


def resolve_selected_skill_sources(
    skill_sources: list[SkillSource],
    selected_names: list[str] | None,
) -> list[SkillSource]:
    if selected_names is None:
        return list(skill_sources)
    selected = {name for name in selected_names if name}
    return [source for source in skill_sources if source.name in selected]


def skill_selection_summary(
    skill_sources: list[SkillSource],
    selected_names: list[str] | None,
    *,
    limit: int = 4,
) -> str:
    selected = resolve_selected_skill_sources(skill_sources, selected_names)
    if not selected:
        return "未启用"
    labels = [source.display_name for source in selected]
    suffix = " ..." if len(labels) > limit else ""
    return f"{len(labels)} 个技能：" + ", ".join(labels[:limit]) + suffix


def sync_project_skills(
    project_root: Path,
    skill_sources: list[SkillSource],
    selected_names: list[str] | None,
    *,
    backup_dir: Path | None = None,
) -> list[Path]:
    selected_sources = resolve_selected_skill_sources(skill_sources, selected_names)
    selected_by_name = {source.name: source for source in selected_sources}
    skills_dir = project_root / PROJECT_SKILLS_RELATIVE_DIR
    generated_paths: list[Path] = []
    backed_up: set[Path] = set()

    if skills_dir.exists():
        for child in sorted(skills_dir.iterdir(), key=lambda path: path.name.casefold()):
            if child.name in selected_by_name:
                continue
            if not _is_managed_skill_dir(child):
                continue
            _backup_skill_path(project_root, child, backup_dir, backed_up)
            shutil.rmtree(child)

    if not selected_by_name:
        return generated_paths

    skills_dir.mkdir(parents=True, exist_ok=True)
    for source in selected_sources:
        if not source.source_path.exists() or not (source.source_path / "SKILL.md").exists():
            continue
        target = skills_dir / source.name
        source_path = source.source_path.resolve()
        if target.exists():
            target_path = target.resolve()
            if target_path == source_path:
                _write_managed_marker(target)
                generated_paths.append(target)
                continue
            _backup_skill_path(project_root, target, backup_dir, backed_up)
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
        shutil.copytree(source.source_path, target)
        _write_managed_marker(target)
        generated_paths.append(target)

    return generated_paths


def _skill_name_from_relative(relative: Path) -> str:
    parts = [part for part in relative.parts if part and part not in (".", "..")]
    return "__".join(parts) if parts else "skill"


def _deduplicate_skill_name(name: str, used_names: set[str]) -> str:
    index = 2
    candidate = f"{name}__{index}"
    while candidate.casefold() in used_names:
        index += 1
        candidate = f"{name}__{index}"
    return candidate


def _is_managed_skill_dir(path: Path) -> bool:
    return path.is_dir() and (path / SKILL_MANAGED_MARKER).exists()


def _write_managed_marker(path: Path) -> None:
    (path / SKILL_MANAGED_MARKER).write_text("managed by codex-switch\n", encoding="utf-8")


def _backup_skill_path(project_root: Path, path: Path, backup_dir: Path | None, backed_up: set[Path]) -> None:
    if backup_dir is None or not path.exists():
        return
    resolved = path.resolve()
    if resolved in backed_up:
        return
    try:
        relative_path = path.relative_to(project_root)
    except ValueError:
        relative_path = PROJECT_SKILLS_RELATIVE_DIR / path.name
    destination = backup_dir / relative_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    if path.is_dir():
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(path, destination)
    else:
        shutil.copy2(path, destination)
    backed_up.add(resolved)
