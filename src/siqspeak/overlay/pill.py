from __future__ import annotations

import ctypes
import ctypes.wintypes

from siqspeak.config import ACTIVE_H, ACTIVE_W, IDLE_H, IDLE_W
from siqspeak.state import AppState


def _pill_screen_rect(state: AppState) -> tuple[int, int, int, int]:
    """Return (x, y, w, h) of the pill window on screen."""
    user32 = ctypes.windll.user32
    rect = ctypes.wintypes.RECT()
    user32.GetWindowRect(state.overlay_hwnd, ctypes.byref(rect))
    return rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top


def _set_pill_mode(state: AppState, mode: str) -> None:
    """Switch pill between idle (toolbar) and active (dots) mode."""
    if state.pill_current_mode == mode or not state.overlay_hwnd:
        return
    state.pill_current_mode = mode
    user32 = ctypes.windll.user32
    sw = user32.GetSystemMetrics(0)
    sh = user32.GetSystemMetrics(1)

    if mode == "idle":
        w, h = IDLE_W, IDLE_H
        # Remove WS_EX_TRANSPARENT (hoverable)
        style = user32.GetWindowLongW(state.overlay_hwnd, -20)  # GWL_EXSTYLE
        user32.SetWindowLongW(state.overlay_hwnd, -20, style & ~0x00000020)
    else:
        w, h = ACTIVE_W, ACTIVE_H
        # Add WS_EX_TRANSPARENT (click-through during recording/transcribing)
        style = user32.GetWindowLongW(state.overlay_hwnd, -20)
        user32.SetWindowLongW(state.overlay_hwnd, -20, style | 0x00000020)

    if state.pill_user_x is not None:
        x = state.pill_user_x
        y = state.pill_user_y
    else:
        x = (sw - w) // 2
        y = sh - h - 80
    # HWND_TOPMOST (-1) + SWP_NOACTIVATE | SWP_FRAMECHANGED
    # SWP_FRAMECHANGED (0x0020) is required to flush SetWindowLong style changes
    # (e.g. WS_EX_TRANSPARENT add/remove) — without it clicks can stay locked.
    HWND_TOPMOST = ctypes.wintypes.HWND(-1)
    user32.SetWindowPos(state.overlay_hwnd, HWND_TOPMOST, x, y, w, h, 0x0010 | 0x0020)
