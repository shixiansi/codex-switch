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

# --- AI 终端依赖（pywinpty 的 ConPTY 后端） --------------------------------
# 注意：pywinpty 3.x 的导入模块名是 ``winpty``（不是 ``pywinpty``），包目录里
# 除了 _winpty*.pyd / winpty.dll / conpty.dll，还有 winpty-agent.exe 与
# OpenConsole.exe 这两个运行期可执行文件。它们不会被自动收集，必须显式打包，
# 否则冻结后的应用在启动 PTY 时会失败。
def _terminal_bundle() -> tuple[list, list]:
    datas: list = []
    binaries: list = []
    try:
        import winpty as _winpty  # pywinpty >= 3
    except ImportError:
        try:
            import pywinpty as _winpty  # type: ignore[no-redef]  # pywinpty 2.x
        except ImportError:
            return datas, binaries

    pkg = Path(_winpty.__file__).parent
    # 目的地必须与 winpty 包在 bundle 中的位置一致：winpty.dll 会按相对自身
    # 模块目录的方式寻找 winpty-agent.exe / OpenConsole.exe。
    target = "winpty"
    for path in pkg.rglob("*"):
        if not path.is_file():
            continue
        if "__pycache__" in path.parts or path.suffix in {".pyc", ".pyi"}:
            continue
        relative = path.relative_to(pkg).parent.as_posix()
        destination = f"{target}/{relative}" if relative != "." else target
        if path.suffix.lower() in {".dll", ".pyd", ".exe"}:
            binaries.append((str(path), destination))
        elif not path.name.startswith("test_"):
            datas.append((str(path), destination))
    return datas, binaries


TERMINAL_DATAS, TERMINAL_BINARIES = _terminal_bundle()

TERMINAL_HIDDENIMPORTS = [
    "codex_switch.ui_v2.terminal",
    "codex_switch.ui_v2.terminal.manager",
    "codex_switch.ui_v2.terminal.pty_session",
    "codex_switch.ui_v2.terminal.screen",
    "codex_switch.ui_v2.terminal.completion",
    "codex_switch.ui_v2.terminal.logging_setup",
    "codex_switch.ui_v2.viewmodels.terminal",
    # pywinpty 3.x 的真实模块名；旧名一并列出以兼容 2.x 环境。
    "winpty",
    "winpty.ptyprocess",
    "winpty.enums",
    "pywinpty",
    "pyte",
    "pyte.streams",
    "pyte.screens",
    "wcwidth",
    "psutil",
]


a = Analysis(
    ['main.py'],
    pathex=[str(ROOT), str(SRC_ROOT)],
    binaries=TERMINAL_BINARIES,
    datas=(
        TKINTER_DATAS
        + APP_DATAS
        + QML_DATAS
        + ICON_DATAS
        + TTKBOOTSTRAP_DATAS
        + TERMINAL_DATAS
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
