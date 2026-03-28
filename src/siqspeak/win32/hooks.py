from __future__ import annotations

import ctypes
import ctypes.wintypes

from siqspeak.config import VK_CONTROL, VK_SHIFT, VK_SPACE
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
# Low-level keyboard hook for Ctrl+Shift+Space hotkey
# ---------------------------------------------------------------------------
# A WH_KEYBOARD_LL hook lets us detect the three-key combo and suppress the
# Space key so it doesn't type a literal space into the active window.
# ---------------------------------------------------------------------------

WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
LLKHF_INJECTED = 0x10


class _KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", ctypes.wintypes.DWORD),
        ("scanCode", ctypes.wintypes.DWORD),
        ("flags", ctypes.wintypes.DWORD),
        ("time", ctypes.wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


# Track whether Space was consumed by our hotkey so we suppress the key-up too.
# space_held is True while Space is physically held during a Ctrl+Shift+Space
# press — _wait_for_release polls this instead of GetAsyncKeyState (which can't
# see suppressed keys).
_space_suppressed: bool = False
space_held: bool = False


def reset_keyboard_hook_state() -> None:
    """Reset hook tracking flags — call when reinstalling the keyboard hook."""
    global _space_suppressed, space_held
    _space_suppressed = False
    space_held = False


def _keyboard_hook_proc(nCode, wParam, lParam):
    global _space_suppressed, space_held
    try:
        if nCode >= 0 and _state_ref is not None:
            data = ctypes.cast(lParam, ctypes.POINTER(_KBDLLHOOKSTRUCT)).contents
            vk = data.vkCode

            # Ignore injected events (e.g. SendInput from type_text) so typed
            # Space characters don't re-trigger recording.
            if data.flags & LLKHF_INJECTED:
                return _CallNextHookEx(None, nCode, wParam, lParam)

            if vk == VK_SPACE and wParam == WM_KEYDOWN:
                if _space_suppressed:
                    return 1  # Already in Ctrl+Shift+Space cycle — suppress repeats
                user32 = ctypes.windll.user32
                ctrl_down = user32.GetAsyncKeyState(VK_CONTROL) & 0x8000
                shift_down = user32.GetAsyncKeyState(VK_SHIFT) & 0x8000
                if ctrl_down and shift_down:
                    _space_suppressed = True
                    space_held = True
                    user32.PostMessageW(None, 0x8001, 0, 0)
                    return 1  # Suppress Space so it doesn't type into the window

            if vk == VK_SPACE and wParam == WM_KEYUP and _space_suppressed:
                _space_suppressed = False
                space_held = False
                return 1  # Suppress release too
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
