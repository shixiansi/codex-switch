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
    """Point TCL/TK_LIBRARY at usable Tcl directories when the environment is stale.

    Retained for the legacy Tk interface and for frozen builds that still ship
    Tcl data. It never imports ``tkinter``, so the QML entrypoint below stays
    free of any Tk dependency.
    """
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


def main() -> int:
    """Launch the PySide6/QML interface."""
    # Imported lazily so importing this module (e.g. from tests) never requires
    # PySide6 or initialises Qt.
    from codex_switch.ui_v2.app import run_app

    return run_app()


if __name__ == "__main__":
    raise SystemExit(main())
