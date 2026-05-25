from __future__ import annotations

import logging
import time

import numpy as np

from siqspeak.state import AppState
from siqspeak.win32.text_input import focus_window, type_text

log = logging.getLogger("siqspeak")


def _transcription_worker(state: AppState) -> None:
    """Background thread: pull audio segments from queue, transcribe, type."""
    while True:
        item = state.stream_queue.get()
        kind, payload = item

        if kind == "stop":
            break

        if kind == "segment":
            segment_chunks = payload
            done_event = None
        elif kind == "flush":
            segment_chunks, done_event = payload
        else:
            continue

        try:
            audio = np.concatenate(segment_chunks)
            t0 = time.perf_counter()
            segments, _ = state.model.transcribe(
                audio,
                beam_size=1,
                language="en",
                temperature=0.0,
                without_timestamps=True,
                no_speech_threshold=0.6,
                condition_on_previous_text=False,
                suppress_blank=True,
            )
            text = " ".join(seg.text.strip() for seg in segments if seg.text.strip()).strip()
            elapsed = time.perf_counter() - t0
            log.info("STREAM TRANSCRIBE %.3fs -> %s", elapsed, text)

            if text:
                state.stream_texts.append(text)

                if state.target_hwnd:
                    if not state.stream_focus_done:
                        try:
                            focus_window(state.target_hwnd)
                            time.sleep(0.15)
                        except Exception:
                            log.exception("STREAM: focus_window failed")
                        state.stream_focus_done = True
                    try:
                        type_text(text + " ", release_modifiers=False)
                    except Exception:
                        log.exception("STREAM: type_text failed")

        except RuntimeError:
            log.exception("STREAM: transcription RuntimeError")
            state.download_error = "Transcription error"
            state.download_error_time = time.time()
        except Exception:
            log.exception("STREAM: transcription error")
            state.download_error = "Transcription error"
            state.download_error_time = time.time()
        finally:
            if done_event:
                done_event.set()
