from __future__ import annotations

import ctypes
import logging
import threading
import time

from siqspeak.config import VK_SPACE
from siqspeak.state import AppState

log = logging.getLogger("siqspeak")


def quit_app(state: AppState, tray_icon) -> None:
    state.should_quit = True
    tray_icon.stop()


def _wait_for_release(state: AppState) -> None:
    """Poll until Space is released, then stop recording and transcribe."""
    user32 = ctypes.windll.user32
    while user32.GetAsyncKeyState(VK_SPACE) & 0x8000:
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
