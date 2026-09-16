"""单个 AI CLI 会话的 PTY 进程生命周期与整树回收。

Windows 走 ConPTY（pywinpty），类 Unix 走标准 pty；两者都暴露
read()/write()/is_alive()/reap_tree()，使上层 manager 与平台无关。

零残留是关键设计：进程启动后立即登记 root PID，退出时用 psutil 递归收集
其全部子孙 PID 一并终止，带走 codex/claude 在工具调用中 spawn 的 node/子 shell。
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable

try:  # pragma: no cover - psutil 为运行期依赖
    import psutil
except ImportError:  # pragma: no cover
    psutil = None  # type: ignore[assignment]


class SessionStatus(str, Enum):
    """会话状态，用于 UI 徽标与事件分类。"""

    STARTING = "starting"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"

    @property
    def is_terminal(self) -> bool:
        return self in {SessionStatus.COMPLETED, SessionStatus.FAILED, SessionStatus.STOPPED}


# 信号回调类型：manager 把"状态变化/输出增量"推给 UI 层。
EventCallback = Callable[["PtySession", str], None]


@dataclass
class PtySession:
    """一个 PTY 会话的不可变标识 + 可变运行时状态。"""

    session_id: str
    title: str
    command: str
    cwd: str
    env: dict[str, str]
    status: SessionStatus = SessionStatus.STARTING
    exit_code: int | None = None
    started_at: str = ""
    finished_at: str = ""
    # 运行期由 backend 填充，单测可留空。
    root_pid: int = 0
    child_pids: set[int] = None  # type: ignore[assignment]
    awaiting_choice: bool = False
    choices: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.child_pids is None:
            self.child_pids = set()
        if self.choices is None:
            self.choices = []


class _Backend:
    """PTY 后端抽象：平台相关部分与 PtySession 解耦（便于单测替换）。"""

    def read(self) -> bytes:  # pragma: no cover - 具体后端实现
        raise NotImplementedError

    def write(self, data: str) -> None:  # pragma: no cover
        raise NotImplementedError

    def is_alive(self) -> bool:  # pragma: no cover
        raise NotImplementedError

    def pid(self) -> int:  # pragma: no cover
        raise NotImplementedError

    def kill(self) -> None:  # pragma: no cover
        raise NotImplementedError


class _WinPtyBackend(_Backend):
    """Windows ConPTY 后端（pywinpty）。"""

    def __init__(self, command: str, cwd: str, env: dict[str, str]) -> None:
        from pywinpty import PTYProcess  # 延迟导入：非 Windows 不需要

        cols, rows = 120, 30
        self._proc = PTYProcess.spawn(
            command,
            cwd=cwd or None,
            env=env or None,
            dimensions=(cols, rows),
        )

    def read(self) -> bytes:
        try:
            return self._proc.read()
        except EOFError:
            return b""
        except OSError:
            return b""

    def write(self, data: str) -> None:
        self._proc.write(data)

    def is_alive(self) -> bool:
        return self._proc.isalive()

    def pid(self) -> int:
        return int(self._proc.pid)

    def kill(self) -> None:
        try:
            self._proc.terminate(force=True)
        except Exception:  # noqa: BLE001 - 关闭时尽力而为
            pass


class _UnixPtyBackend(_Backend):
    """类 Unix 标准 pty 后端（仅打包 Linux/macOS 时需要）。"""

    def __init__(self, command: str, cwd: str, env: dict[str, str]) -> None:
        import pty
        import select
        import shlex

        master, slave = pty.openpty()
        self._master = master
        self._slave = slave
        self._select = select
        args = shlex.split(command)
        self._pid = os.fork()
        if self._pid == 0:  # pragma: no cover - 子进程
            os.setsid()
            os.dup2(slave, 0)
            os.dup2(slave, 1)
            os.dup2(slave, 2)
            os.close(master)
            os.close(slave)
            os.execvpe(args[0], args, env or os.environ)
        os.close(slave)

    def read(self) -> bytes:
        try:
            r, _, _ = self._select.select([self._master], [], [], 0)
            if r:
                return os.read(self._master, 65536)
        except OSError:
            return b""
        return b""

    def write(self, data: str) -> None:
        try:
            os.write(self._master, data.encode("utf-8", errors="replace"))
        except OSError:
            pass

    def is_alive(self) -> bool:
        try:
            pid, _ = os.waitpid(self._pid, os.WNOHANG)
            return pid == 0
        except ChildProcessError:
            return False

    def pid(self) -> int:
        return self._pid

    def kill(self) -> None:
        try:
            os.killpg(os.getpgid(self._pid), 15)
        except OSError:
            pass


def _build_backend(command: str, cwd: str, env: dict[str, str]) -> _Backend:
    if os.name == "nt":
        return _WinPtyBackend(command, cwd, env)
    return _UnixPtyBackend(command, cwd, env)


_TERMINATE_WAIT_S = 3.0


def collect_child_pids(root_pid: int) -> set[int]:
    """返回 root_pid 进程树（含自身外的全部子孙）。psutil 缺失时退化为空集。"""
    if psutil is None or root_pid <= 0:
        return set()
    pids: set[int] = set()
    try:
        root = psutil.Process(root_pid)
    except psutil.Error:  # type: ignore[attr-defined]
        return pids
    for child in root.children(recursive=True):
        pids.add(child.pid)
    return pids


def reap_tree(session: PtySession) -> None:
    """整树回收：终止 root 及其全部子孙进程，带走 AI CLI 遗留的子进程。"""
    if psutil is None:
        return
    pids = set(session.child_pids)
    if session.root_pid > 0:
        pids.add(session.root_pid)
    for pid in pids:
        try:
            proc = psutil.Process(pid)
        except psutil.Error:  # type: ignore[attr-defined]
            continue
        try:
            proc.terminate()
        except psutil.Error:  # type: ignore[attr-defined]
            continue
    # 给被终止进程一个优雅退出的窗口，再强制收割仍未死的。
    deadline = time.monotonic() + _TERMINATE_WAIT_S
    while pids and time.monotonic() < deadline:
        for pid in list(pids):
            try:
                if not psutil.Process(pid).is_running():
                    pids.discard(pid)
            except psutil.Error:  # type: ignore[attr-defined]
                pids.discard(pid)
        if pids:
            time.sleep(0.1)
    for pid in pids:
        try:
            psutil.Process(pid).kill()
        except psutil.Error:  # type: ignore[attr-defined]
            pass


def start_session(
    session: PtySession,
    *,
    backend_factory: Callable[[str, str, dict[str, str]], _Backend] | None = None,
) -> _Backend:
    """启动会话的 PTY 后端并登记进程树。backend_factory 用于单测注入假后端。"""
    factory = backend_factory or _build_backend
    backend = factory(session.command, session.cwd, session.env)
    session.root_pid = backend.pid()
    session.child_pids = collect_child_pids(session.root_pid)
    session.status = SessionStatus.RUNNING
    return backend


def mark_finished(session: PtySession, exit_code: int | None) -> SessionStatus:
    """根据退出码推导终态：0=完成，非0=失败；再由调用方决定是否需要回收。"""
    session.exit_code = exit_code
    if exit_code is None:
        session.status = SessionStatus.STOPPED
    elif exit_code == 0:
        session.status = SessionStatus.COMPLETED
    else:
        session.status = SessionStatus.FAILED
    session.finished_at = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
    return session.status


__all__ = [
    "PtySession",
    "SessionStatus",
    "_Backend",
    "collect_child_pids",
    "reap_tree",
    "start_session",
    "mark_finished",
]
