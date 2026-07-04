from __future__ import annotations

from pathlib import Path
import subprocess

from codex_switch.models import ProjectRecord, SkillMarketRepo
from codex_switch.ui.update_logic import (
    GitRemoteUpdate,
    git_fetch_ref_candidates,
    git_remote_ref_patterns,
    is_git_commit_ref,
    normalize_git_ref,
    remote_commit_from_ls_remote,
    same_git_commit,
)


def git_remote_commit(
    url: str,
    ref: str,
    *,
    default_ref: str,
    run_command=subprocess.run,
) -> str:
    normalized_ref = normalize_git_ref(ref, default=default_ref)
    if is_git_commit_ref(normalized_ref):
        return normalized_ref.casefold()
    patterns = git_remote_ref_patterns(normalized_ref)
    completed = run_command(
        ["git", "ls-remote", url, *patterns],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    if completed.returncode != 0 or not completed.stdout.strip():
        detail = completed.stderr.strip() or "\u8fdc\u7aef\u6ca1\u6709\u8fd4\u56de\u63d0\u4ea4\u4fe1\u606f\u3002"
        raise RuntimeError(detail)
    commit = remote_commit_from_ls_remote(completed.stdout, normalized_ref)
    if not commit:
        raise RuntimeError("\u8fdc\u7aef\u6ca1\u6709\u8fd4\u56de\u63d0\u4ea4\u4fe1\u606f\u3002")
    return commit


def git_local_commit(git_root: Path, *, run_command=subprocess.run) -> str:
    if not (git_root / ".git").exists():
        return ""
    completed = run_command(
        ["git", "-C", str(git_root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    return completed.stdout.strip() if completed.returncode == 0 else ""


def skill_repo_remote_update(
    repo: SkillMarketRepo,
    *,
    default_ref: str,
    cache_dir: Path,
    run_command=subprocess.run,
) -> GitRemoteUpdate:
    repo_ref = normalize_git_ref(repo.branch, default=default_ref)
    latest_commit = git_remote_commit(repo.url, repo_ref, default_ref=default_ref, run_command=run_command)
    previous_commit = repo.last_sync_commit or git_local_commit(cache_dir, run_command=run_command)
    return GitRemoteUpdate(latest_commit=latest_commit, previous_commit=previous_commit)


def project_remote_update(
    project: ProjectRecord,
    *,
    default_ref: str,
    project_root: Path,
    run_command=subprocess.run,
) -> GitRemoteUpdate:
    latest_commit = git_remote_commit(
        project.github_repo,
        project.github_ref,
        default_ref=default_ref,
        run_command=run_command,
    )
    previous_commit = project.github_last_sync_commit or git_local_commit(project_root, run_command=run_command)
    return GitRemoteUpdate(latest_commit=latest_commit, previous_commit=previous_commit)


def run_git_command(
    args: list[str],
    *,
    timeout: int,
    fallback_error: str,
    run_command=subprocess.run,
) -> None:
    completed = run_command(
        args,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or fallback_error
        raise RuntimeError(detail)


def fetch_remote_ref(
    repo_root: Path,
    ref: str,
    *,
    remote: str = "origin",
    run_command=subprocess.run,
) -> None:
    last_detail = ""
    for candidate in git_fetch_ref_candidates(ref):
        completed = run_command(
            ["git", "-C", str(repo_root), "fetch", "--depth", "1", remote, candidate],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        if completed.returncode == 0:
            return
        last_detail = completed.stderr.strip() or completed.stdout.strip()
    raise RuntimeError(last_detail or "git fetch \u5931\u8d25\u3002")


def sync_repo_cache(
    cache_dir: Path,
    *,
    remote_url: str,
    ref: str,
    target_commit: str,
    run_command=subprocess.run,
) -> str:
    cache_dir.parent.mkdir(parents=True, exist_ok=True)
    if not (cache_dir / ".git").exists():
        run_git_command(
            ["git", "init", str(cache_dir)],
            timeout=20,
            fallback_error="\u521d\u59cb\u5316\u4ed3\u5e93\u7f13\u5b58\u5931\u8d25\u3002",
            run_command=run_command,
        )
        run_git_command(
            ["git", "-C", str(cache_dir), "remote", "add", "origin", remote_url],
            timeout=20,
            fallback_error="\u8bbe\u7f6e\u8fdc\u7aef\u5730\u5740\u5931\u8d25\u3002",
            run_command=run_command,
        )
    else:
        run_git_command(
            ["git", "-C", str(cache_dir), "remote", "set-url", "origin", remote_url],
            timeout=20,
            fallback_error="\u66f4\u65b0\u8fdc\u7aef\u5730\u5740\u5931\u8d25\u3002",
            run_command=run_command,
        )
    fetch_remote_ref(cache_dir, ref, run_command=run_command)
    run_git_command(
        ["git", "-C", str(cache_dir), "checkout", "--detach", "--force", target_commit],
        timeout=120,
        fallback_error="\u5207\u6362\u4ed3\u5e93 ref \u5931\u8d25\u3002",
        run_command=run_command,
    )
    completed = run_command(
        ["git", "-C", str(cache_dir), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    synced_commit = completed.stdout.strip() if completed.returncode == 0 else ""
    if not synced_commit:
        raise RuntimeError("\u65e0\u6cd5\u786e\u8ba4\u4ed3\u5e93\u540c\u6b65\u540e\u7684 HEAD\u3002")
    if not same_git_commit(synced_commit, target_commit):
        raise RuntimeError(
            "\u4ed3\u5e93\u540c\u6b65\u540e\u7684 HEAD \u4e0e\u68c0\u6d4b\u5230\u7684\u8fdc\u7aef\u63d0\u4ea4\u4e0d\u4e00\u81f4\uff0c\u8bf7\u91cd\u65b0\u68c0\u67e5\u66f4\u65b0\u3002"
        )
    return synced_commit


def fetch_project_ref(
    project_root: Path,
    url: str,
    ref: str,
    *,
    run_command=subprocess.run,
) -> bool:
    for candidate in git_fetch_ref_candidates(ref):
        completed = run_command(
            ["git", "-C", str(project_root), "fetch", url, candidate],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        if completed.returncode == 0:
            return True
    return False


def sync_project_checkout(
    project_root: Path,
    *,
    remote_url: str,
    ref: str,
    latest_commit: str,
    default_ref: str,
    run_command=subprocess.run,
) -> str:
    github_ref = normalize_git_ref(ref, default=default_ref)
    pull_args = ["git", "-C", str(project_root), "pull", "--ff-only"]
    if github_ref != default_ref:
        pull_args.extend([remote_url, github_ref])
    completed = run_command(
        pull_args,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if completed.returncode != 0:
        if github_ref == default_ref or not remote_url:
            detail = completed.stderr.strip() or completed.stdout.strip() or "git pull \u5931\u8d25\u3002"
            raise RuntimeError(detail)
        if not fetch_project_ref(project_root, remote_url, github_ref, run_command=run_command):
            detail = completed.stderr.strip() or completed.stdout.strip() or "git fetch \u5931\u8d25\u3002"
            raise RuntimeError(detail)
        checkout = run_command(
            ["git", "-C", str(project_root), "checkout", "--detach", latest_commit],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        if checkout.returncode != 0:
            detail = checkout.stderr.strip() or checkout.stdout.strip() or "\u5207\u6362\u9879\u76ee ref \u5931\u8d25\u3002"
            raise RuntimeError(detail)
    synced_commit = git_local_commit(project_root, run_command=run_command)
    if not synced_commit:
        raise RuntimeError("\u65e0\u6cd5\u786e\u8ba4\u9879\u76ee\u66f4\u65b0\u540e\u7684 HEAD\u3002")
    if not same_git_commit(synced_commit, latest_commit):
        raise RuntimeError(
            "\u9879\u76ee\u66f4\u65b0\u540e\u7684 HEAD \u4e0e\u68c0\u6d4b\u5230\u7684\u8fdc\u7aef\u63d0\u4ea4\u4e0d\u4e00\u81f4\uff0c\u8bf7\u91cd\u65b0\u68c0\u67e5\u66f4\u65b0\u3002"
        )
    return synced_commit
