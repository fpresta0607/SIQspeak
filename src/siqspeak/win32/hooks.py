from __future__ import annotations

import ctypes
import ctypes.wintypes

from siqspeak.config import VK_CONTROL, VK_LWIN, VK_RWIN
from siqspeak.state import AppState

# ---------------------------------------------------------------------------
# Shared hook infrastructure
# ---------------------------------------------------------------------------

# LRESULT is pointer-sized (8 bytes on x64) — ctypes.c_long is always 4 bytes on Windows.
# Using c_long truncates the CallNextHookEx return and blocks all events.
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

# Module-level state reference so callbacks can access AppState
_state_ref: AppState | None = None

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


# ---------------------------------------------------------------------------
# Low-level keyboard hook for Ctrl+Win hotkey
# ---------------------------------------------------------------------------
# RegisterHotKey cannot reliably use VK_LWIN as the trigger key on Windows 11
# because the shell intercepts Win key presses. A WH_KEYBOARD_LL hook runs
# before the shell, so we can detect Ctrl+Win and suppress the Start Menu.
# ---------------------------------------------------------------------------

WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105


class _KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", ctypes.wintypes.DWORD),
        ("scanCode", ctypes.wintypes.DWORD),
        ("flags", ctypes.wintypes.DWORD),
        ("time", ctypes.wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


# Track whether Win was consumed by our hotkey so we suppress the key-up too.
# win_held is True while Win is physically held during a Ctrl+Win press —
# _wait_for_release polls this instead of GetAsyncKeyState (which can't see
# suppressed keys).
_win_suppressed: bool = False
win_held: bool = False


def _keyboard_hook_proc(nCode, wParam, lParam):
    global _win_suppressed, win_held
    try:
        if nCode >= 0 and _state_ref is not None:
            data = ctypes.cast(lParam, ctypes.POINTER(_KBDLLHOOKSTRUCT)).contents
            vk = data.vkCode
            is_win = vk in (VK_LWIN, VK_RWIN)

            if is_win and wParam in (WM_KEYDOWN, WM_SYSKEYDOWN):
                # Check if Ctrl is currently held
                user32 = ctypes.windll.user32
                ctrl_down = user32.GetAsyncKeyState(VK_CONTROL) & 0x8000
                if ctrl_down:
                    _win_suppressed = True
                    win_held = True
                    # Fire hotkey on main thread via PostMessage (WM_APP+1)
                    user32.PostMessageW(None, 0x8001, 0, 0)
                    return 1  # Suppress — prevents Start Menu

            if is_win and wParam in (WM_KEYUP, WM_SYSKEYUP) and _win_suppressed:
                _win_suppressed = False
                win_held = False
                return 1  # Suppress release too — prevents Start Menu flash
    except Exception:
        pass
    return _CallNextHookEx(None, nCode, wParam, lParam)


# Must prevent GC of the callback
_keyboard_hook_callback = _HOOKPROC(_keyboard_hook_proc)


def install_keyboard_hook(state: AppState) -> None:
    global _state_ref
    _state_ref = state
    state.keyboard_hook = ctypes.windll.user32.SetWindowsHookExW(
        WH_KEYBOARD_LL, _keyboard_hook_callback, None, 0
    )


def uninstall_keyboard_hook(state: AppState) -> None:
    if state.keyboard_hook:
        ctypes.windll.user32.UnhookWindowsHookEx(state.keyboard_hook)
        state.keyboard_hook = None
