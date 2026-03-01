from __future__ import annotations

import ctypes
import ctypes.wintypes

from siqspeak.state import AppState

# ---------------------------------------------------------------------------
# Low-level mouse hook for wheel scroll support
# ---------------------------------------------------------------------------


class _MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", ctypes.wintypes.POINT),
        ("mouseData", ctypes.wintypes.DWORD),
        ("flags", ctypes.wintypes.DWORD),
        ("time", ctypes.wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


# LRESULT is pointer-sized (8 bytes on x64) — ctypes.c_long is always 4 bytes on Windows.
# Using c_long truncates the CallNextHookEx return and blocks all mouse events.
_HOOKPROC = ctypes.WINFUNCTYPE(
    ctypes.wintypes.LPARAM, ctypes.c_int, ctypes.wintypes.WPARAM, ctypes.wintypes.LPARAM
)

# ctypes defaults foreign function returns to c_int (32-bit) — must declare explicitly.
_CallNextHookEx = ctypes.windll.user32.CallNextHookEx
_CallNextHookEx.restype = ctypes.wintypes.LPARAM
_CallNextHookEx.argtypes = [
    ctypes.wintypes.HHOOK, ctypes.c_int,
    ctypes.wintypes.WPARAM, ctypes.wintypes.LPARAM,
]

# Module-level state reference so the callback can access AppState
_state_ref: AppState | None = None


def _mouse_hook_proc(nCode, wParam, lParam):
    try:
        if nCode >= 0 and wParam == 0x020A and _state_ref is not None:  # WM_MOUSEWHEEL
            data = ctypes.cast(lParam, ctypes.POINTER(_MSLLHOOKSTRUCT)).contents
            delta = ctypes.c_short((data.mouseData >> 16) & 0xFFFF).value
            _state_ref.wheel_delta += delta
    except Exception:
        pass
    # None for hook handle — modern Windows ignores it, avoids startup race condition
    return _CallNextHookEx(None, nCode, wParam, lParam)


# Must prevent GC of the callback
_mouse_hook_callback = _HOOKPROC(_mouse_hook_proc)


def install_mouse_hook(state: AppState) -> None:
    global _state_ref
    _state_ref = state
    state.mouse_hook = ctypes.windll.user32.SetWindowsHookExW(
        14, _mouse_hook_callback, None, 0
    )


def uninstall_mouse_hook(state: AppState) -> None:
    if state.mouse_hook:
        ctypes.windll.user32.UnhookWindowsHookEx(state.mouse_hook)
        state.mouse_hook = None
