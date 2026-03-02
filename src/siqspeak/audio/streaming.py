from __future__ import annotations

import logging
import re
import time

import numpy as np
from faster_whisper import WhisperModel

from siqspeak.config import (
    _HALLUCINATION_PATTERNS,
    OVERLAP_TAIL_WORDS,
    device_settings,
    save_state_config,
)
from siqspeak.state import AppState
from siqspeak.win32.text_input import focus_window, type_text

log = logging.getLogger("siqspeak")


def _strip_overlap(text: str, tail_words: list) -> str:
    """Remove leading words that duplicate the previous chunk's tail."""
    def norm(w: str) -> str:
        return re.sub(r"[^a-z0-9]", "", w.lower())

    new_words = text.split()
    tail_norm = [norm(w) for w in tail_words]
    new_norm = [norm(w) for w in new_words]

    for match_len in range(min(len(tail_norm), len(new_norm)), 0, -1):
        if tail_norm[-match_len:] == new_norm[:match_len]:
            log.info("STREAM DEDUP: stripped %d word(s): %s",
                     match_len, " ".join(new_words[:match_len]))
            return " ".join(new_words[match_len:]).strip()

    return text


def _transcription_worker(state: AppState) -> None:
    """Background thread: pull audio segments from queue, transcribe, type."""
    while True:
        item = state.stream_queue.get()
        kind, payload = item

        if kind == "stop":
            break

        if kind == "segment":
            segment_chunks, has_overlap = payload
            done_event = None
        elif kind == "flush":
            segment_chunks, done_event = payload
            has_overlap = False
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
            filtered = []
            for seg in segments:
                t = seg.text.strip()
                if not t:
                    continue
                if seg.no_speech_prob > 0.6 and seg.avg_logprob < -1.0:
                    log.info("STREAM SKIP (no_speech=%.2f logprob=%.2f): %s",
                             seg.no_speech_prob, seg.avg_logprob, t)
                    continue
                if t.lower().rstrip(".!?,") in _HALLUCINATION_PATTERNS:
                    log.info("STREAM SKIP (hallucination): %s", t)
                    continue
                filtered.append(t)
            text = " ".join(filtered).strip()
            elapsed = time.perf_counter() - t0
            log.info("STREAM TRANSCRIBE %.3fs -> %s", elapsed, text)

            if text and has_overlap and state.prev_chunk_tail:
                text = _strip_overlap(text, state.prev_chunk_tail)

            if text:
                state.prev_chunk_tail = text.split()[-OVERLAP_TAIL_WORDS:]
                state.stream_texts.append(text)

                if not state.stream_focus_done and state.target_hwnd:
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

        except RuntimeError as exc:
            log.exception("STREAM: transcription RuntimeError")
            exc_msg = str(exc).lower()
            if "cublas" in exc_msg or "cuda" in exc_msg:
                state.download_error = "GPU error — reloading on CPU"
                state.download_error_time = time.time()
                try:
                    state.device, state.compute_type = device_settings(False)
                    state.model = WhisperModel(
                        state.loaded_model_name,
                        device=state.device,
                        compute_type=state.compute_type,
                    )
                    save_state_config(state)
                    log.info("STREAM: reloaded model on CPU after CUDA error")
                except Exception:
                    log.exception("STREAM: CPU fallback failed")
                    state.download_error = "Transcription failed"
                    state.download_error_time = time.time()
                    break
            else:
                state.download_error = "Transcription error"
                state.download_error_time = time.time()
        except Exception:
            log.exception("STREAM: transcription error")
            state.download_error = "Transcription error"
            state.download_error_time = time.time()
        finally:
            if done_event:
                done_event.set()
