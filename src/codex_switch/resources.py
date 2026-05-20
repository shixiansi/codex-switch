from __future__ import annotations

from pathlib import Path
import sys


def asset_path_candidates(relative_path: str) -> list[Path]:
    rel = Path("assets") / relative_path
    candidates: list[Path] = []
    pyinstaller_root = getattr(sys, "_MEIPASS", None)
    if pyinstaller_root:
        candidates.append(Path(pyinstaller_root) / "codex_switch" / rel)
        candidates.append(Path(pyinstaller_root) / rel)
    candidates.append(Path(__file__).resolve().parent / rel)
    return candidates


def asset_path(relative_path: str) -> Path:
    for candidate in asset_path_candidates(relative_path):
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"Missing asset: {relative_path}")
