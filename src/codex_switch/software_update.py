from __future__ import annotations

from dataclasses import dataclass
import json
import re
from urllib import error, parse, request


DEFAULT_SOFTWARE_UPDATE_REPO = "https://github.com/shixiansi/codex-switch"
GITHUB_API_BASE = "https://api.github.com"


@dataclass(frozen=True)
class SoftwareUpdateInfo:
    current_version: str
    latest_version: str
    release_url: str
    download_url: str = ""
    release_name: str = ""

    @property
    def update_available(self) -> bool:
        return is_newer_version(self.latest_version, self.current_version)


def version_key(value: str) -> tuple[int, ...]:
    normalized = str(value or "").strip()
    normalized = normalized[1:] if normalized[:1].casefold() == "v" else normalized
    normalized = normalized.split("+", 1)[0].split("-", 1)[0]
    numbers = [int(part) for part in re.findall(r"\d+", normalized)]
    if not numbers:
        return (0,)
    while len(numbers) < 3:
        numbers.append(0)
    return tuple(numbers)


def is_newer_version(candidate: str, current: str) -> bool:
    return version_key(candidate) > version_key(current)


def github_latest_release_api_url(repo_url: str) -> str:
    owner, repo = github_repo_parts(repo_url)
    return f"{GITHUB_API_BASE}/repos/{owner}/{repo}/releases/latest"


def github_repo_parts(repo_url: str) -> tuple[str, str]:
    parsed = parse.urlparse(str(repo_url or "").strip())
    host = (parsed.hostname or "").casefold()
    if host == "www.github.com":
        host = "github.com"
    parts = [part for part in parsed.path.strip("/").split("/") if part]
    if parsed.scheme != "https" or host != "github.com" or len(parts) != 2:
        raise ValueError("Software update repository must be a GitHub HTTPS repository URL.")
    owner, repo = parts
    repo = repo[:-4] if repo.endswith(".git") else repo
    return owner, repo


def github_latest_release_page_url(repo_url: str) -> str:
    owner, repo = github_repo_parts(repo_url)
    return f"https://github.com/{owner}/{repo}/releases/latest"


def _asset_score(asset_name: str) -> tuple[int, int, int]:
    normalized = asset_name.casefold()
    platform_score = 1 if any(token in normalized for token in ("windows", "win64", "win-x64", "x64")) else 0
    package_score = 1 if normalized.endswith((".zip", ".exe", ".msi")) else 0
    name_score = 1 if "codexswitch" in normalized or "codex-switch" in normalized else 0
    return platform_score, package_score, name_score


def preferred_release_download_url(assets: object) -> str:
    if not isinstance(assets, list):
        return ""
    candidates: list[tuple[tuple[int, int, int], str]] = []
    for item in assets:
        if not isinstance(item, dict):
            continue
        url = str(item.get("browser_download_url") or "").strip()
        if not url:
            continue
        name = str(item.get("name") or url).strip()
        candidates.append((_asset_score(name), url))
    if not candidates:
        return ""
    candidates.sort(reverse=True)
    return candidates[0][1]


def software_update_info_from_github_release(payload: object, current_version: str) -> SoftwareUpdateInfo:
    if not isinstance(payload, dict):
        raise ValueError("GitHub latest release response must be a JSON object.")
    latest_version = str(payload.get("tag_name") or payload.get("name") or "").strip()
    if not latest_version:
        raise ValueError("GitHub latest release response does not include a version tag.")
    release_url = str(payload.get("html_url") or "").strip()
    return SoftwareUpdateInfo(
        current_version=str(current_version or "").strip(),
        latest_version=latest_version,
        release_url=release_url,
        download_url=preferred_release_download_url(payload.get("assets")),
        release_name=str(payload.get("name") or latest_version).strip(),
    )


def software_update_info_from_release_url(release_url: str, current_version: str) -> SoftwareUpdateInfo:
    normalized_url = str(release_url or "").strip()
    parsed = parse.urlparse(normalized_url)
    path_parts = [parse.unquote(part) for part in parsed.path.strip("/").split("/") if part]
    latest_version = path_parts[-1] if len(path_parts) >= 4 and path_parts[-2] == "tag" and path_parts[-3] == "releases" else ""
    if not latest_version:
        raise RuntimeError("GitHub latest release page did not resolve to a release tag.")
    return SoftwareUpdateInfo(
        current_version=str(current_version or "").strip(),
        latest_version=latest_version,
        release_url=normalized_url,
        release_name=latest_version,
    )


class SoftwareUpdateChecker:
    def __init__(self, repo_url: str = DEFAULT_SOFTWARE_UPDATE_REPO, *, timeout: int = 10) -> None:
        self.repo_url = repo_url
        self.timeout = timeout

    def check(self, current_version: str) -> SoftwareUpdateInfo:
        api_url = github_latest_release_api_url(self.repo_url)
        req = request.Request(
            api_url,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": f"CodexSwitch/{current_version or 'unknown'}",
            },
            method="GET",
        )
        try:
            with request.urlopen(req, timeout=self.timeout) as response:
                text = response.read().decode("utf-8", errors="replace")
        except error.HTTPError as exc:
            if exc.code == 404:
                raise RuntimeError("GitHub Releases has no published latest version.") from exc
            if exc.code == 403:
                return self._check_latest_release_page(current_version)
            raise RuntimeError(f"GitHub update check failed: HTTP {exc.code}") from exc
        except error.URLError as exc:
            reason = str(exc.reason or "").strip() or "unknown network error"
            raise RuntimeError(f"GitHub update check failed: {reason}") from exc
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise RuntimeError("GitHub latest release response is not valid JSON.") from exc
        return software_update_info_from_github_release(payload, current_version)

    def _check_latest_release_page(self, current_version: str) -> SoftwareUpdateInfo:
        latest_url = github_latest_release_page_url(self.repo_url)
        req = request.Request(
            latest_url,
            headers={
                "Accept": "text/html,application/xhtml+xml",
                "User-Agent": f"CodexSwitch/{current_version or 'unknown'}",
            },
            method="GET",
        )
        try:
            with request.urlopen(req, timeout=self.timeout) as response:
                resolved_url = str(response.geturl() or latest_url).strip()
        except error.HTTPError as exc:
            raise RuntimeError(f"GitHub update check failed: HTTP {exc.code}") from exc
        except error.URLError as exc:
            reason = str(exc.reason or "").strip() or "unknown network error"
            raise RuntimeError(f"GitHub update check failed: {reason}") from exc
        return software_update_info_from_release_url(resolved_url, current_version)
