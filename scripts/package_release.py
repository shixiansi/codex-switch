from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import zipfile


ROOT = Path(__file__).resolve().parents[1]
APP_NAME = "CodexSwitch"
SPEC_PATH = ROOT / "CodexSwitch.spec"


def run(command: list[str]) -> None:
    subprocess.run(command, cwd=ROOT, check=True, env=build_env())


def build_env() -> dict[str, str]:
    env = dict(os.environ)
    base_prefix = Path(sys.base_prefix)
    expected_dirs = {
        "TCL_LIBRARY": (base_prefix / "tcl" / "tcl8.6", base_prefix / "tcl" / "tcl8"),
        "TK_LIBRARY": (base_prefix / "tcl" / "tk8.6",),
    }

    for env_key, candidates in expected_dirs.items():
        current_value = env.get(env_key, "").strip()
        if current_value and Path(current_value).exists():
            continue

        env.pop(env_key, None)
        for candidate in candidates:
            if candidate.exists():
                env[env_key] = str(candidate)
                break

    return env


def ensure_tkinter_available() -> None:
    subprocess.run([sys.executable, "-c", "import _tkinter, tkinter"], cwd=ROOT, check=True, env=build_env())


def assert_no_missing_tkinter_warning(warn_path: Path) -> None:
    if not warn_path.exists():
        return
    warn_text = warn_path.read_text(encoding="utf-8", errors="replace")
    if (
        "missing module named tkinter" in warn_text
        or "missing module named _tkinter" in warn_text
        or "tkinter installation is broken" in warn_text
    ):
        raise RuntimeError(
            f"PyInstaller reported tkinter as missing. Refusing to package a broken build.\nSee: {warn_path}"
        )


def clean_path(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
    elif path.exists():
        path.unlink()


def copy_artifact(source: Path, destination: Path) -> None:
    if source.is_dir():
        shutil.copytree(source, destination, dirs_exist_ok=True)
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def package_directory(staging_dir: Path, output_path: Path, target: str) -> None:
    if target.startswith("windows"):
        with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in staging_dir.rglob("*"):
                archive.write(path, path.relative_to(staging_dir))
        return

    with tarfile.open(output_path, "w:gz") as archive:
        archive.add(staging_dir, arcname=staging_dir.name)


def build(target: str, output_name: str) -> Path:
    pyinstaller_dist = ROOT / "build" / "pyinstaller-dist" / target
    pyinstaller_work = ROOT / "build" / "pyinstaller-work" / target
    spec_dir = ROOT / "build" / "pyinstaller-spec"
    staging_dir = ROOT / "build" / "release-staging" / output_name
    artifacts_dir = ROOT / "artifacts"
    warn_path = pyinstaller_work / APP_NAME / f"warn-{APP_NAME}.txt"

    for path in (pyinstaller_dist, pyinstaller_work, staging_dir):
        clean_path(path)

    artifacts_dir.mkdir(parents=True, exist_ok=True)
    spec_dir.mkdir(parents=True, exist_ok=True)
    ensure_tkinter_available()

    run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--distpath",
            str(pyinstaller_dist),
            "--workpath",
            str(pyinstaller_work),
            "--specpath",
            str(spec_dir),
            str(SPEC_PATH),
        ]
    )
    assert_no_missing_tkinter_warning(warn_path)

    built_outputs = [path for path in pyinstaller_dist.iterdir() if path.name.startswith(APP_NAME)]
    if not built_outputs:
        raise RuntimeError(f"No packaged output found in {pyinstaller_dist}")

    staging_dir.mkdir(parents=True, exist_ok=True)
    package_root = staging_dir / output_name
    package_root.mkdir(parents=True, exist_ok=True)

    for output in built_outputs:
        copy_artifact(output, package_root / output.name)

    readme = ROOT / "README.md"
    if readme.exists():
        shutil.copy2(readme, package_root / "README.md")

    extension = ".zip" if target.startswith("windows") else ".tar.gz"
    output_path = artifacts_dir / f"{output_name}{extension}"
    clean_path(output_path)
    package_directory(package_root, output_path, target)
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a release archive for the current platform.")
    parser.add_argument("--target", required=True, help="Target id, e.g. windows-x64 / linux-x64 / macos-x64")
    parser.add_argument("--output-name", required=True, help="Output file base name")
    args = parser.parse_args()

    output_path = build(args.target, args.output_name)
    print(f"Built archive: {output_path}")


if __name__ == "__main__":
    main()
