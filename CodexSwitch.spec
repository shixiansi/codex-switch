# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_submodules


ROOT = Path.cwd()
SRC_ROOT = ROOT / "src"
BASE_PREFIX = Path(sys.base_prefix)
HOOKS_ROOT = ROOT / "pyinstaller-hooks"
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
APP_DATAS = collect_data_files("codex_switch", includes=["assets/*"])
TTKBOOTSTRAP_HIDDENIMPORTS = collect_submodules("ttkbootstrap")
TTKBOOTSTRAP_DATAS = collect_data_files("ttkbootstrap")


a = Analysis(
    ['main.py'],
    pathex=[str(ROOT), str(SRC_ROOT)],
    binaries=[],
    datas=TKINTER_DATAS + APP_DATAS + TTKBOOTSTRAP_DATAS,
    hiddenimports=TKINTER_HIDDENIMPORTS + TTKBOOTSTRAP_HIDDENIMPORTS,
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
