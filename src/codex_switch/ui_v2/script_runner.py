"""Tracks script processes so the UI can show live run state.

One class owns the whole lifecycle: starting a process (windowed or hidden),
capturing its output to a log file, polling for completion and cleaning up the
temporary script file. Keeping it out of ``workspace.py`` leaves that module
with business rules only, and makes the runner testable without Qt or a real
shell.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import subprocess
from typing import Any

from ..models import now_iso

STATUS_IDLE = "idle"
STATUS_RUNNING = "running"
STATUS_SUCCESS = "success"
STATUS_FAILED = "failed"
STATUS_STOPPED = "stopped"

# How much of a log the detail panel shows; the file keeps everything.
OUTPUT_TAIL_LINES = 200

# Console programs on a Chinese Windows write the OEM code page (GBK/cp936),
# not UTF-8. The log keeps the raw bytes, so decoding has to detect which one a
# run actually produced; guessing UTF-8 unconditionally mangled every Chinese
# line into U+FFFD.
_PREFERRED_ENCODINGS = ("utf-8", "mbcs", "cp936", "gbk", "big5", "utf-16")


def decode_output(data: bytes) -> str:
    """Decode captured console bytes, preferring a strict UTF-8 reading.

    UTF-8 is tried first so modern tools (and our own ``PYTHONIOENCODING``
    children) stay lossless. Anything that is *not* valid UTF-8 is far more
    likely to be the local ANSI/OEM code page, so that is tried next. Only if
    every candidate fails do we fall back to a lossy decode, which keeps
    mojibake out of the UI while still showing something.
    """
    if not data:
        return ""
    for encoding in _PREFERRED_ENCODINGS:
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", errors="replace")


def _read_log_bytes(log_path: str) -> bytes:
    try:
        return Path(log_path).read_bytes()
    except OSError:
        return b""


@dataclass
class ScriptRun:
    """Live state of one script launch."""

    script_id: str
    status: str = STATUS_RUNNING
    started_at: str = ""
    finished_at: str = ""
    exit_code: int | None = None
    log_path: str = ""
    temp_path: str = ""

    @property
    def running(self) -> bool:
        return self.status == STATUS_RUNNING

    @property
    def output_tail(self) -> str:
        if not self.log_path:
            return ""
        text = decode_output(_read_log_bytes(self.log_path))
        if not text:
            return ""
        lines = text.splitlines()
        if len(lines) > OUTPUT_TAIL_LINES:
            lines = [f"… 仅显示最后 {OUTPUT_TAIL_LINES} 行，完整内容见日志文件。", *lines[-OUTPUT_TAIL_LINES:]]
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scriptId": self.script_id,
            "status": self.status,
            "startedAt": self.started_at,
            "finishedAt": self.finished_at,
            "exitCode": self.exit_code,
            "logPath": self.log_path,
            "output": self.output_tail,
        }


def _hidden_process_kwargs() -> dict[str, Any]:
    """Flags that start a process with no console window (Windows only)."""
    if os.name != "nt":
        return {}
    startupinfo = subprocess.STARTUPINFO()  # type: ignore[attr-defined]
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW  # type: ignore[attr-defined]
    startupinfo.wShowWindow = 0  # SW_HIDE
    return {
        "startupinfo": startupinfo,
        "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0),
    }


class ScriptRunManager:
    """Starts, watches and stops script processes (at most one per script)."""

    def __init__(self, log_dir: Path | str | None = None) -> None:
        self.log_dir = Path(log_dir) if log_dir else None
        self._runs: dict[str, ScriptRun] = {}
        self._processes: dict[str, subprocess.Popen] = {}
        self._streams: dict[str, Any] = {}

    # -- queries ---------------------------------------------------------
    def is_running(self, script_id: str) -> bool:
        return script_id in self._processes

    def run(self, script_id: str) -> ScriptRun | None:
        return self._runs.get(script_id)

    def snapshot(self, script_id: str) -> dict[str, Any]:
        run = self._runs.get(script_id)
        if run is None:
            return {"scriptId": script_id, "status": STATUS_IDLE, "exitCode": None, "output": ""}
        return run.to_dict()

    def running_count(self) -> int:
        return len(self._processes)

    def forget(self, script_id: str) -> None:
        """Drop stored state for a deleted script (its process keeps running)."""
        self._runs.pop(script_id, None)
        self._processes.pop(script_id, None)
        stream = self._streams.pop(script_id, None)
        if stream is not None:
            try:
                stream.close()
            except OSError:
                pass

    # -- lifecycle -------------------------------------------------------
    def start(
        self,
        script_id: str,
        argv: list[str],
        *,
        cwd: str | None = None,
        hidden: bool = False,
        temp_path: str = "",
        env_extra: dict[str, str] | None = None,
    ) -> ScriptRun:
        log_path = ""
        stdout = None
        if hidden:
            try:
                log_path = self._open_log(script_id)
                # Raw bytes on purpose: the child writes whatever its console
                # code page produces, and decode_output() works it out later.
                stdout = open(log_path, "wb")  # noqa: SIM115 - closed on finish
            except OSError as exc:
                raise OSError(f"无法创建脚本日志文件：{exc}") from exc

        kwargs: dict[str, Any] = {"cwd": cwd}
        if env_extra:
            # Inherit the parent environment rather than replacing it, so the
            # caller only has to name the variables it wants to override.
            kwargs["env"] = {**os.environ, **env_extra}
        if hidden:
            kwargs.update(_hidden_process_kwargs())
            kwargs.update({"stdout": stdout, "stderr": subprocess.STDOUT, "stdin": subprocess.DEVNULL})
        else:
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)

        try:
            process = subprocess.Popen(argv, **kwargs)  # noqa: S603 - user-authored script
        except OSError:
            if stdout is not None:
                stdout.close()
            raise

        run = ScriptRun(
            script_id=script_id,
            status=STATUS_RUNNING,
            started_at=now_iso(),
            log_path=log_path,
            temp_path=temp_path,
        )
        self._runs[script_id] = run
        self._processes[script_id] = process
        if stdout is not None:
            self._streams[script_id] = stdout
        return run

    def stop(self, script_id: str) -> bool:
        """Ask a running script to terminate; returns False when none is running."""
        process = self._processes.get(script_id)
        if process is None:
            return False
        try:
            process.terminate()
        except OSError:
            self._finish(script_id, process, STATUS_STOPPED)
        return True

    def poll(self) -> list[str]:
        """Reap finished processes; returns the script ids whose state changed."""
        changed: list[str] = []
        for script_id, process in list(self._processes.items()):
            if process.poll() is None:
                continue
            status = STATUS_SUCCESS if process.returncode == 0 else STATUS_FAILED
            self._finish(script_id, process, status)
            changed.append(script_id)
        return changed

    def shutdown(self) -> None:
        """Best-effort cleanup when the app closes; never raises."""
        for script_id in list(self._processes):
            try:
                self._processes[script_id].terminate()
            except OSError:
                pass
        for stream in self._streams.values():
            try:
                stream.close()
            except OSError:
                pass
        self._processes.clear()
        self._streams.clear()
        for run in self._runs.values():
            if run.running:
                run.status = STATUS_STOPPED
        self._runs.clear()

    # -- internals -------------------------------------------------------
    def _finish(self, script_id: str, process: subprocess.Popen, status: str) -> None:
        run = self._runs.get(script_id)
        if run is not None:
            run.status = status
            run.exit_code = process.returncode
            run.finished_at = now_iso()
        # The log handle is owned here, not by the Popen: mock processes in
        # tests have no real stdout, and a real one is closed by the OS anyway.
        stream = self._streams.pop(script_id, None)
        if stream is not None:
            try:
                stream.close()
            except OSError:
                pass
        self._processes.pop(script_id, None)
        if run is not None:
            self._remove_temp(run.temp_path)

    def _remove_temp(self, temp_path: str) -> None:
        if not temp_path:
            return
        try:
            Path(temp_path).unlink(missing_ok=True)
        except OSError:
            # A leftover temp script is harmless; never fail a run because of it.
            pass

    def _open_log(self, script_id: str) -> str:
        directory = self.log_dir or (Path(os.environ.get("TEMP") or ".") / "codex-switch-scripts")
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError:
            return ""
        safe_id = "".join(char for char in script_id if char.isalnum() or char in "-_") or "script"
        path = directory / f"{safe_id}.log"
        try:
            path.write_text("", encoding="utf-8")
        except OSError:
            return ""
        return str(path)


__all__ = [
    "OUTPUT_TAIL_LINES",
    "STATUS_FAILED",
    "STATUS_IDLE",
    "STATUS_RUNNING",
    "STATUS_STOPPED",
    "STATUS_SUCCESS",
    "ScriptRun",
    "ScriptRunManager",
]
