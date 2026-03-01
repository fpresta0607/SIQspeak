# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

SIQspeak — a single-file Windows desktop app that provides local speech-to-text via OpenAI's Whisper model. Runs in the system tray; hold Ctrl+Shift+Space to record, release to transcribe and auto-type into the active window.

## Running

```bash
# Normal (with console)
.venv/Scripts/python.exe dictate.py

# Silent (no console window, production use)
.venv/Scripts/pythonw.exe dictate.py
```

There is no build step, test suite, or linter configured. The app is a single `dictate.py` file.

## Architecture

Single-file (`dictate.py`, ~2100 lines). No modules, no packages.

**Flow:** `main()` loads model → starts pystray in background thread → runs unified Win32 message loop on main thread (handles hotkey, overlay animation, and hover/click events).

**Hotkey cycle (hold-to-record):**
1. Hold Ctrl+Shift+Space → `RegisterHotKey` fires `on_hotkey_down()` → `start_recording()` opens mic stream, saves `GetForegroundWindow()` as paste target, pill expands to active mode
2. Release Space → `_wait_for_release()` polling thread detects key-up via `GetAsyncKeyState` → `stop_and_transcribe()` runs Whisper inference, restores foreground window via `AttachThreadInput` + `SetForegroundWindow`, types text via `SendInput` Unicode events, pill returns to idle

**State management:** `set_state("idle" | "recording" | "transcribing")` drives both tray icon color and overlay mode. Thread-safe via atomic global write (`_overlay_target_state`) under CPython GIL; main thread reads it each timer tick.

**Overlay (two modes):**
- Idle: 110x36 toolbar with 3 clickable icon zones (info "i", model hexagon, gear). Click toggles panels. NOT click-through.
- Active: 120x32 pill with 6 audio-reactive dots, click-through (`WS_EX_TRANSPARENT`)

Rendered via `UpdateLayeredWindow` with pre-multiplied alpha BGRA buffers from numpy. Animates at ~30fps via `SetTimer`. Never steals focus — shown via `SW_SHOWNA`. Topmost re-asserted every ~2s via `SetWindowPos`.

**Panels (click-activated, one at a time):**
All three panels share consistent styling: 14px corner radius, 0.94 alpha background, header with title (22px seguisb) + separator line, 20px side padding. Panel dimensions are screen-adaptive via `_screen_size()` / `GetSystemMetrics` — computed dynamically per render, not hardcoded. Panels are clamped to screen boundaries with 8px margin.

- **Log panel:** Shows recent transcriptions (up to 20 visible) with timestamps and copy buttons. Supports mouse wheel scrolling via `WH_MOUSE_LL` low-level hook with scroll indicators (▲/▼). Uses `pyperclip` for clipboard. Width/height scale with screen resolution.
- **Model selector:** "Models" header + rows. Cached models show "ready" and load on single click. Uncached models show download size and require two-click confirmation with progress bar. Internet connectivity is checked before download. Errors auto-clear after 5s.
- **Settings panel:** "Settings" header, stream mode toggle pill (rounded ON/OFF visual with knob), and Quit button.

Clicking an icon toggles its panel; clicking outside pill+panel dismisses it. All panels auto-hide when recording starts.

**DPI awareness:** `SetProcessDpiAwareness(2)` called before any Win32 calls to ensure correct positioning on high-DPI displays.

**Color palette:** Dark blue (20,40,80), cyan (0,200,220), gray (140,140,150), white (230,240,255). Recording = cyan dots. Transcribing = white dots.

**Streaming transcription (opt-in via settings panel):**
When `STREAM_MODE` is enabled, the `on_audio` callback monitors raw RMS for silence. After ~0.7s of silence, accumulated audio is dispatched to a background `_transcription_worker` thread via `queue.Queue`. The worker calls `model.transcribe()` with Silero VAD enabled (`vad_filter=True`) to strip non-speech audio, `condition_on_previous_text=False` to prevent cross-chunk duplication, and a post-transcription hallucination filter (no_speech_prob + known pattern matching). Focuses the target window once and types the result immediately. Recording continues. On key release, remaining audio is flushed.

**Threading model:**
- Main thread: Win32 message loop (`GetMessageW`) handles `WM_HOTKEY` + `WM_TIMER` + click detection + mouse wheel scroll (via `WH_MOUSE_LL` hook delta accumulation)
- Background daemon: pystray tray icon
- Temporary daemon threads: `_wait_for_release()` polling, transcription, model loading/downloading
- Streaming worker (when enabled): `_transcription_worker` — single consumer on `_stream_queue`

**Text input:** `type_text()` uses `SendInput` with `KEYEVENTF_UNICODE` to type directly into the focused window. No clipboard involved in the paste flow.

**Error handling:** All critical paths wrapped in try/except with `log.exception()`. `stop_and_transcribe()` has a `finally` block that always resets state to idle. `_hotkey_busy` flag prevents rapid-fire re-triggering.

## Configuration

All config is hardcoded at the top of `dictate.py`:

- `MODEL_NAME` — `"tiny"` default (changeable at runtime via model selector panel)
- `AVAILABLE_MODELS` — tiny, base, small, medium, large-v2, large-v3
- `MODEL_SIZES_MB` — approximate download sizes per model (75 MB to ~3 GB)
- `SAMPLE_RATE` — 16000 Hz
- `HOTKEY` — Ctrl+Shift+Space (via `RegisterHotKey`)
- Inference: CPU-only, int8 quantization, beam_size=1, English-only, Silero VAD enabled
- `STREAM_MODE` — `False` default (toggleable at runtime via settings panel)
- `SILENCE_RMS_THRESHOLD` — `0.012` (increase for noisy rooms, decrease for quiet rooms)
- `SILENCE_DURATION` — `0.7` seconds of silence before dispatching a chunk
- `MIN_CHUNK_DURATION` — `0.5` seconds minimum audio to attempt transcription

## Dependencies

Managed via pip in `.venv`. Listed in `requirements.txt`: `faster-whisper`, `sounddevice`, `numpy`, `pystray`, `pillow`, `pyperclip`.

## Logging

File-only logging to `dictate.log` in the script directory. Format: `HH:MM:SS.mmm MESSAGE`. No console output (especially when run via `pythonw.exe`).

## Notes

- No admin/elevated privileges required — uses `RegisterHotKey` (not low-level keyboard hooks). A `WH_MOUSE_LL` hook is used for log panel scroll but requires no special privileges.
