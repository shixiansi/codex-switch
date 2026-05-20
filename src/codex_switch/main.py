from __future__ import annotations

from pathlib import Path
import os
import sys


def _has_required_tcl_file(path: str, filename: str) -> bool:
    raw = path.strip()
    if not raw:
        return False
    candidate = Path(raw)
    return candidate.is_dir() and (candidate / filename).exists()


def _normalize_tk_environment() -> None:
    expected_dirs = {
        "TCL_LIBRARY": (
            "init.tcl",
            (
                Path(sys.base_prefix) / "tcl" / "tcl8.6",
                Path(sys.base_prefix) / "tcl" / "tcl8.5",
                Path(sys.base_prefix) / "tcl" / "tcl8",
            ),
        ),
        "TK_LIBRARY": (
            "tk.tcl",
            (
                Path(sys.base_prefix) / "tcl" / "tk8.6",
                Path(sys.base_prefix) / "tcl" / "tk8.5",
            ),
        ),
    }

    for env_key, (required_file, candidates) in expected_dirs.items():
        current_value = os.environ.get(env_key, "").strip()
        if current_value and _has_required_tcl_file(current_value, required_file):
            continue

        if current_value:
            os.environ.pop(env_key, None)

        for candidate in candidates:
            if _has_required_tcl_file(str(candidate), required_file):
                os.environ[env_key] = str(candidate)
                break


def main() -> None:
    _normalize_tk_environment()

    from codex_switch.ui.app import run_app

    run_app()


if __name__ == "__main__":
    main()
