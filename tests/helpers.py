from __future__ import annotations

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import shutil
import sys
import threading
import uuid


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for path in (SRC, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


TEST_ROOT = Path.cwd() / ".test-temp"


@contextmanager
def workspace_tempdir():
    TEST_ROOT.mkdir(exist_ok=True)
    path = TEST_ROOT / uuid.uuid4().hex
    path.mkdir(parents=True, exist_ok=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def start_test_server(handler_cls: type[BaseHTTPRequestHandler]) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


_GIT_CLONE_PROBE: tuple[bool, str] | None = None


def git_clone_available(timeout: int = 15) -> tuple[bool, str]:
    """Check whether git can perform *remote* operations in this environment.

    Returns ``(available, reason)``. Git for Windows runs remote transports
    through its bundled ``sh.exe``; some sandboxes block the named pipes that
    process needs, so ``clone`` / ``ls-remote`` fail immediately or hang.

    Crucially, ``subprocess.run(capture_output=True)`` makes the failure mode a
    *hard hang*: Python's pipe reader thread waits forever on a child that never
    produced output. Probing with ``stdout/stderr=DEVNULL`` avoids pipes
    entirely, so the call either returns quickly (failure) or times out
    cleanly. The result is cached because a failing probe costs one timeout.
    """
    global _GIT_CLONE_PROBE
    if _GIT_CLONE_PROBE is not None:
        return _GIT_CLONE_PROBE

    result = _probe_git_clone(timeout)
    _GIT_CLONE_PROBE = result
    return result


def _probe_git_clone(timeout: int) -> tuple[bool, str]:
    import shutil
    import subprocess

    def run_quiet(*args: str) -> subprocess.CompletedProcess:
        # DEVNULL (never pipes) keeps a dying MSYS sh from wedging the reader thread.
        return subprocess.run(
            ["git", *args],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
            check=False,
        )

    try:
        if run_quiet("--version").returncode != 0:
            return False, "git is not available"
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"git is not available: {exc}"

    TEST_ROOT.mkdir(exist_ok=True)
    root = TEST_ROOT / f"git-probe-{uuid.uuid4().hex}"
    root.mkdir(parents=True, exist_ok=True)
    try:
        remote = root / "remote"
        remote.mkdir()
        (remote / "probe.txt").write_text("probe", encoding="utf-8")
        local = root / "local"

        try:
            if run_quiet("-C", str(remote), "init").returncode != 0:
                return False, "git init failed"
            run_quiet("-C", str(remote), "add", ".")
            committed = run_quiet(
                "-C", str(remote), "-c", "user.name=Probe", "-c", "user.email=probe@example.test",
                "commit", "-m", "probe",
            )
            if committed.returncode != 0:
                return False, "git commit failed"
            # clone exercises the MSYS sh transport that sandboxes often block.
            if run_quiet("clone", str(remote), str(local)).returncode != 0:
                return False, "git clone is unavailable (sandbox blocks the MSYS sh named pipe)"
            if run_quiet("-C", str(local), "rev-parse", "HEAD").returncode != 0:
                return False, "git clone produced no usable repository"
        except subprocess.TimeoutExpired:
            return False, "git clone hangs (sandbox blocks the MSYS sh named pipe)"
        except (OSError, subprocess.SubprocessError) as exc:
            return False, f"git clone failed: {exc}"
        return True, ""
    finally:
        shutil.rmtree(root, ignore_errors=True)
