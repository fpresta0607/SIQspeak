from __future__ import annotations

import logging
import threading
import time

from siqspeak.state import AppState

log = logging.getLogger("siqspeak")


def quit_app(state: AppState, tray_icon) -> None:
    state.should_quit = True
    tray_icon.stop()


def _wait_for_release(state: AppState) -> None:
    """Poll until Win key is released, then enqueue audio for transcription."""
    from siqspeak.win32 import hooks
    deadline = time.monotonic() + 5.0
    while hooks.win_held:
        if time.monotonic() > deadline:
            log.warning("Win key release not detected after 5s — forcing stop")
            hooks.reset_keyboard_hook_state()
            break
        time.sleep(0.05)
    try:
        from siqspeak.audio.recording import stop_and_enqueue
        stop_and_enqueue(state)
    finally:
        state.hotkey_busy = False


def on_hotkey_down(state: AppState) -> None:
    if state.hotkey_busy:
        return
    state.hotkey_busy = True
    from siqspeak.audio.recording import start_recording
    start_recording(state)
    threading.Thread(target=_wait_for_release, args=(state,), daemon=True).start()
