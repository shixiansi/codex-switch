from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
import tkinter as tk
from tkinter import messagebox


_SINGLE_INSTANCE_HANDLE = None


def _has_visible_codex_window() -> bool:
    if os.name != "nt":
        return False
    try:
        user32 = ctypes.windll.user32
        user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
        user32.FindWindowW.restype = wintypes.HWND
        user32.IsWindowVisible.argtypes = [wintypes.HWND]
        user32.IsWindowVisible.restype = wintypes.BOOL
        is_hung = getattr(user32, "IsHungAppWindow", None)
        hwnd = user32.FindWindowW(None, "Codex Switch")
        if not hwnd:
            return False
        if not user32.IsWindowVisible(hwnd):
            return False
        if is_hung and is_hung(hwnd):
            return False
        return True
    except Exception:
        return False


def _activate_existing_codex_window() -> bool:
    if os.name != "nt":
        return False
    try:
        user32 = ctypes.windll.user32
        user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
        user32.FindWindowW.restype = wintypes.HWND
        user32.IsWindowVisible.argtypes = [wintypes.HWND]
        user32.IsWindowVisible.restype = wintypes.BOOL
        user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.ShowWindow.restype = wintypes.BOOL
        user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        user32.SetForegroundWindow.restype = wintypes.BOOL
        user32.BringWindowToTop.argtypes = [wintypes.HWND]
        user32.BringWindowToTop.restype = wintypes.BOOL
        is_hung = getattr(user32, "IsHungAppWindow", None)
        hwnd = user32.FindWindowW(None, "Codex Switch")
        if not hwnd:
            return False
        if not user32.IsWindowVisible(hwnd):
            return False
        if is_hung and is_hung(hwnd):
            return False

        SW_RESTORE = 9
        user32.ShowWindow(hwnd, SW_RESTORE)
        user32.SetForegroundWindow(hwnd)
        user32.BringWindowToTop(hwnd)
        return True
    except Exception:
        return False


def _acquire_single_instance() -> bool:
    global _SINGLE_INSTANCE_HANDLE
    if os.name != "nt":
        return True
    try:
        if _SINGLE_INSTANCE_HANDLE is not None:
            return True
        mutex_name = "Global\\CodexSwitchSingleInstance"
        handle = ctypes.windll.kernel32.CreateMutexW(None, False, mutex_name)
        if not handle:
            return True
        if ctypes.windll.kernel32.GetLastError() == 183:
            if _has_visible_codex_window():
                ctypes.windll.kernel32.CloseHandle(handle)
                return False
        _SINGLE_INSTANCE_HANDLE = handle
        return True
    except Exception:
        return True


def _release_single_instance() -> None:
    global _SINGLE_INSTANCE_HANDLE
    if os.name != "nt" or _SINGLE_INSTANCE_HANDLE is None:
        return
    try:
        ctypes.windll.kernel32.CloseHandle(_SINGLE_INSTANCE_HANDLE)
    finally:
        _SINGLE_INSTANCE_HANDLE = None


def _show_single_instance_message() -> None:
    root = tk.Tk()
    root.withdraw()
    try:
        messagebox.showinfo("Codex Switch", "Codex Switch 已经在运行。")
    finally:
        root.destroy()
