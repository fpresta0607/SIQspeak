from __future__ import annotations

import logging
import threading
import time

from siqspeak.state import AppState

log = logging.getLogger("siqspeak")


def quit_app(state: AppState, tray_icon) -> None:
    state.should_quit = True
    tray_icon.stop()


MAX_RECORDING_SECS = 120.0  # hard cap — guards against hook missing key-up event


def _wait_for_release(state: AppState) -> None:
    """Poll until Space key is released, then enqueue audio for transcription.

    Includes a hard timeout so a stuck space_held (hook missed key-up) can't
    cause unbounded mic recording and audio_chunks growth.
    """
    from siqspeak.win32 import hooks
    deadline = time.time() + MAX_RECORDING_SECS
    while hooks.space_held:
        if time.time() >= deadline:
            log.warning(
                "Space held for %.0fs — forcing release (hook may have missed key-up).",
                MAX_RECORDING_SECS,
            )
            hooks.space_held = False
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
