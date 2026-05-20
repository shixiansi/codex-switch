from __future__ import annotations

from pathlib import Path

from codex_switch.project_template import CODEX_SCRIPT_DIRNAME

def compact_text(value: str, limit: int = 54) -> str:
    return value if len(value) <= limit else f"{value[:limit - 1]}…"

def hidden_secret(value: str | None) -> str:
    if not value:
        return "-"
    return "*" * min(max(len(value), 8), 24)

def is_http_url(value: str) -> bool:
    return value.startswith(("http://", "https://"))

def project_start_script_paths(project_dir: Path | str) -> tuple[Path, Path]:
    project_root = Path(project_dir)
    script_root = project_root / CODEX_SCRIPT_DIRNAME
    return script_root / "start-codex.ps1", script_root / "start-codex.cmd"

def resolve_mcp_editor_text(*candidates: str) -> str:
    for candidate in candidates:
        if candidate and candidate.strip():
            return candidate
    return ""
