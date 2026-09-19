"""进程与日志的通用工具（不依赖 Qt，也不依赖任何业务模块）。

``ui_v2/script_runner.py`` 与 DSH 多开插件需要同一批能力：

* 判断某个 pid 是否还活着（重启后接管既有进程）；
* 按进程树强杀（Windows 上 ``taskkill /T``，否则 ``SIGTERM``）；
* 让子进程不弹出控制台窗口；
* 把控制台原始字节按本机代码页解码。

这些逻辑原先都写在 ``ui_v2/script_runner.py`` 里。但插件是普通 Python 模块，
**不能**通过 ``codex_switch.ui_v2`` 导入它们——那个包的 ``__init__`` 会立刻
拉起 Qt，而插件核心逻辑必须在没有 Qt 的测试环境里也能导入。

所以这里抽成独立模块，两边共用同一份实现（DRY），同时保持可单测。
``script_runner`` 仍然把 :func:`decode_output` / :func:`kill_pid` /
:func:`pid_alive` 重新导出，历史调用方与测试无需改动。
"""

from __future__ import annotations

import ctypes
import os
from pathlib import Path
import signal
import subprocess
from typing import Any


# Console programs on a Chinese Windows write the OEM code page (GBK/cp936),
# not UTF-8. Logs keep the raw bytes, so decoding has to detect which one a run
# actually produced; guessing UTF-8 unconditionally mangled every Chinese line
# into U+FFFD.
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


def read_log_text(path: str | Path, *, max_bytes: int = 0, tail_lines: int = 0) -> str:
    """Read a log file as text, tolerating any console code page.

    Args:
        path: log file to read.
        max_bytes: when positive, read at most this many bytes **from the end**,
            so a huge log cannot be pulled into memory just to show its tail.
        tail_lines: when positive, keep only the last N lines.

    Returns:
        The decoded text, or ``""`` when the file is missing or unreadable.
        A missing log is an ordinary state (nothing has run yet), not an error.
    """
    target = Path(path)
    try:
        if max_bytes > 0:
            size = target.stat().st_size
            with open(target, "rb") as handle:
                if size > max_bytes:
                    handle.seek(size - max_bytes)
                data = handle.read()
        else:
            data = target.read_bytes()
    except OSError:
        return ""

    text = decode_output(data)
    if tail_lines > 0:
        lines = text.splitlines()
        if len(lines) > tail_lines:
            text = "\n".join(lines[-tail_lines:])
    return text


def hidden_process_kwargs() -> dict[str, Any]:
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


def pid_alive(pid: int) -> bool:
    """Whether a process with ``pid`` currently exists.

    Used to re-adopt background runs after an app restart, so it must not
    create or signal anything. A reused pid could falsely read as alive, but
    for a desktop tool the window for that race is negligible.
    """
    if pid <= 0:
        return False
    if os.name == "nt":
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        kernel32 = ctypes.windll.kernel32
        kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            exit_code = ctypes.c_uint32()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return False
            return exit_code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Exists but belongs to someone else: alive is the safer answer.
        return True
    return True


def kill_pid(pid: int) -> bool:
    """Forcefully kill a process we hold no Popen handle for.

    On Windows ``/T`` is essential: the DSH launcher is ``node`` and it is the
    parent of the real server work, so killing only the recorded pid would
    leave a stray listener holding the port.
    """
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            completed = subprocess.run(  # noqa: S603 - fixed argv
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            return False
        return completed.returncode == 0
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return False
    return True


__all__ = [
    "decode_output",
    "hidden_process_kwargs",
    "kill_pid",
    "pid_alive",
    "read_log_text",
]
