from __future__ import annotations

import ctypes
import json
import logging
import os
import queue
import re
import threading
import time

import numpy as np
import sounddevice as sd

from siqspeak.audio.streaming import _transcription_worker
from siqspeak.config import (
    LOG_FILE_MAX_ENTRIES,
    LOG_FILE_PATH,
    LOG_IN_MEMORY_CAP,
    MIN_CHUNK_DURATION,
    OVERLAP_FRAMES,
    SAMPLE_RATE,
    SILENCE_DURATION,
    SILENCE_RMS_THRESHOLD,
)
from siqspeak.state import AppState
from siqspeak.tray import set_state
from siqspeak.win32.text_input import focus_window, type_text

log = logging.getLogger("siqspeak")


# ---------------------------------------------------------------------------
# Log persistence
# ---------------------------------------------------------------------------
def _load_log(state: AppState) -> None:
    """Load last LOG_IN_MEMORY_CAP entries from JSONL file on startup."""
    if not os.path.exists(LOG_FILE_PATH):
        return
    try:
        entries: list[dict] = []
        with open(LOG_FILE_PATH, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        state.transcription_log = entries[-LOG_IN_MEMORY_CAP:]
        log.info("Loaded %d log entries from disk", len(state.transcription_log))
    except OSError:
        log.warning("Could not read %s", LOG_FILE_PATH)


def _save_log_entry(state: AppState, entry: dict) -> None:
    """Append one entry to JSONL file; trigger rotation periodically."""
    try:
        with open(LOG_FILE_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        state.log_append_count += 1
        if state.log_append_count >= 50:
            _rotate_log_file()
            state.log_append_count = 0
    except OSError:
        log.warning("Could not write to %s", LOG_FILE_PATH)


def _rotate_log_file() -> None:
    """Keep only the last LOG_FILE_MAX_ENTRIES lines in the JSONL file."""
    if not os.path.exists(LOG_FILE_PATH):
        return
    try:
        with open(LOG_FILE_PATH, encoding="utf-8") as f:
            lines = f.readlines()
        if len(lines) <= LOG_FILE_MAX_ENTRIES:
            return
        with open(LOG_FILE_PATH, "w", encoding="utf-8") as f:
            f.writelines(lines[-LOG_FILE_MAX_ENTRIES:])
        log.info("Rotated log file to %d entries", LOG_FILE_MAX_ENTRIES)
    except OSError:
        log.warning("Could not rotate %s", LOG_FILE_PATH)


# ---------------------------------------------------------------------------
# Core recording logic
# ---------------------------------------------------------------------------
def start_recording(state: AppState) -> None:
    """Open microphone and begin capturing audio."""
    if state.is_recording:
        return

    state.target_hwnd = ctypes.windll.user32.GetForegroundWindow()
    state.current_level = 0.0
    state.display_level = 0.0
    state.audio_chunks = []

    # Compute silence threshold in callback count from SILENCE_DURATION.
    # sounddevice default blocksize at 16 kHz ~= 512 frames (~32ms per callback).
    _cb_duration = 512 / SAMPLE_RATE  # seconds per callback
    silence_needed = int(SILENCE_DURATION / _cb_duration)

    streaming = state.stream_mode
    if streaming:
        state.stream_queue = queue.Queue()
        state.silence_count = 0
        state.transcribed_idx = 0
        state.stream_focus_done = False
        state.stream_texts = []
        state.prev_chunk_tail = []
        state.stream_worker = threading.Thread(
            target=_transcription_worker, args=(state,), daemon=True,
        )
        state.stream_worker.start()

    def on_audio(indata, frames, time_info, status):
        if not state.is_recording:
            return

        chunk = indata[:, 0].copy()
        state.audio_chunks.append(chunk)

        rms = float(np.sqrt(np.mean(chunk ** 2)))
        state.current_level = state.current_level * 0.6 + min(rms * 15, 1.0) * 0.4

        if not streaming:
            return

        # Silence detection for streaming dispatch
        if rms < SILENCE_RMS_THRESHOLD:
            state.silence_count += 1
        else:
            state.silence_count = 0

        if state.silence_count == silence_needed:
            # Silence threshold just hit -- dispatch accumulated speech audio
            end_idx = len(state.audio_chunks) - silence_needed  # exclude trailing silence
            if end_idx > state.transcribed_idx:
                # Prepend overlap from previous chunk for word-boundary context
                overlap_start = max(state.transcribed_idx - OVERLAP_FRAMES, 0)
                has_overlap = overlap_start < state.transcribed_idx
                segment = state.audio_chunks[overlap_start:end_idx]
                state.transcribed_idx = end_idx
                state.stream_queue.put(("segment", (segment, has_overlap)))
            state.silence_count = 0  # reset so it doesn't re-trigger each tick

    mic_kwargs: dict = dict(
        samplerate=SAMPLE_RATE, channels=1, dtype="float32",
        blocksize=512, callback=on_audio,
    )
    if state.mic_device is not None:
        mic_kwargs["device"] = state.mic_device
    try:
        state.mic_stream = sd.InputStream(**mic_kwargs)
        state.mic_stream.start()
    except Exception:
        state.mic_stream = None
        if state.mic_device is not None:
            log.warning("Mic device %s unavailable, falling back to default",
                        state.mic_device, exc_info=True)
            state.mic_device = None
            mic_kwargs.pop("device", None)
            try:
                state.mic_stream = sd.InputStream(**mic_kwargs)
                state.mic_stream.start()
            except Exception:
                log.exception("Failed to open default microphone")
                state.mic_stream = None
        else:
            log.exception("Failed to open microphone")

    if state.mic_stream is None:
        set_state(state, "idle")
        if streaming and state.stream_queue:
            state.stream_queue.put(("stop", None))
        return

    state.is_recording = True
    set_state(state, "recording")
    log.info("REC START (stream=%s)", streaming)


def stop_and_transcribe(state: AppState) -> None:
    """Stop mic and route to batch or streaming transcription."""
    if not state.is_recording:
        return
    state.is_recording = False

    try:
        if state.mic_stream:
            state.mic_stream.stop()
            state.mic_stream.close()
            state.mic_stream = None
    except Exception:
        log.exception("Error closing microphone")
        state.mic_stream = None

    if state.stream_mode and state.stream_queue:
        _stop_and_transcribe_streaming(state)
    else:
        _stop_and_transcribe_batch(state)


def _stop_and_transcribe_batch(state: AppState) -> None:
    """Original batch transcription path."""
    set_state(state, "transcribing")

    try:
        if not state.audio_chunks:
            log.info("No audio")
            return

        audio = np.concatenate(state.audio_chunks)
        duration = len(audio) / SAMPLE_RATE
        log.info("REC STOP -- %.1fs captured", duration)

        if duration < 0.3:
            log.info("Too short, skip")
            return

        t0 = time.perf_counter()
        segments, _ = state.model.transcribe(
            audio, beam_size=1, language="en",
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=500),
            no_speech_threshold=0.6,
        )
        # Deduplicate words at VAD segment boundaries
        seg_texts = [seg.text.strip() for seg in segments if seg.text.strip()]
        if len(seg_texts) > 1:
            def _norm(w: str) -> str:
                return re.sub(r"[^a-z0-9]", "", w.lower())
            deduped = [seg_texts[0]]
            for seg_text in seg_texts[1:]:
                prev_words = deduped[-1].split()
                next_words = seg_text.split()
                if (prev_words and next_words
                        and _norm(prev_words[-1]) == _norm(next_words[0])):
                    deduped.append(" ".join(next_words[1:]))
                else:
                    deduped.append(seg_text)
            text = " ".join(t for t in deduped if t).strip()
        else:
            text = " ".join(seg_texts).strip()
        elapsed = time.perf_counter() - t0
        log.info("TRANSCRIBE %.3fs -> %s", elapsed, text)

        if text:
            entry = {
                "text": text,
                "timestamp": time.strftime("%H:%M:%S"),
                "time_epoch": time.time(),
            }
            state.transcription_log.append(entry)
            if len(state.transcription_log) > LOG_IN_MEMORY_CAP:
                state.transcription_log[:] = state.transcription_log[-LOG_IN_MEMORY_CAP:]
            _save_log_entry(state, entry)

            if state.target_hwnd:
                try:
                    focus_window(state.target_hwnd)
                    time.sleep(0.15)
                except Exception:
                    log.exception("Failed to restore foreground window")

            try:
                type_text(text)
            except Exception:
                log.exception("Failed to type text")
            log.info("TYPED: %s", text)
    except Exception:
        log.exception("Transcription failed")
    finally:
        set_state(state, "idle")


def _stop_and_transcribe_streaming(state: AppState) -> None:
    """Flush remaining audio through worker, then tear down."""
    try:
        remaining = state.audio_chunks[state.transcribed_idx:]
        if remaining:
            audio = np.concatenate(remaining)
            duration = len(audio) / SAMPLE_RATE
            log.info("STREAM FLUSH -- %.1fs remaining", duration)

            if duration >= MIN_CHUNK_DURATION:
                set_state(state, "transcribing")
                done_event = threading.Event()
                state.stream_queue.put(("flush", (remaining, done_event)))
                done_event.wait(timeout=30.0)
            else:
                log.info("STREAM FLUSH: too short, skip")
        else:
            log.info("STREAM FLUSH: nothing remaining")

        state.stream_queue.put(("stop", None))
        if state.stream_worker:
            state.stream_worker.join(timeout=5.0)

        # Log combined text as one entry
        full_text = " ".join(state.stream_texts).strip()
        if full_text:
            entry = {
                "text": full_text,
                "timestamp": time.strftime("%H:%M:%S"),
                "time_epoch": time.time(),
            }
            state.transcription_log.append(entry)
            if len(state.transcription_log) > LOG_IN_MEMORY_CAP:
                state.transcription_log[:] = state.transcription_log[-LOG_IN_MEMORY_CAP:]
            _save_log_entry(state, entry)
            log.info("STREAM TYPED: %s", full_text)

    except Exception:
        log.exception("Streaming flush failed")
    finally:
        state.stream_queue = None
        state.stream_worker = None
        set_state(state, "idle")
