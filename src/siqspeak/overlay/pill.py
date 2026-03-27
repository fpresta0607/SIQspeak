from __future__ import annotations

import ctypes
import ctypes.wintypes
import logging

from siqspeak.config import ACTIVE_H, ACTIVE_W, IDLE_H, IDLE_W
from siqspeak.state import AppState

log = logging.getLogger("siqspeak")

# ShowWindow constants
_SW_HIDE = 0
_SW_SHOWNA = 8  # show without activating


def _pill_screen_rect(state: AppState) -> tuple[int, int, int, int]:
    """Return (x, y, w, h) of the pill window on screen."""
    user32 = ctypes.windll.user32
    rect = ctypes.wintypes.RECT()
    user32.GetWindowRect(state.overlay_hwnd, ctypes.byref(rect))
    return rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top


def _set_pill_mode(state: AppState, mode: str) -> None:
    """Switch pill between idle (clickable) and active (click-through) by swapping windows.

    Two pre-created overlay windows have immutable extended styles:
    - idle_overlay_hwnd:   NO WS_EX_TRANSPARENT (always clickable)
    - active_overlay_hwnd: WITH WS_EX_TRANSPARENT (always click-through)

    Mode switch = position incoming window at outgoing window's location,
    show incoming, hide outgoing, update state.overlay_hwnd alias.
    """
    if state.pill_current_mode == mode:
        return
    if not state.idle_overlay_hwnd or not state.active_overlay_hwnd:
        return

    user32 = ctypes.windll.user32
    old_mode = state.pill_current_mode
    state.pill_current_mode = mode

    if mode == "idle":
        outgoing = state.active_overlay_hwnd
        incoming = state.idle_overlay_hwnd
        in_w, in_h = IDLE_W, IDLE_H
    else:
        outgoing = state.idle_overlay_hwnd
        incoming = state.active_overlay_hwnd
        in_w, in_h = ACTIVE_W, ACTIVE_H

    # Read position from the outgoing (visible) window
    rect = ctypes.wintypes.RECT()
    user32.GetWindowRect(outgoing, ctypes.byref(rect))
    out_cx = (rect.left + rect.right) // 2
    out_cy = (rect.top + rect.bottom) // 2

    # Center the incoming window on the same midpoint
    in_x = out_cx - in_w // 2
    in_y = out_cy - in_h // 2

    HWND_TOPMOST = ctypes.wintypes.HWND(-1)
    SWP_NOACTIVATE = 0x0010

    # Position incoming window (still hidden)
    user32.SetWindowPos(
        incoming, HWND_TOPMOST, in_x, in_y, in_w, in_h, SWP_NOACTIVATE,
    )

    # Show incoming THEN hide outgoing to avoid flicker gap
    user32.ShowWindow(incoming, _SW_SHOWNA)
    user32.ShowWindow(outgoing, _SW_HIDE)

    state.overlay_hwnd = incoming
    log.info("PILL MODE %s -> %s (hwnd=%d)", old_mode, mode, incoming)
