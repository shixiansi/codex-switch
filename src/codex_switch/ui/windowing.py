from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
import tkinter as tk


_DRAG_REDRAW_GUARD_ATTR = "_codex_switch_drag_redraw_guard"

_WM_ENTERSIZEMOVE = 0x0231
_WM_EXITSIZEMOVE = 0x0232
_WM_NCDESTROY = 0x0082
_WM_SETREDRAW = 0x000B

_RDW_INVALIDATE = 0x0001
_RDW_ALLCHILDREN = 0x0080
_REDRAW_FLAGS = _RDW_INVALIDATE | _RDW_ALLCHILDREN


def install_windows_drag_redraw_guard(window: tk.Misc) -> bool:
    if os.name != "nt":
        return False
    if getattr(window, _DRAG_REDRAW_GUARD_ATTR, None):
        return True

    try:
        hwnd = int(window.winfo_id())
    except Exception:
        return False
    if not hwnd:
        return False

    try:
        user32 = ctypes.windll.user32
        comctl32 = ctypes.windll.comctl32

        lresult = ctypes.c_ssize_t
        uint_ptr = ctypes.c_size_t
        dword_ptr = ctypes.c_size_t
        subclass_proc = ctypes.WINFUNCTYPE(
            lresult,
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
            uint_ptr,
            dword_ptr,
        )

        set_window_subclass = comctl32.SetWindowSubclass
        set_window_subclass.argtypes = [wintypes.HWND, subclass_proc, uint_ptr, dword_ptr]
        set_window_subclass.restype = wintypes.BOOL
        remove_window_subclass = comctl32.RemoveWindowSubclass
        remove_window_subclass.argtypes = [wintypes.HWND, subclass_proc, uint_ptr]
        remove_window_subclass.restype = wintypes.BOOL
        def_subclass_proc = comctl32.DefSubclassProc
        def_subclass_proc.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        def_subclass_proc.restype = lresult

        send_message = user32.SendMessageW
        send_message.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        send_message.restype = lresult
        redraw_window = user32.RedrawWindow
        redraw_window.argtypes = [wintypes.HWND, ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]
        redraw_window.restype = wintypes.BOOL

        state = {"redraw_suspended": False, "removed": False, "refresh_pending": False}
        subclass_id = uint_ptr(id(window))

        def queue_refresh(target_hwnd: int) -> None:
            state["refresh_pending"] = False
            redraw_window(target_hwnd, None, None, _REDRAW_FLAGS)

        def resume_redraw(target_hwnd: int, *, refresh: bool = True) -> None:
            if not state["redraw_suspended"]:
                return
            state["redraw_suspended"] = False
            send_message(target_hwnd, _WM_SETREDRAW, 1, 0)
            if not refresh or state["refresh_pending"]:
                return
            state["refresh_pending"] = True
            try:
                # Avoid blocking the system move loop with a synchronous full repaint.
                window.after_idle(lambda hwnd=target_hwnd: queue_refresh(hwnd))
            except Exception:
                queue_refresh(target_hwnd)

        def remove_subclass() -> None:
            if state["removed"]:
                return
            state["removed"] = True
            remove_window_subclass(hwnd, callback, subclass_id)

        def handle_destroy(_event: tk.Event) -> None:
            resume_redraw(hwnd, refresh=False)
            remove_subclass()

        def window_proc(
            target_hwnd: wintypes.HWND,
            message: int,
            wparam: wintypes.WPARAM,
            lparam: wintypes.LPARAM,
            _subclass_id: int,
            _ref_data: int,
        ) -> int:
            if message == _WM_ENTERSIZEMOVE and not state["redraw_suspended"]:
                state["redraw_suspended"] = True
                send_message(target_hwnd, _WM_SETREDRAW, 0, 0)
            elif message == _WM_EXITSIZEMOVE:
                resume_redraw(target_hwnd)
            elif message == _WM_NCDESTROY:
                resume_redraw(target_hwnd, refresh=False)
                remove_subclass()
            return def_subclass_proc(target_hwnd, message, wparam, lparam)

        callback = subclass_proc(window_proc)
        if not set_window_subclass(hwnd, callback, subclass_id, 0):
            return False

        setattr(
            window,
            _DRAG_REDRAW_GUARD_ATTR,
            {
                "callback": callback,
                "subclass_id": subclass_id,
                "state": state,
                "remove": remove_subclass,
            },
        )
        window.bind("<Destroy>", handle_destroy, add="+")
        return True
    except Exception:
        return False
