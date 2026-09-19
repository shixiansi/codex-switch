"""Tracks script processes so the UI can show live run state.

One class owns the whole lifecycle: starting a process (windowed or hidden),
capturing its output to a log file, polling for completion and cleaning up the
temporary script file. Keeping it out of ``workspace.py`` leaves that module
with business rules only, and makes the runner testable without Qt or a real
shell.

Background (hidden) runs are meant to outlive the app: each launch records
``{scriptId, pid, logPath, ...}`` to a state file, and the next launch adopts
the entries whose pid is still alive so the UI shows them as running again.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import os
import subprocess
from typing import Any

from ..models import now_iso
# 进程/日志的通用实现抽到了 codex_switch.process_util：DSH 多开插件同样需要
# 这些能力，而插件不能 import 本包（ui_v2/__init__ 会拉起 Qt）。这里继续从
# 原位置导出，历史调用方与测试不受影响（DRY）。
from ..process_util import (
    decode_output,
    hidden_process_kwargs,
    kill_pid,
    pid_alive,
)

STATUS_IDLE = "idle"
STATUS_RUNNING = "running"
STATUS_SUCCESS = "success"
STATUS_FAILED = "failed"
STATUS_STOPPED = "stopped"

# How much of a log the detail panel shows; the file keeps everything.
OUTPUT_TAIL_LINES = 200

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
    pid: int = 0
    # Background runs outlive the app; windowed runs die with it.
    background: bool = False

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
    """Flags that start a process with no console window (Windows only).

    薄封装：真实实现在 :mod:`codex_switch.process_util`，与 DSH 多开插件共用。
    保留这个私有名字是为了不惊动本模块内部既有的调用点。
    """
    return hidden_process_kwargs()



class ScriptRunManager:
    """Starts, watches and stops script processes (at most one per script)."""

    def __init__(
        self,
        log_dir: Path | str | None = None,
        state_path: Path | str | None = None,
    ) -> None:
        self.log_dir = Path(log_dir) if log_dir else None
        self._state_path = Path(state_path) if state_path else None
        self._runs: dict[str, ScriptRun] = {}
        self._processes: dict[str, subprocess.Popen] = {}
        self._streams: dict[str, Any] = {}

    # -- queries ---------------------------------------------------------
    def is_running(self, script_id: str) -> bool:
        run = self._runs.get(script_id)
        return run is not None and run.running

    def run(self, script_id: str) -> ScriptRun | None:
        return self._runs.get(script_id)

    def snapshot(self, script_id: str) -> dict[str, Any]:
        run = self._runs.get(script_id)
        if run is None:
            return {"scriptId": script_id, "status": STATUS_IDLE, "exitCode": None, "output": ""}
        return run.to_dict()

    def running_count(self) -> int:
        return sum(1 for run in self._runs.values() if run.running)

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
        self._persist_state()

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

        pid = getattr(process, "pid", 0)
        run = ScriptRun(
            script_id=script_id,
            status=STATUS_RUNNING,
            started_at=now_iso(),
            log_path=log_path,
            temp_path=temp_path,
            pid=pid if isinstance(pid, int) else 0,
            background=hidden,
        )
        self._runs[script_id] = run
        self._processes[script_id] = process
        if stdout is not None:
            self._streams[script_id] = stdout
        if hidden:
            self._persist_state()
        return run

    def stop(self, script_id: str) -> bool:
        """Ask a running script to terminate; returns False when none is running."""
        process = self._processes.get(script_id)
        if process is not None:
            try:
                process.terminate()
            except OSError:
                self._finish(script_id, process, STATUS_STOPPED)
            return True
        run = self._runs.get(script_id)
        if run is None or not run.running:
            return False
        # Adopted from a previous session: there is no Popen, kill by pid.
        # The next poll notices the pid is gone and records the stop.
        kill_pid(run.pid)
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
        # Adopted runs have no Popen object; their pid is the only lifeline.
        for script_id, run in list(self._runs.items()):
            if script_id in self._processes or not run.running:
                continue
            if pid_alive(run.pid):
                continue
            run.status = STATUS_STOPPED
            run.finished_at = now_iso()
            self._remove_temp(run.temp_path)
            self._persist_state()
            changed.append(script_id)
        return changed

    def restore(self, known_ids: set[str] | None = None) -> list[str]:
        """Re-adopt background runs recorded by a previous session.

        Entries whose pid is gone (finished or machine-rebooted) are dropped;
        their log files stay on disk. ``known_ids`` filters out runs whose
        script was deleted while the app was closed. Returns adopted ids.
        """
        if self._state_path is None:
            return []
        try:
            entries = json.loads(self._state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        if not isinstance(entries, list):
            return []
        adopted: list[str] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            script_id = str(entry.get("scriptId") or "")
            pid = entry.get("pid")
            if not script_id or not isinstance(pid, int) or not pid_alive(pid):
                continue
            if known_ids is not None and script_id not in known_ids:
                continue
            self._runs[script_id] = ScriptRun(
                script_id=script_id,
                status=STATUS_RUNNING,
                started_at=str(entry.get("startedAt") or ""),
                log_path=str(entry.get("logPath") or ""),
                temp_path=str(entry.get("tempPath") or ""),
                pid=pid,
                background=True,
            )
            adopted.append(script_id)
        if entries:
            self._persist_state()
        return adopted

    def shutdown(self) -> None:
        """Best-effort cleanup when the app closes; never raises.

        Background runs are left alive on purpose — they outlive the app and
        the next launch re-adopts them from the state file. Windowed runs
        belong to a console the app opened, so they are asked to terminate.
        """
        for script_id, process in list(self._processes.items()):
            run = self._runs.get(script_id)
            if run is not None and run.background:
                continue
            try:
                process.terminate()
            except OSError:
                pass
        for stream in self._streams.values():
            try:
                stream.close()
            except OSError:
                pass
        self._processes.clear()
        self._streams.clear()
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
            self._persist_state()

    def _persist_state(self) -> None:
        """Record the background runs that are still alive, for the next launch."""
        if self._state_path is None:
            return
        entries = [
            {
                "scriptId": run.script_id,
                "pid": run.pid,
                "logPath": run.log_path,
                "tempPath": run.temp_path,
                "startedAt": run.started_at,
            }
            for run in self._runs.values()
            if run.background and run.running
        ]
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            self._state_path.write_text(
                json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError:
            # The state file is an optimization, never a hard requirement.
            pass

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
    "decode_output",
    "kill_pid",
    "pid_alive",
]
