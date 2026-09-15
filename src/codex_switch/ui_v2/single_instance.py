"""Single-instance guard for the desktop app.

Two instances would race on ``profiles.json`` and on the route-proxy port, so
the app holds a named mutex for its lifetime. Window re-activation is
best-effort and only attempted on Windows.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import os


_SINGLE_INSTANCE_HANDLE = None
MUTEX_NAME = "Global\\CodexSwitchSingleInstance"
_ERROR_ALREADY_EXISTS = 183

# Shown in the QML window title; matched by prefix when locating the window.
WINDOW_TITLE_PREFIX = "Codex Switch"


def _user32():
    user32 = ctypes.windll.user32
    user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    user32.FindWindowW.restype = wintypes.HWND
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    return user32


def _find_app_window():
    """Return the handle of a visible Codex Switch window, if any.

    The window title includes the version, so an exact match is not possible;
    ``EnumWindows`` with a prefix test is used instead.
    """
    try:
        user32 = _user32()
        user32.EnumWindows.argtypes = [ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM), wintypes.LPARAM]
        user32.EnumWindows.restype = wintypes.BOOL
        user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]

        found: list[int] = []

        def callback(hwnd, _param):
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buffer, length + 1)
            if buffer.value.startswith(WINDOW_TITLE_PREFIX):
                found.append(hwnd)
                return False
            return True

        user32.EnumWindows(ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)(callback), 0)
        return found[0] if found else None
    except Exception:  # noqa: BLE001 - activation is best-effort
        return None


def has_visible_window() -> bool:
    if os.name != "nt":
        return False
    return _find_app_window() is not None


def activate_existing_window() -> bool:
    """Bring an already-running instance to the foreground."""
    if os.name != "nt":
        return False
    hwnd = _find_app_window()
    if not hwnd:
        return False
    try:
        user32 = _user32()
        user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        user32.BringWindowToTop.argtypes = [wintypes.HWND]
        user32.ShowWindow(hwnd, 9)
        user32.SetForegroundWindow(hwnd)
        user32.BringWindowToTop(hwnd)
        return True
    except Exception:  # noqa: BLE001 - activation is best-effort
        return False


def acquire_single_instance() -> bool:
    """Return True when this process may run, False when another already is."""
    global _SINGLE_INSTANCE_HANDLE
    if os.name != "nt":
        return True
    if _SINGLE_INSTANCE_HANDLE is not None:
        return True
    try:
        handle = ctypes.windll.kernel32.CreateMutexW(None, False, MUTEX_NAME)
        if not handle:
            # Cannot create the mutex: prefer starting over blocking the user.
            return True
        if ctypes.windll.kernel32.GetLastError() == _ERROR_ALREADY_EXISTS:
            # Another instance owns the mutex; surface its window if we can.
            if activate_existing_window():
                return False
            if has_visible_window():
                return False
            # A stale mutex with no window: take ownership and continue.
        _SINGLE_INSTANCE_HANDLE = handle
        return True
    except Exception:  # noqa: BLE001 - never block startup on this
        return True


def release_single_instance() -> None:
    global _SINGLE_INSTANCE_HANDLE
    if os.name != "nt" or _SINGLE_INSTANCE_HANDLE is None:
        return
    try:
        ctypes.windll.kernel32.ReleaseMutex(_SINGLE_INSTANCE_HANDLE)
        ctypes.windll.kernel32.CloseHandle(_SINGLE_INSTANCE_HANDLE)
    except Exception:  # noqa: BLE001
        pass
    _SINGLE_INSTANCE_HANDLE = None


__all__ = [
    "WINDOW_TITLE_PREFIX",
    "acquire_single_instance",
    "activate_existing_window",
    "has_visible_window",
    "release_single_instance",
]
