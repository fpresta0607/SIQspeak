"""SIQspeak application entry point — main() and message_loop()."""
from __future__ import annotations

import ctypes
import ctypes.wintypes
import logging
import sys
import threading
import time

from faster_whisper import WhisperModel
from pystray import Icon, Menu, MenuItem

from siqspeak._frozen import bundled_model_path
from siqspeak.audio.devices import _get_input_devices
from siqspeak.audio.recording import _load_log, transcription_worker_loop
from siqspeak.config import (
    ACTIVE_H,
    ACTIVE_W,
    AVAILABLE_MODELS,
    IDLE_H,
    IDLE_W,
    LOG_PANEL_MAX_VISIBLE,
    MODEL_NAME,
    MODEL_PANEL_HEADER_H,
    MODEL_PANEL_ROW_H,
    SCRIPT_DIR,
    STATE_NAME,
    WM_APP_STATE,
    WM_TIMER,
    _load_config,
    device_settings,
)
from siqspeak.hotkey import on_hotkey_down, quit_app
from siqspeak.interaction.click_handlers import (
    _get_idle_icon_zone,
    _handle_idle_pill_click,
    _handle_model_click,
    _handle_settings_click,
)
from siqspeak.interaction.hover import (
    _handle_copy_click,
    _is_cursor_over_hwnd,
    _update_copy_hover,
)
from siqspeak.logging_setup import configure_logging
from siqspeak.overlay.panels import _hide_all_panels, _update_panel_content
from siqspeak.overlay.panels.log_panel import _render_log_panel, _show_log_panel
from siqspeak.overlay.panels.model_panel import _render_model_panel
from siqspeak.overlay.panels.welcome import _hide_welcome, _show_welcome
from siqspeak.overlay.pill import _set_pill_mode
from siqspeak.overlay.rendering import _build_idle_frame, _render_frame
from siqspeak.state import AppState
from siqspeak.tray import make_icon
from siqspeak.win32.dpi import enable_dpi_awareness
from siqspeak.win32.hooks import (
    install_keyboard_hook,
    install_mouse_hook,
    uninstall_keyboard_hook,
    uninstall_mouse_hook,
)
from siqspeak.win32.window import (
    _create_active_overlay,
    _create_idle_overlay,
    _create_panel_window,
    _update_layered_window,
)

log = logging.getLogger("siqspeak")


def _recover_after_sleep(state: AppState) -> None:
    """Reinstall Win32 hooks and reset stuck recording state after sleep/wake."""
    log.info("System resumed from sleep — recovering hooks and state")

    # If recording was in progress when the machine slept, clean it up
    if state.is_recording:
        state.is_recording = False
        if state.mic_stream:
            try:
                state.mic_stream.stop()
                state.mic_stream.close()
            except Exception:
                pass
            state.mic_stream = None
        state.audio_chunks = []

    # Release stuck hotkey flags (win_held can stay True if hook died mid-press)
    from siqspeak.win32 import hooks as _hooks
    _hooks.win_held = False
    _hooks._win_suppressed = False
    state.hotkey_busy = False
    from siqspeak.tray import set_state as _set_state
    _set_state(state, "idle")

    # Reinstall keyboard hook
    uninstall_keyboard_hook(state)
    install_keyboard_hook(state)
    if state.keyboard_hook:
        log.info("Keyboard hook reinstalled after sleep")
    else:
        log.error("Failed to reinstall keyboard hook after sleep")

    # Reinstall mouse hook
    uninstall_mouse_hook(state)
    install_mouse_hook(state)
    if state.mouse_hook:
        log.info("Mouse hook reinstalled after sleep")


