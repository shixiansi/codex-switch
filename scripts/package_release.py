from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import zipfile


ROOT = Path(__file__).resolve().parents[1]
APP_NAME = "CodexSwitch"


def run(command: list[str]) -> None:
    subprocess.run(command, cwd=ROOT, check=True)


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

    for path in (pyinstaller_dist, pyinstaller_work, staging_dir):
        clean_path(path)

    artifacts_dir.mkdir(parents=True, exist_ok=True)
    spec_dir.mkdir(parents=True, exist_ok=True)

    run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--onefile",
            "--windowed",
            "--name",
            APP_NAME,
            "--distpath",
            str(pyinstaller_dist),
            "--workpath",
            str(pyinstaller_work),
            "--specpath",
            str(spec_dir),
            "main.py",
        ]
    )

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
