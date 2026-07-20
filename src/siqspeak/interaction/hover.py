from __future__ import annotations

import ctypes
import ctypes.wintypes
import logging
import time
from collections.abc import Sequence

import pyperclip

from siqspeak.config import (
    LOG_CARD_MARGIN_X,
    LOG_COPY_BTN_W,
    LOG_HEADER_H,
    LOG_PANEL_MAX_VISIBLE,
    LOG_PANEL_PADDING,
    _log_panel_dims,
)
from siqspeak.overlay.panels.log_panel import _visible_entries
from siqspeak.state import AppState

log = logging.getLogger("siqspeak")


def _is_cursor_over_hwnd(hwnd: int) -> bool:
    """Check if the mouse cursor is over a window."""
    if not hwnd:
        return False
    user32 = ctypes.windll.user32
    pt = ctypes.wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    rect = ctypes.wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return rect.left <= pt.x <= rect.right and rect.top <= pt.y <= rect.bottom


def _copy_row_at_position(
    x: int,
    y: int,
    panel_width: int,
    entry_heights: Sequence[int],
) -> int | None:
    """Map a panel-relative point to a history row index, or None.

    Pure geometry: no Win32 calls. Matches the copy-column and row strides used
    by the renderer so a click on a card's copy control resolves to that row.
    """
    copy_right = panel_width - LOG_CARD_MARGIN_X
    copy_left = copy_right - LOG_COPY_BTN_W
    if not (copy_left <= x <= copy_right):
        return None
    y_acc = LOG_HEADER_H + LOG_PANEL_PADDING
    for idx, stride in enumerate(entry_heights):
        if y_acc <= y < y_acc + stride:
            return idx
        y_acc += stride
    return None


def _handle_copy_click(state: AppState) -> None:
    """Copy the transcript of the history row under a left-click, if any."""
    user32 = ctypes.windll.user32

    # VK_LBUTTON
    if not (user32.GetAsyncKeyState(0x01) & 0x8000):
        state.copy_debounce = False
        return

    if state.copy_debounce or state.active_panel != "info" or not state.log_panel_hwnd:
        return

    pt = ctypes.wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    rect = ctypes.wintypes.RECT()
    user32.GetWindowRect(state.log_panel_hwnd, ctypes.byref(rect))
    rx = pt.x - rect.left
    ry = pt.y - rect.top

    panel_w, _ = _log_panel_dims()
    idx = _copy_row_at_position(rx, ry, panel_w, state.log_entry_heights)
    if idx is None:
        return

    entries = _visible_entries(
        state.transcription_log, state.log_scroll_offset, LOG_PANEL_MAX_VISIBLE,
    )
    if idx < len(entries):
        text = entries[idx].get("text", "")
        if text and text != "No transcriptions yet":
            try:
                pyperclip.copy(text)
                log.info("COPIED: %s", text[:50])
                state.copied_row = idx
                state.copied_time = time.time()
            except Exception:
                log.exception("Failed to copy text")
    state.copy_debounce = True
