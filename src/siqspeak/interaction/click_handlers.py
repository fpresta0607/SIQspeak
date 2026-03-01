from __future__ import annotations

import ctypes
import ctypes.wintypes
import logging

from siqspeak.config import (
    _DRAG_THRESHOLD,
    _ZONE_PANEL,
    AVAILABLE_MODELS,
    IDLE_H,
    IDLE_ICON_ZONE_W,
    IDLE_W,
    MODEL_PANEL_HEADER_H,
    MODEL_PANEL_ROW_H,
    SETTINGS_HEADER_H,
    save_config,
)
from siqspeak.interaction.hover import _is_cursor_over_hwnd
from siqspeak.overlay.pill import _pill_screen_rect
from siqspeak.state import AppState

log = logging.getLogger("siqspeak")


def _get_idle_icon_zone(cursor_x: int, pill_left: int) -> int | None:
    """Map cursor X to icon zone 0 (info), 1 (model), 2 (settings), or None."""
    rx = cursor_x - pill_left
    if rx < 0 or rx >= IDLE_W:
        return None
    zone = rx // IDLE_ICON_ZONE_W
    return min(zone, 2)


def _handle_idle_pill_click(state: AppState) -> None:
    """Handle click/drag on idle pill. Short click = toggle panel; drag = reposition."""
    from siqspeak.overlay.panels import _hide_all_panels, _toggle_panel

    user32 = ctypes.windll.user32

    mouse_down = bool(user32.GetAsyncKeyState(0x01) & 0x8000)

    if not mouse_down:
        # --- Mouse released ---
        if state.drag_active:
            # End drag -- save position
            px, py, _, _ = _pill_screen_rect(state)
            state.pill_user_x = px
            state.pill_user_y = py
            save_config({
                "model": state.loaded_model_name,
                "stream_mode": state.stream_mode,
                "pill_x": state.pill_user_x,
                "pill_y": state.pill_user_y,
                "device": state.device,
                "mic_device": state.mic_device,
            })
            state.drag_active = False
            state.drag_pending = False
            state.idle_click_debounce = True
            return

        if state.drag_pending:
            # Was pressed on pill but didn't move enough -- treat as click
            state.drag_pending = False
            rect = ctypes.wintypes.RECT()
            user32.GetWindowRect(state.overlay_hwnd, ctypes.byref(rect))
            zone = _get_idle_icon_zone(state.drag_start_x, rect.left)
            if zone is not None:
                _toggle_panel(state, _ZONE_PANEL[zone])
            state.idle_click_debounce = True
            return

        state.idle_click_debounce = False
        return

    # --- Mouse is down ---
    if state.idle_click_debounce:
        return

    if state.drag_active:
        # Continue dragging -- move pill to follow cursor
        pt = ctypes.wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        new_x = state.drag_pill_x + (pt.x - state.drag_start_x)
        new_y = state.drag_pill_y + (pt.y - state.drag_start_y)
        user32.SetWindowPos(
            state.overlay_hwnd, None, new_x, new_y, IDLE_W, IDLE_H,
            0x0010 | 0x0004,
        )
        # Reposition open panel to follow
        if state.active_panel:
            from siqspeak.overlay.panels import _toggle_panel
            # Re-show the currently active panel at new position
            panel_name = state.active_panel
            state.active_panel = None  # clear so toggle opens (not closes)
            _toggle_panel(state, panel_name)
        return

    if state.drag_pending:
        # Check if cursor has moved enough to start a drag
        pt = ctypes.wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        dx = abs(pt.x - state.drag_start_x)
        dy = abs(pt.y - state.drag_start_y)
        if dx > _DRAG_THRESHOLD or dy > _DRAG_THRESHOLD:
            state.drag_active = True
            _hide_all_panels(state)
        return

    # Fresh click -- check what's under cursor
    if not _is_cursor_over_hwnd(state.overlay_hwnd):
        # Click outside pill -- dismiss panels if also outside active panel
        if state.active_panel:
            active_hwnd = {
                "info": state.log_panel_hwnd,
                "model": state.model_panel_hwnd,
                "settings": state.settings_panel_hwnd,
            }.get(state.active_panel)
            if not _is_cursor_over_hwnd(active_hwnd):
                _hide_all_panels(state)
                state.idle_click_debounce = True
        return

    # Mouse down on pill -- start tracking for drag-or-click
    pt = ctypes.wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    rect = ctypes.wintypes.RECT()
    user32.GetWindowRect(state.overlay_hwnd, ctypes.byref(rect))
    state.drag_start_x = pt.x
    state.drag_start_y = pt.y
    state.drag_pill_x = rect.left
    state.drag_pill_y = rect.top
    state.drag_pending = True


