from __future__ import annotations

import ctypes
import ctypes.wintypes

import numpy as np

from siqspeak.config import _screen_size
from siqspeak.overlay.pill import _pill_screen_rect
from siqspeak.state import AppState
from siqspeak.win32.window import _update_layered_window


def _show_panel_window(state: AppState, hwnd: int, buf: np.ndarray, pw: int, ph: int) -> None:
    """Position a panel window above the pill and show it."""
    if not hwnd or not state.overlay_hwnd:
        return
    user32 = ctypes.windll.user32
    px, py, pill_w, _ = _pill_screen_rect(state)
    pill_center_x = px + pill_w // 2
    panel_x = pill_center_x - pw // 2
    panel_y = py - ph - 8
    # Clamp to screen edges with 8px margin
    sw, _sh = _screen_size()
    panel_x = max(8, min(panel_x, sw - pw - 8))
    panel_y = max(8, panel_y)
    user32.SetWindowPos(hwnd, None, panel_x, panel_y, pw, ph, 0x0010 | 0x0004)
    _update_layered_window(hwnd, buf, pw, ph)
    user32.ShowWindow(hwnd, 8)  # SW_SHOWNA


def _hide_all_panels(state: AppState) -> None:
    """Hide whichever panel is currently active."""
    if state.active_panel == "info" and state.log_panel_hwnd:
        ctypes.windll.user32.ShowWindow(state.log_panel_hwnd, 0)
    elif state.active_panel == "model" and state.model_panel_hwnd:
        ctypes.windll.user32.ShowWindow(state.model_panel_hwnd, 0)
    elif state.active_panel == "settings" and state.settings_panel_hwnd:
        ctypes.windll.user32.ShowWindow(state.settings_panel_hwnd, 0)
    state.active_panel = None


def _toggle_panel(state: AppState, name: str) -> None:
    """Toggle a panel: if it's active close it, otherwise open it (closing any other)."""
    # Lazy imports to avoid circular dependency
    from siqspeak.overlay.panels.log_panel import _show_log_panel
    from siqspeak.overlay.panels.model_panel import _show_model_panel
    from siqspeak.overlay.panels.settings_panel import _show_settings_panel

    _PANEL_SHOW = {
        "info": _show_log_panel,
        "model": _show_model_panel,
        "settings": _show_settings_panel,
    }

    if state.active_panel == name:
        _hide_all_panels(state)
    else:
        _hide_all_panels(state)
        _PANEL_SHOW[name](state)
