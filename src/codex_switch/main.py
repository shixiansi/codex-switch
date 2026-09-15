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


_INSTALL_HINT = """PySide6 未安装，无法启动界面。

当前解释器：{executable}

请任选一种方式安装后重试：

1) 安装到当前解释器（推荐先用虚拟环境）：
   "{executable}" -m pip install -r requirements.txt

2) 使用项目自带的虚拟环境启动：
   .venv\\Scripts\\python.exe main.py

提示：如果网络较慢，可加国内镜像，例如
   -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
"""


def main() -> int:
    """Launch the PySide6/QML interface."""
    # Imported lazily so importing this module (e.g. from tests) never requires
    # PySide6 or initialises Qt.
    from codex_switch.ui_v2.app import run_app
    from codex_switch.ui_v2.qt_compat import QT_AVAILABLE

    if not QT_AVAILABLE:
        # A bare "not installed" message left users unable to tell which
        # interpreter was used or how to fix it, so print exact instructions.
        print(_INSTALL_HINT.format(executable=sys.executable), file=sys.stderr)
        return 1

    return run_app()


if __name__ == "__main__":
    raise SystemExit(main())