def message_loop(state: AppState) -> None:
    """Unified Win32 message loop: hotkey + overlay animation + panel interaction."""
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    WM_APP_HOTKEY = 0x8001  # custom message posted by keyboard hook
    WM_POWERBROADCAST = 0x0218
    PBT_APMRESUMEAUTOMATIC = 0x12  # system auto-resumed (e.g. scheduled wake)
    PBT_APMRESUMESUSPEND = 0x7     # user-initiated resume from suspend
    PBT_APMSUSPEND = 0x0004        # system is about to sleep/hibernate

    # Store thread ID so background threads can PostThreadMessageW to us
    state._main_thread_id = kernel32.GetCurrentThreadId()

    install_keyboard_hook(state)
    if not state.keyboard_hook:
        log.error("Failed to install keyboard hook for Ctrl+Win hotkey")
        return
    log.info("Hotkey: hold Ctrl+Win to record, release to transcribe")

    # Create two overlay windows with immutable styles (no runtime style toggling)
    state.idle_overlay_hwnd = _create_idle_overlay(state)
    state.active_overlay_hwnd = _create_active_overlay(state)
    if not state.idle_overlay_hwnd or not state.active_overlay_hwnd:
        log.error("Failed to create overlay windows")
        return
    state.overlay_hwnd = state.idle_overlay_hwnd  # idle is the initial visible window
    log.info(
        "Overlay windows created: idle=%d, active=%d",
        state.idle_overlay_hwnd, state.active_overlay_hwnd,
    )

    state.log_panel_hwnd = _create_panel_window()
    state.model_panel_hwnd = _create_panel_window()
    state.settings_panel_hwnd = _create_panel_window()
    state.welcome_hwnd = _create_panel_window()

    install_mouse_hook(state)
    if not state.mouse_hook:
        log.warning("Failed to install mouse hook — log panel scroll disabled")

    # Show idle pill immediately
    _update_layered_window(state.idle_overlay_hwnd, _build_idle_frame(), IDLE_W, IDLE_H)
    user32.ShowWindow(state.idle_overlay_hwnd, 8)  # SW_SHOWNA

    _show_welcome(state)

    timer_id = user32.SetTimer(None, 0, 33, None)  # ~30fps
    HWND_TOPMOST = ctypes.wintypes.HWND(-1)
    SWP_NOMOVE = 0x0002
    SWP_NOSIZE = 0x0001
    SWP_NOACTIVATE = 0x0010

    phase = 0.0
    current_state = "idle"
    topmost_tick = 0
    was_model_loading = False

    msg = ctypes.wintypes.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
        if state.should_quit:
            if state.overlay_hwnd:
                user32.KillTimer(None, timer_id)
                uninstall_keyboard_hook(state)
                uninstall_mouse_hook(state)
                _hide_all_panels(state)
                _hide_welcome(state)
                for hwnd in (state.log_panel_hwnd, state.model_panel_hwnd,
                             state.settings_panel_hwnd, state.welcome_hwnd):
                    if hwnd:
                        user32.DestroyWindow(hwnd)
                state.log_panel_hwnd = None
                state.model_panel_hwnd = None
                state.settings_panel_hwnd = None
                state.welcome_hwnd = None
                for hwnd in (state.idle_overlay_hwnd, state.active_overlay_hwnd):
                    if hwnd:
                        user32.DestroyWindow(hwnd)
                state.idle_overlay_hwnd = None
                state.active_overlay_hwnd = None
                state.overlay_hwnd = None
                user32.PostQuitMessage(0)
            break

        if msg.message == WM_APP_HOTKEY:
            on_hotkey_down(state)

        elif msg.message == WM_APP_STATE:
            # --- Message-driven state transition (thread-safe) ---
            new_state = STATE_NAME.get(msg.wParam, "idle")

            # Stale-idle guard: reject idle from a previous cycle if recording is active
            if new_state == "idle" and (state.is_recording or state.hotkey_busy):
                log.debug(
                    "STATE GUARD: rejected idle (is_recording=%s, hotkey_busy=%s)",
                    state.is_recording, state.hotkey_busy,
                )
            elif new_state != current_state:
                log.info("STATE %s -> %s", current_state, new_state)
                current_state = new_state
                phase = 0.0

                if current_state == "idle":
                    _set_pill_mode(state, "idle")
                    frame = _build_idle_frame(state.hover_zone)
                    _update_layered_window(state.overlay_hwnd, frame, IDLE_W, IDLE_H)
                    # Auto-refresh log panel if new transcription was added
                    if state.log_panel_dirty:
                        state.log_panel_dirty = False
                        if state.active_panel == "info":
                            _show_log_panel(state)
                else:
                    _hide_all_panels(state)
                    _hide_welcome(state)
                    _set_pill_mode(state, "active")

        elif msg.message == WM_POWERBROADCAST:
            if msg.wParam == PBT_APMSUSPEND:
                # System going to sleep/hibernate — kill the process cleanly
                log.info("System suspending — shutting down SIQspeak")
                quit_app(state, state.icon)
            elif msg.wParam in (PBT_APMRESUMEAUTOMATIC, PBT_APMRESUMESUSPEND):
                _recover_after_sleep(state)

        elif msg.message == WM_TIMER:
            # Animate active states
            if current_state != "idle":
                phase += 0.1
                buf = _render_frame(state, current_state, phase)
                _update_layered_window(state.overlay_hwnd, buf, ACTIVE_W, ACTIVE_H)

            # Click-based panel interaction (only in idle state)
            if current_state == "idle":
                # Hover detection (skip during drag to avoid flicker)
                if not state.drag_active:
                    prev_hover = state.hover_zone
                    if _is_cursor_over_hwnd(state.overlay_hwnd):
                        pt = ctypes.wintypes.POINT()
                        user32.GetCursorPos(ctypes.byref(pt))
                        rect = ctypes.wintypes.RECT()
                        user32.GetWindowRect(state.overlay_hwnd, ctypes.byref(rect))
                        state.hover_zone = _get_idle_icon_zone(pt.x, rect.left)
                    else:
                        state.hover_zone = None
                    if state.hover_zone != prev_hover:
                        frame = _build_idle_frame(state.hover_zone)
                        _update_layered_window(state.overlay_hwnd, frame, IDLE_W, IDLE_H)

                _handle_idle_pill_click(state)

                # Handle clicks within active panels
                if state.active_panel == "info":
                    prev_copied = state.copied_row
                    _handle_copy_click(state)
                    prev_copy_hover = state.copy_hover_row
                    _update_copy_hover(state)
                    needs_rerender = (
                        state.copy_hover_row != prev_copy_hover
                        or state.copied_row != prev_copied
                    )
                    if state.copied_row is not None and (time.time() - state.copied_time) >= 1.5:
                        state.copied_row = None
                        needs_rerender = True
                    if needs_rerender:
                        # Content-only update — skip SetWindowPos to avoid flicker
                        buf, pw, ph = _render_log_panel(state)
                        _update_panel_content(state.log_panel_hwnd, buf, pw, ph)

                elif state.active_panel == "model":
                    _handle_model_click(state)
                    # Hover tracking for model rows (skip during loading)
                    if not state.model_loading:
                        if state.model_panel_hwnd and _is_cursor_over_hwnd(state.model_panel_hwnd):
                            pt = ctypes.wintypes.POINT()
                            user32.GetCursorPos(ctypes.byref(pt))
                            rect = ctypes.wintypes.RECT()
                            user32.GetWindowRect(state.model_panel_hwnd, ctypes.byref(rect))
                            ry = pt.y - rect.top - MODEL_PANEL_HEADER_H
                            row = ry // MODEL_PANEL_ROW_H
                            hover = row if 0 <= row < len(AVAILABLE_MODELS) else None
                        else:
                            hover = None
                        if hover != state.model_hover_row:
                            state.model_hover_row = hover
                            from siqspeak.overlay.panels import _show_panel_window
                            buf, pw, ph = _render_model_panel(state)
                            _show_panel_window(state, state.model_panel_hwnd, buf, pw, ph)

                        # Auth button hover tracking
                        if state.needs_hf_auth and not state.hf_auth_success:
                            from siqspeak.overlay.panels.model_panel import AUTH_BTN_Y, AUTH_BUTTONS
                            rx = pt.x - rect.left
                            ry_abs = pt.y - rect.top
                            new_hover = ""
                            if AUTH_BTN_Y <= ry_abs <= AUTH_BTN_Y + 32:
                                for bi, btn in enumerate(AUTH_BUTTONS):
                                    if btn["x1"] <= rx <= btn["x2"]:
                                        new_hover = f"btn{bi}"
                                        break
                            if new_hover != state.hf_token_input:
                                state.hf_token_input = new_hover
                                from siqspeak.overlay.panels import _show_panel_window
                                buf2, pw2, ph2 = _render_model_panel(state)
                                _show_panel_window(state, state.model_panel_hwnd, buf2, pw2, ph2)
                elif state.active_panel == "settings":
                    _handle_settings_click(state)

                # Mouse wheel scroll for log panel
                if state.wheel_delta != 0:
                    delta_snapshot = state.wheel_delta
                    state.wheel_delta = 0
                    if state.active_panel == "info" and state.log_panel_hwnd and _is_cursor_over_hwnd(state.log_panel_hwnd):
                        total = len(state.transcription_log)
                        max_offset = max(0, total - LOG_PANEL_MAX_VISIBLE)
                        scroll_lines = delta_snapshot // 120
                        if scroll_lines:
                            state.log_scroll_offset = max(0, min(
                                state.log_scroll_offset + scroll_lines, max_offset))
                            _show_log_panel(state)

                # Loading timeout safety: reset stuck model_loading after 300s (5 min)
                if (state.model_loading and state.model_loading_start > 0
                        and time.time() - state.model_loading_start > 300.0):
                        log.warning("Model load timed out after 300s")
                        state.model_loading = False
                        state.download_error = "Load timed out"
                        state.download_error_time = time.time()

                # Animate model panel during download / refresh after load
                if state.model_loading:
                    was_model_loading = True
                    if state.active_panel == "model" and state.model_panel_hwnd:
                        from siqspeak.overlay.panels import _show_panel_window
                        buf, pw, ph = _render_model_panel(state)
                        _show_panel_window(state, state.model_panel_hwnd, buf, pw, ph)
                elif was_model_loading:
                    was_model_loading = False
                    if state.active_panel == "model" and state.model_panel_hwnd:
                        from siqspeak.overlay.panels import _show_panel_window
                        buf, pw, ph = _render_model_panel(state)
                        _show_panel_window(state, state.model_panel_hwnd, buf, pw, ph)

                # Auto-clear download error after 5 seconds
                if state.download_error and (time.time() - state.download_error_time) >= 5.0:
                    state.download_error = None
                    if state.active_panel == "model" and state.model_panel_hwnd:
                        from siqspeak.overlay.panels import _show_panel_window
                        buf, pw, ph = _render_model_panel(state)
                        _show_panel_window(state, state.model_panel_hwnd, buf, pw, ph)

            # Auto-dismiss welcome tooltip after 5 seconds
            if state.welcome_shown and time.time() - state.welcome_show_time >= 5.0:
                _hide_welcome(state)

            # Topmost re-assertion every ~0.3 seconds (10 ticks at 33ms)
            # More frequent than 1s to stay above aggressive apps.
            # Panels are excluded: they're already TOPMOST and calling SetWindowPos
            # on a window while the cursor hovers over it causes a visible mouse stutter.
            topmost_tick += 1
            if topmost_tick >= 10:
                topmost_tick = 0
                for hwnd in (state.overlay_hwnd, state.welcome_hwnd):
                    if hwnd and user32.IsWindowVisible(hwnd):
                        user32.SetWindowPos(
                            hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
                        )



