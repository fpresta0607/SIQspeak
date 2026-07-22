from __future__ import annotations

import ctypes
import ctypes.wintypes
import logging

from siqspeak.config import (
    _DRAG_THRESHOLD,
    _ZONE_PANEL,
    AVAILABLE_MODELS,
    ENHANCEMENT_MODELS,
    ENHANCEMENT_MODES,
    IDLE_H,
    IDLE_ICON_ZONE_W,
    IDLE_W,
    MODEL_PANEL_HEADER_H,
    MODEL_PANEL_ROW_H,
    enhancement_model_spec,
    save_state_config,
)
from siqspeak.enhancement.hardware import can_run_model
from siqspeak.interaction.hover import _is_cursor_over_hwnd
from siqspeak.overlay.panels.settings_panel import (
    MIC_ROW_H,
    SETTINGS_ROW_H,
    SettingsAction,
    _open_ollama_download,
    _refresh_enhancer_status,
    _settings_layout,
    _start_model_pull,
    settings_action_at_y,
)
from siqspeak.overlay.pill import _pill_screen_rect
from siqspeak.state import AppState
from siqspeak.win32.folder_dialog import select_folder

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
            save_state_config(state)
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
        HWND_TOPMOST = ctypes.wintypes.HWND(-1)
        user32.SetWindowPos(
            state.overlay_hwnd, HWND_TOPMOST, new_x, new_y, IDLE_W, IDLE_H,
            0x0010,
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


def _cycle_enhancement_mode(state: AppState) -> None:
    """Advance the enhancement mode (default -> code -> email -> default) and persist."""
    index = ENHANCEMENT_MODES.index(state.enhancement_mode)
    state.enhancement_mode = ENHANCEMENT_MODES[(index + 1) % len(ENHANCEMENT_MODES)]
    save_state_config(state)


def _apply_workspace_selection(state: AppState, folder: str | None) -> bool:
    """Persist a chosen workspace folder; return whether it changed."""
    if not folder:
        return False
    state.workspace_override = folder
    save_state_config(state)
    return True


def _cycle_enhancer_model(state: AppState) -> None:
    """Advance to the next catalog model, persist, and refresh its status."""
    names = [spec["name"] for spec in ENHANCEMENT_MODELS]
    index = names.index(state.enhancement_model) if state.enhancement_model in names else 0
    state.enhancement_model = names[(index + 1) % len(names)]
    save_state_config(state)
    _refresh_enhancer_status(state)


def _install_model_action(state: AppState) -> None:
    """Act on the enhancer status row: open Ollama download or start a pull.

    A model that the machine cannot run is never downloaded — the pull is refused
    with a clear message instead of wasting several GB on an unusable model.
    """
    if state.enhancement_status == "ollama_missing":
        _open_ollama_download()
    elif state.enhancement_status in ("model_missing", "error", None):
        min_gb = enhancement_model_spec(state.enhancement_model)["min_gb"]
        ok, readout = can_run_model(min_gb)
        if not ok:
            state.enhancement_status = "error"
            state.enhancement_error = (
                f"Needs ~{min_gb:.0f} GB, you have {readout}"
            )
            return
        _start_model_pull(state)
    # "ready" / "pulling": nothing actionable.


def _handle_mic_click(state: AppState, ry: int) -> None:
    """Toggle the mic dropdown or select a device within the mic band."""
    mic_row = _settings_layout(state)[0]
    header_bottom = mic_row.y + SETTINGS_ROW_H
    if ry < header_bottom:
        state.mic_expanded = not state.mic_expanded
        return
    if state.mic_expanded and state.mic_devices:
        dev_idx = (ry - header_bottom) // MIC_ROW_H
        if 0 <= dev_idx < len(state.mic_devices):
            dev = state.mic_devices[dev_idx]
            state.mic_device = dev["index"]
            state.mic_expanded = False
            log.info("Mic changed to device %d: %s", dev["index"], dev["name"])
            save_state_config(state)


def _handle_settings_click(state: AppState) -> None:
    """Route a click within the settings panel to its action.

    State is only mutated here; the message loop re-renders when the settings
    signature changes, so pointer movement never drives a redraw.
    """
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

    pt = ctypes.wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    rect = ctypes.wintypes.RECT()
    user32.GetWindowRect(state.settings_panel_hwnd, ctypes.byref(rect))
    ry = pt.y - rect.top

    action = settings_action_at_y(state, ry)
    if action is None:
        return
    if action == SettingsAction.MICROPHONE:
        _handle_mic_click(state, ry)
    elif action == SettingsAction.MODE:
        _cycle_enhancement_mode(state)
    elif action == SettingsAction.WORKSPACE:
        folder = select_folder(hwnd=state.settings_panel_hwnd or 0)
        if _apply_workspace_selection(state, folder):
            _refresh_enhancer_status(state)
    elif action == SettingsAction.ENHANCER_MODEL:
        _cycle_enhancer_model(state)
    elif action == SettingsAction.INSTALL_MODEL:
        _install_model_action(state)
    elif action == SettingsAction.QUIT:
        state.should_quit = True
        if state.icon:
            state.icon.stop()
