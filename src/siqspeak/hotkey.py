from __future__ import annotations

import ctypes
import logging
import threading
import time

from siqspeak.config import VK_LWIN
from siqspeak.state import AppState

log = logging.getLogger("siqspeak")


def quit_app(state: AppState, tray_icon) -> None:
    state.should_quit = True
    tray_icon.stop()


MAX_RECORDING_SECS = 60.0  # safety cap — prevents stuck-key runaway recording


def _wait_for_release(state: AppState) -> None:
    """Poll until Win key is released, then stop recording and transcribe.

    Includes a hard timeout to guard against stuck key state after
    sleep/wake cycles — a common source of unbounded audio_chunks growth
    and eventual OOM crash.
    """
    user32 = ctypes.windll.user32
    deadline = time.time() + MAX_RECORDING_SECS
    while user32.GetAsyncKeyState(VK_LWIN) & 0x8000:
        if time.time() >= deadline:
            log.warning(
                "Key-release not detected after %.0fs — forcing stop "
                "(possible stuck key state after sleep/wake).",
                MAX_RECORDING_SECS,
            )
            break
        time.sleep(0.05)
    try:
        from siqspeak.audio.recording import stop_and_transcribe
        stop_and_transcribe(state)
    finally:
        state.hotkey_busy = False


def on_hotkey_down(state: AppState) -> None:
    if state.hotkey_busy:
        return
    state.hotkey_busy = True
    from siqspeak.audio.recording import start_recording
    start_recording(state)
    threading.Thread(target=_wait_for_release, args=(state,), daemon=True).start()