def _handle_model_click(state: AppState) -> None:
    """Detect click on a model row -- two-click confirmation for uncached models."""
    from siqspeak.model.manager import (
        _is_model_cached,
        _start_model_download_and_load,
        _start_model_load,
    )
    from siqspeak.overlay.panels.model_panel import _show_model_panel

    user32 = ctypes.windll.user32

    if not (user32.GetAsyncKeyState(0x01) & 0x8000):
        state.model_click_debounce = False
        return
    if state.model_click_debounce:
        return
    if state.model_loading or not state.model_panel_hwnd or state.active_panel != "model":
        return
    if not _is_cursor_over_hwnd(state.model_panel_hwnd):
        # Click outside panel -- cancel confirmation if pending
        if state.download_confirm_name:
            state.download_confirm_name = None
            _show_model_panel(state)
        return

    state.model_click_debounce = True
    pt = ctypes.wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    rect = ctypes.wintypes.RECT()
    user32.GetWindowRect(state.model_panel_hwnd, ctypes.byref(rect))

    ry = pt.y - rect.top - MODEL_PANEL_HEADER_H
    row = ry // MODEL_PANEL_ROW_H
    if 0 <= row < len(AVAILABLE_MODELS):
        name = AVAILABLE_MODELS[row]
        if name == state.loaded_model_name:
            return

        if _is_model_cached(name):
            # Cached: load immediately
            state.download_confirm_name = None
            _start_model_load(state, name)
        elif name == state.download_confirm_name:
            # Second click: confirmed -- start download + load
            state.download_confirm_name = None
            _start_model_download_and_load(state, name)
        else:
            # First click on uncached model: show confirmation
            state.download_confirm_name = name
            _show_model_panel(state)


def _handle_settings_click(state: AppState) -> None:
    """Detect click on stream toggle, GPU toggle, mic selector, or Quit."""
    from siqspeak.model.manager import _start_model_load
    from siqspeak.overlay.panels import _show_panel_window
    from siqspeak.overlay.panels.settings_panel import _render_settings_panel

    user32 = ctypes.windll.user32

    if not (user32.GetAsyncKeyState(0x01) & 0x8000):
        state.settings_click_debounce = False
        return
    if state.settings_click_debounce:
        return
    if not state.settings_panel_hwnd or state.active_panel != "settings":
        return
    if not _is_cursor_over_hwnd(state.settings_panel_hwnd):
        return

    state.settings_click_debounce = True

    # Get click position relative to panel
    pt = ctypes.wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    rect = ctypes.wintypes.RECT()
    user32.GetWindowRect(state.settings_panel_hwnd, ctypes.byref(rect))
    ry = pt.y - rect.top

    # Row layout: header, then 44px rows (stream, gpu if available, mic), then quit
    row_h = 44
    row_start = SETTINGS_HEADER_H + 8  # first row top
    row_idx = (ry - row_start) // row_h if ry >= row_start else -1

    if ry < SETTINGS_HEADER_H:
        return  # clicked header area

    # Map row index to action based on whether GPU row is present
    # Row 0 = stream, Row 1 = gpu (if has_cuda) else mic, Row 2 = mic (if has_cuda)
    stream_row = 0
    gpu_row = 1 if state.has_cuda else -1
    mic_row = 2 if state.has_cuda else 1
    quit_top = row_start + row_h * (3 if state.has_cuda else 2) + 12

    def _save() -> None:
        save_config({
            "model": state.loaded_model_name,
            "stream_mode": state.stream_mode,
            "pill_x": state.pill_user_x,
            "pill_y": state.pill_user_y,
            "device": state.device,
            "mic_device": state.mic_device,
        })

    def _rerender_settings() -> None:
        buf, pw, ph = _render_settings_panel(state)
        _show_panel_window(state, state.settings_panel_hwnd, buf, pw, ph)

    if row_idx == stream_row and ry < row_start + row_h:
        state.stream_mode = not state.stream_mode
        log.info("STREAM_MODE toggled to %s", state.stream_mode)
        _save()
        _rerender_settings()
    elif state.has_cuda and row_idx == gpu_row and ry < row_start + row_h * 2:
        if state.device == "cuda":
            state.device, state.compute_type = "cpu", "int8"
        else:
            state.device, state.compute_type = "cuda", "float16"
        log.info("GPU toggled: device=%s, compute_type=%s", state.device, state.compute_type)
        _save()
        _rerender_settings()
        _start_model_load(state, state.loaded_model_name)
    elif row_idx == mic_row and ry < row_start + row_h * (mic_row + 1):
        if state.mic_devices:
            if state.mic_device is None:
                state.mic_device = state.mic_devices[0]["index"]
            else:
                cur_indices = [d["index"] for d in state.mic_devices]
                try:
                    pos = cur_indices.index(state.mic_device)
                    state.mic_device = cur_indices[(pos + 1) % len(cur_indices)]
                except ValueError:
                    state.mic_device = cur_indices[0]
            log.info(
                "Mic changed to device %d: %s",
                state.mic_device,
                next(
                    (d["name"] for d in state.mic_devices if d["index"] == state.mic_device),
                    "?",
                ),
            )
            _save()
            _rerender_settings()
    elif ry >= quit_top:
        state.should_quit = True
        if state.icon:
            state.icon.stop()
