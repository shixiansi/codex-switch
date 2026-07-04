from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path


HOT_UPDATE_CHECKSUM_MANIFEST_RELATIVE_PATHS = (
    Path("codex-switch-checksums.json"),
    Path(".codex-switch") / "checksums.json",
)
DEFAULT_PROJECT_GITHUB_REF = "HEAD"
DEFAULT_SKILL_REPO_REF = "main"


def normalize_git_ref(ref: str | None, *, default: str) -> str:
    normalized = str(ref or "").strip()
    return normalized or default


def is_git_commit_ref(ref: str) -> bool:
    normalized = ref.strip()
    return len(normalized) in (40, 64) and all(char in "0123456789abcdefABCDEF" for char in normalized)


def same_git_commit(actual: str, expected: str) -> bool:
    actual_normalized = actual.strip().casefold()
    expected_normalized = expected.strip().casefold()
    return bool(actual_normalized) and actual_normalized == expected_normalized


def git_remote_ref_patterns(ref: str) -> list[str]:
    normalized = normalize_git_ref(ref, default=DEFAULT_PROJECT_GITHUB_REF)
    if is_git_commit_ref(normalized):
        return []
    if normalized == "HEAD":
        return ["HEAD"]
    if normalized.endswith("^{}"):
        return [normalized]
    if normalized.startswith("refs/tags/"):
        return [f"{normalized}^{{}}", normalized]
    if normalized.startswith("refs/"):
        return [normalized]
    return [f"refs/heads/{normalized}", f"refs/tags/{normalized}^{{}}", f"refs/tags/{normalized}", normalized]


def git_fetch_ref_candidates(ref: str) -> list[str]:
    normalized = normalize_git_ref(ref, default=DEFAULT_PROJECT_GITHUB_REF)
    if normalized.endswith("^{}"):
        normalized = normalized[:-3]
    if normalized == "HEAD" or is_git_commit_ref(normalized) or normalized.startswith("refs/"):
        return [normalized]
    return [normalized, f"refs/heads/{normalized}", f"refs/tags/{normalized}"]


def remote_commit_from_ls_remote(output: str, ref: str) -> str:
    entries: list[tuple[str, str]] = []
    for line in output.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            entries.append((parts[0], parts[1]))
    if not entries:
        return ""
    for pattern in git_remote_ref_patterns(ref):
        for commit, remote_ref in entries:
            if remote_ref == pattern:
                return commit
    return entries[0][0]


def _normalize_checksum_manifest_path(value: object) -> str:
    raw_path = str(value or "").strip().replace("\\", "/")
    if not raw_path or raw_path.startswith("/"):
        raise RuntimeError("Checksum manifest contains an unsafe path.")
    parts = [part for part in raw_path.split("/") if part and part != "."]
    if not parts or any(part == ".." for part in parts) or parts[0].endswith(":"):
        raise RuntimeError("Checksum manifest contains an unsafe path.")
    return Path(*parts).as_posix()


def _normalize_sha256_digest(value: object) -> str:
    digest = str(value or "").strip().casefold()
    if digest.startswith("sha256:"):
        digest = digest[len("sha256:") :]
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise RuntimeError("Checksum manifest contains an invalid SHA-256 digest.")
    return digest


def checksum_manifest_entries(payload: object) -> dict[str, str]:
    if not isinstance(payload, dict):
        raise RuntimeError("Checksum manifest must be a JSON object.")
    algorithm = str(payload.get("algorithm") or "sha256").strip().casefold()
    if algorithm != "sha256":
        raise RuntimeError("Checksum manifest must use SHA-256.")
    raw_entries = payload.get("sha256")
    entries: dict[str, str] = {}
    if isinstance(raw_entries, dict):
        for raw_path, raw_digest in raw_entries.items():
            entries[_normalize_checksum_manifest_path(raw_path)] = _normalize_sha256_digest(raw_digest)
    elif isinstance(payload.get("files"), list):
        for item in payload["files"]:
            if not isinstance(item, dict):
                raise RuntimeError("Checksum manifest file entries must be objects.")
            entries[_normalize_checksum_manifest_path(item.get("path"))] = _normalize_sha256_digest(
                item.get("sha256") or item.get("digest")
            )
    else:
        raise RuntimeError("Checksum manifest must contain SHA-256 entries.")
    if not entries:
        raise RuntimeError("Checksum manifest must contain SHA-256 entries.")
    return entries


def hot_update_checksum_manifest_path(repo_root: Path) -> Path | None:
    for relative_path in HOT_UPDATE_CHECKSUM_MANIFEST_RELATIVE_PATHS:
        manifest_path = repo_root / relative_path
        if manifest_path.is_file():
            return manifest_path
    return None


def sha256_file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_hot_update_checksums(repo_root: Path, required_paths: list[Path]) -> bool:
    manifest_path = hot_update_checksum_manifest_path(repo_root)
    if manifest_path is None:
        return False
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Checksum manifest is unreadable: {exc}") from exc
    checksums = checksum_manifest_entries(payload)
    root = repo_root.resolve()
    for relative_path in checksums:
        target = (root / relative_path).resolve()
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise RuntimeError("Checksum manifest contains an unsafe path.") from exc
    for required_path in required_paths:
        if not required_path.is_file():
            continue
        relative_path = required_path.resolve().relative_to(root).as_posix()
        expected_digest = checksums.get(relative_path)
        if expected_digest is None:
            raise RuntimeError(f"Checksum manifest is missing {relative_path}.")
        actual_digest = sha256_file_digest(required_path)
        if actual_digest != expected_digest:
            raise RuntimeError(f"Checksum mismatch for {relative_path}.")
    return True


@dataclass(frozen=True)
class GitRemoteUpdate:
    latest_commit: str
    previous_commit: str

    @property
    def has_update(self) -> bool:
        return bool(self.latest_commit) and self.latest_commit != self.previous_commit

    @property
    def short_latest(self) -> str:
        return self.latest_commit[:12] if self.latest_commit else "-"


def software_update_error_detail(error: object) -> str:
    message = str(error or "").strip()
    normalized = message.casefold()
    if not message or normalized == "none" or normalized.endswith(": none") or normalized.endswith("- none"):
        return "未能获取 GitHub 最新版本信息，请检查网络或稍后重试。"
    return message