def main() -> None:
    """Application entry point."""
    # Single-instance guard: prevent multiple copies running at the same time.
    # CreateMutexW returns a handle even if it already exists; GetLastError()
    # returns ERROR_ALREADY_EXISTS (183) in that case.
    _MUTEX_NAME = "Global\\SIQspeak_SingleInstance_v1"
    _app_mutex = ctypes.windll.kernel32.CreateMutexW(None, True, _MUTEX_NAME)
    if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        ctypes.windll.user32.MessageBoxW(
            None,
            "SIQspeak is already running.\nCheck the system tray to access it.",
            "SIQspeak",
            0x40 | 0x1000,  # MB_ICONINFORMATION | MB_SETFOREGROUND
        )
        sys.exit(0)

    enable_dpi_awareness()
    configure_logging(SCRIPT_DIR)

    state = AppState()

    # Load persisted config
    cfg = _load_config()
    state.loaded_model_name = cfg.get("model", MODEL_NAME)
    state.stream_mode = False
    state.pill_user_x = cfg.get("pill_x")
    state.pill_user_y = cfg.get("pill_y")
    state.mic_device = cfg.get("mic_device")

    # Load persisted transcription log
    _load_log(state)

    # GPU auto-detection
    import ctranslate2
    state.has_cuda = ctranslate2.get_cuda_device_count() > 0
    saved_device = cfg.get("device")
    if saved_device == "cuda" and state.has_cuda:
        state.device, state.compute_type = device_settings(True)
    elif saved_device == "cpu":
        state.device, state.compute_type = device_settings(False)
    else:
        state.device, state.compute_type = device_settings(state.has_cuda)
    log.info("Device: %s (%s), CUDA available: %s", state.device, state.compute_type, state.has_cuda)

    # Cache available microphones
    state.mic_devices = _get_input_devices()
    if state.mic_device is not None:
        valid_indices = {d["index"] for d in state.mic_devices}
        if state.mic_device not in valid_indices:
            log.warning("Saved mic device %d not found, using default", state.mic_device)
            state.mic_device = None

    log.info("Loading model...")
    t0 = time.perf_counter()
    model_name = state.loaded_model_name
    model_path = bundled_model_path(model_name) or model_name
    try:
        state.model = WhisperModel(model_path, device=state.device, compute_type=state.compute_type)
        # Validate CUDA actually works by running minimal inference
        if state.device == "cuda":
            import numpy as np
            _silence = np.zeros(16000, dtype=np.float32)
            list(state.model.transcribe(_silence, beam_size=1)[0])
    except Exception:
        if state.device == "cuda":
            log.warning("GPU load failed, falling back to CPU")
            state.device, state.compute_type = device_settings(False)
            state.model = WhisperModel(model_path, device=state.device, compute_type=state.compute_type)
        else:
            log.exception("Failed to load Whisper model")
            sys.exit(1)
    log.info("Model ready in %.2fs", time.perf_counter() - t0)

    # Async transcription worker — hotkey enqueues audio, worker transcribes + types
    import queue as _queue
    state.transcription_queue = _queue.Queue()
    threading.Thread(
        target=transcription_worker_loop, args=(state,), daemon=True,
    ).start()

    menu = Menu(MenuItem("Quit", lambda tray_icon: quit_app(state, tray_icon)))
    state.icon = Icon("SIQspeak", make_icon("gray"), "SIQspeak", menu)

    threading.Thread(target=state.icon.run, daemon=True).start()
    log.info("READY")

    # Main thread: unified message loop (hotkey + overlay animation)
    try:
        message_loop(state)
    finally:
        uninstall_keyboard_hook(state)
        uninstall_mouse_hook(state)
