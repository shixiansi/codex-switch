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
from pathlib import Path
from typing import Any, Callable

try:  # pragma: no cover - psutil 为运行期依赖
    import psutil
except ImportError:  # pragma: no cover
    psutil = None  # type: ignore[assignment]

from .logging_setup import get_logger


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
    # 是否已收到过任何输出：用于区分"CLI 没输出"与"读取环节坏了"。
    received_output: bool = False

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
    """Windows ConPTY 后端（pywinpty）。

    pywinpty 3.x 的导入模块名是 ``winpty``（不是 ``pywinpty``），对外暴露
    ``PtyProcess``。spawn 接受命令行字符串，dimensions 为 ``(rows, cols)``。
    """

    def __init__(self, command: str, cwd: str, env: dict[str, str]) -> None:
        try:
            from winpty import PtyProcess  # pywinpty >= 3
        except ImportError:  # pragma: no cover - pywinpty 2.x 旧模块名
            from pywinpty import PtyProcess  # type: ignore[no-redef]

        cols, rows = 120, 30
        self._proc = PtyProcess.spawn(
            command,
            cwd=cwd or None,
            env=env or None,
            dimensions=(rows, cols),
        )
        # pywinpty 的 read() 内部是阻塞 recv()：CLI 空闲时会把轮询线程永久挂住，
        # 导致输出既读不到、退出也检测不到（界面表现得"什么都没有"）。
        # 这里把底层 socket 改成非阻塞，改由 select() 判断可读性。
        self._sock = getattr(self._proc, "fileobj", None)
        if self._sock is not None:
            try:
                self._sock.setblocking(False)
            except OSError:
                self._sock = None
        if self._sock is None:
            # 不能静默降级：读不到输出会表现为"界面一片空白"，必须有迹可循。
            get_logger().warning(
                "PTY 后端未提供可用的非阻塞句柄，输出可能无法读取（pywinpty 版本不兼容？）"
            )

    def read(self) -> bytes:
        """非阻塞读取原始字节；没有数据时立即返回空字节。

        直接读底层 socket 而不是 ``pywinpty.read()``：后者的实现是"按 UTF-8 解码，
        失败就再 recv(1) 补齐"，在非阻塞 socket 上补不到字节会抛 BlockingIOError，
        导致跨读取边界拆开的多字节字符（中文）整块丢失。这里只负责搬运字节，
        解码交给上层的增量解码器处理。
        """
        if self._sock is None:
            return b""
        try:
            import select as _select

            ready, _, _ = _select.select([self._sock], [], [], 0)
            if not ready:
                return b""
            data = self._sock.recv(65536)
        except (OSError, ValueError):
            return b""
        if not data:
            # 对端关闭
            self._proc.flag_eof = True
            return b""
        # pywinpty 用于探测存活状态的哨兵值，不应显示。
        if data == b"0011Ignore":
            return b""
        return bytes(data)

    def write(self, data: str) -> None:
        self._proc.write(data)

    def is_alive(self) -> bool:
        return bool(self._proc.isalive())

    def pid(self) -> int:
        return int(getattr(self._proc, "pid", 0) or 0)

    def kill(self) -> None:
        try:
            self._proc.terminate(force=True)
        except Exception:  # noqa: BLE001 - 关闭时尽力而为
            pass
        # pywinpty 内部持有一个 socket 对；不显式关闭会泄漏句柄（ResourceWarning）。
        fileobj = getattr(self._proc, "fileobj", None)
        if fileobj is not None:
            try:
                fileobj.close()
            except Exception:  # noqa: BLE001
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


def reap_tree(session: PtySession) -> int:
    """整树回收：终止 root 及其全部子孙进程，带走 AI CLI 遗留的子进程。

    返回本次终止的进程数量，供日志与界面反馈使用。
    """
    if psutil is None:
        return 0
    pids = set(session.child_pids)
    if session.root_pid > 0:
        pids.add(session.root_pid)
    total = len(pids)
    if not pids:
        return 0
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
    return total


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


def check_pty_backend() -> str:
    """检查 PTY 运行环境是否可用，返回空字符串表示正常。

    冻结包最容易缺的就是 winpty 的原生文件（winpty.dll / winpty-agent.exe /
    OpenConsole.exe）。缺失时直接给出可读原因，而不是让用户在空白界面里猜。
    """
    if os.name != "nt":
        return ""
    try:
        import winpty  # noqa: F401
    except ImportError:
        try:
            import pywinpty  # noqa: F401
        except ImportError:
            return "未安装 pywinpty，无法创建伪终端。请执行 pip install -r requirements.txt。"

    try:
        import winpty as _winpty

        pkg_dir = Path(_winpty.__file__).parent
    except ImportError:  # pragma: no cover - pywinpty 2.x
        return ""

    missing = [
        name
        for name in ("winpty.dll", "winpty-agent.exe")
        if not (pkg_dir / name).exists()
    ]
    if missing:
        return (
            "PTY 运行库不完整，缺少："
            + "、".join(missing)
            + "。若是打包版本，请重新构建以包含 pywinpty 的原生文件。"
        )
    return ""


__all__ = [
    "PtySession",
    "SessionStatus",
    "_Backend",
    "check_pty_backend",
    "collect_child_pids",
    "reap_tree",
    "start_session",
    "mark_finished",
]
