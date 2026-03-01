from __future__ import annotations

import ctypes
import ctypes.wintypes
import logging
import time

import pyperclip

from siqspeak.config import (
    LOG_COPY_BTN_W,
    LOG_HEADER_H,
    LOG_PANEL_MAX_VISIBLE,
    LOG_PANEL_PADDING,
    _log_panel_dims,
)
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


def _update_copy_hover(state: AppState) -> None:
    """Update copy_hover_row based on cursor position over copy buttons."""
    if state.active_panel != "info" or not state.log_panel_hwnd:
        state.copy_hover_row = None
        return
    if not _is_cursor_over_hwnd(state.log_panel_hwnd):
        state.copy_hover_row = None
        return

    user32 = ctypes.windll.user32
    pt = ctypes.wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    rect = ctypes.wintypes.RECT()
    user32.GetWindowRect(state.log_panel_hwnd, ctypes.byref(rect))
    rx = pt.x - rect.left
    ry = pt.y - rect.top

    # Check if cursor is in the copy button column
    panel_w, _ = _log_panel_dims()
    copy_x = panel_w - LOG_COPY_BTN_W - 8
    if rx < copy_x or rx > copy_x + LOG_COPY_BTN_W:
        state.copy_hover_row = None
        return

    # Walk variable-height rows
    y_acc = LOG_HEADER_H + LOG_PANEL_PADDING
    entries_count = min(len(state.transcription_log), LOG_PANEL_MAX_VISIBLE)
    for idx, entry_h in enumerate(state.log_entry_heights):
        if idx >= entries_count:
            break
        if y_acc <= ry < y_acc + entry_h:
            state.copy_hover_row = idx
            return
        y_acc += entry_h
    state.copy_hover_row = None


def _handle_copy_click(state: AppState) -> None:
    """Check if user clicked a copy button in the log panel."""
    user32 = ctypes.windll.user32

    # VK_LBUTTON
    if not (user32.GetAsyncKeyState(0x01) & 0x8000):
        state.copy_debounce = False
        return

    if state.copy_debounce or state.active_panel != "info" or not state.log_panel_hwnd:
        return

    # Get cursor position relative to log panel
    pt = ctypes.wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    rect = ctypes.wintypes.RECT()
    user32.GetWindowRect(state.log_panel_hwnd, ctypes.byref(rect))

    rx = pt.x - rect.left
    ry = pt.y - rect.top

    # Check if in copy button column (right edge of panel)
    panel_w, _ = _log_panel_dims()
    copy_x = panel_w - LOG_COPY_BTN_W - 8
    if rx < copy_x or rx > copy_x + LOG_COPY_BTN_W:
        return

    # Walk variable-height rows to find which entry was clicked (scroll-aware)
    total = len(state.transcription_log)
    end = total - state.log_scroll_offset
    start = max(0, end - LOG_PANEL_MAX_VISIBLE)
    entries = list(reversed(state.transcription_log[start:end]))
    y_acc = LOG_HEADER_H + LOG_PANEL_PADDING
    for idx, entry_h in enumerate(state.log_entry_heights):
        if idx >= len(entries):
            break
        if y_acc <= ry < y_acc + entry_h:
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
            return
        y_acc += entry_h
