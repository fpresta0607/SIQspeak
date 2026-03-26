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

    # Flush style change — SetWindowLongW alone doesn't recompute the frame
    HWND_TOPMOST = ctypes.wintypes.HWND(-1)
    user32.SetWindowPos(
        state.overlay_hwnd, HWND_TOPMOST, 0, 0, 0, 0,
        0x0002 | 0x0001 | 0x0010 | 0x0020,  # SWP_NOMOVE|SWP_NOSIZE|SWP_NOACTIVATE|SWP_FRAMECHANGED
    )


def _ensure_clickable(state: AppState) -> None:
    """Watchdog: if pill is in idle mode but WS_EX_TRANSPARENT is still set, clear it.

    Called on the topmost tick. Fixes the 'pill freezes / clicks pass through'
    bug where a racing state transition leaves the transparent flag stuck on.
    """
    if not state.overlay_hwnd or state.pill_current_mode != "idle":
        return
    user32 = ctypes.windll.user32
    style = user32.GetWindowLongW(state.overlay_hwnd, -20)  # GWL_EXSTYLE
    WS_EX_TRANSPARENT = 0x00000020
    if style & WS_EX_TRANSPARENT:
        # Stuck — clear it and force a style flush via SWP_FRAMECHANGED
        user32.SetWindowLongW(state.overlay_hwnd, -20, style & ~WS_EX_TRANSPARENT)
        HWND_TOPMOST = ctypes.wintypes.HWND(-1)
        # SWP_NOMOVE|SWP_NOSIZE|SWP_NOACTIVATE|SWP_FRAMECHANGED
        user32.SetWindowPos(state.overlay_hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                            0x0002 | 0x0001 | 0x0010 | 0x0020)
