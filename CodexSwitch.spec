# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Codex Switch.

The default UI is PySide6/QML, so this build:
* bundles the QML tree and the bundled SVG icons,
* collects the Qt Quick / QuickControls2 plugins PyInstaller's hooks need,
* keeps the Tk data because the legacy Tk modules are still importable.
"""

from pathlib import Path
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_submodules


ROOT = Path.cwd()
SRC_ROOT = ROOT / "src"
BASE_PREFIX = Path(sys.base_prefix)
HOOKS_ROOT = ROOT / "pyinstaller-hooks"
QML_ROOT = SRC_ROOT / "codex_switch" / "ui_v2" / "qml"
ICONS_ROOT = SRC_ROOT / "codex_switch" / "ui_v2" / "assets" / "icons"
sys.path.insert(0, str(SRC_ROOT))


def _collect_tree(source: Path, target_root: str) -> list[tuple[str, str]]:
    if not source.exists():
        return []

    output: list[tuple[str, str]] = []
    for path in source.rglob("*"):
        if not path.is_file():
            continue
        relative_parent = path.relative_to(source).parent
        destination_dir = Path(target_root) / relative_parent
        output.append((str(path), destination_dir.as_posix()))
    return output


# --- legacy Tk data (kept for the retained Tk modules) ----------------------
TKINTER_HIDDENIMPORTS = [
    "_tkinter",
    "tkinter",
    "tkinter.filedialog",
    "tkinter.font",
    "tkinter.messagebox",
    "tkinter.ttk",
]
TKINTER_DATAS = (
    _collect_tree(BASE_PREFIX / "tcl" / "tcl8.6", "_tcl_data")
    + _collect_tree(BASE_PREFIX / "tcl" / "tk8.6", "_tk_data")
    + _collect_tree(BASE_PREFIX / "tcl" / "tcl8", "tcl8")
)

# --- QML resources ----------------------------------------------------------
# The QML tree is loaded from the package directory at runtime, so it must keep
# the same relative layout inside the bundle: codex_switch/ui_v2/qml/...
QML_PACKAGE_ROOT = "codex_switch/ui_v2"
QML_DATAS = _collect_tree(QML_ROOT, f"{QML_PACKAGE_ROOT}/qml")
ICON_DATAS = _collect_tree(ICONS_ROOT, f"{QML_PACKAGE_ROOT}/assets/icons")
QML_HIDDENIMPORTS = [
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuickControls2",
    "PySide6.QtWidgets",
    "codex_switch.ui_v2",
    "codex_switch.ui_v2.app",
    "codex_switch.ui_v2.controller",
    "codex_switch.ui_v2.workspace",
]

APP_DATAS = collect_data_files("codex_switch", includes=["assets/*"])
TTKBOOTSTRAP_HIDDENIMPORTS = collect_submodules("ttkbootstrap")
TTKBOOTSTRAP_DATAS = collect_data_files("ttkbootstrap")

# --- AI 终端依赖（pywinpty 的 ConPTY 后端需要打包 ptycon.dll） -------------
# pywinpty 把架构相关的 ptycon.dll 放在包目录下，PyInstaller 不一定自动收集，
# 这里显式把整个包目录的 dll 一并打进 bundle，避免运行期找不到 ConPTY。
try:
    import pywinpty

    _PYWINPTY_PKG = Path(pywinpty.__file__).parent
    TERMINAL_BINARIES = _collect_tree(_PYWINPTY_PKG, "codex_switch/ui_v2/terminal/_pywinpty")
except Exception:  # pragma: no cover - 构建环境未装 pywinpty 时跳过
    TERMINAL_BINARIES = []

TERMINAL_HIDDENIMPORTS = [
    "codex_switch.ui_v2.terminal",
    "codex_switch.ui_v2.terminal.manager",
    "codex_switch.ui_v2.terminal.pty_session",
    "codex_switch.ui_v2.terminal.screen",
    "codex_switch.ui_v2.terminal.completion",
    "codex_switch.ui_v2.viewmodels.terminal",
    "pywinpty",
    "pyte",
    "psutil",
]


a = Analysis(
    ['main.py'],
    pathex=[str(ROOT), str(SRC_ROOT)],
    binaries=[],
    datas=(
        TKINTER_DATAS
        + APP_DATAS
        + QML_DATAS
        + ICON_DATAS
        + TTKBOOTSTRAP_DATAS
        + TERMINAL_BINARIES
    ),
    hiddenimports=TKINTER_HIDDENIMPORTS + TTKBOOTSTRAP_HIDDENIMPORTS + QML_HIDDENIMPORTS + TERMINAL_HIDDENIMPORTS,
    hookspath=[str(HOOKS_ROOT)],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='CodexSwitch',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
