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

Single-file (`dictate.py`, ~900 lines). No modules, no packages.

**Flow:** `main()` loads model → starts pystray in background thread → runs unified Win32 message loop on main thread (handles hotkey, overlay animation, and hover/click events).

**Hotkey cycle (hold-to-record):**
1. Hold Ctrl+Shift+Space → `RegisterHotKey` fires `on_hotkey_down()` → `start_recording()` opens mic stream, saves `GetForegroundWindow()` as paste target, pill expands to active mode
2. Release Space → `_wait_for_release()` polling thread detects key-up via `GetAsyncKeyState` → `stop_and_transcribe()` runs Whisper inference, restores foreground window via `AttachThreadInput` + `SetForegroundWindow`, types text via `SendInput` Unicode events, pill returns to idle

**State management:** `set_state("idle" | "recording" | "transcribing")` drives both tray icon color and overlay mode. Thread-safe via atomic global write (`_overlay_target_state`) under CPython GIL; main thread reads it each timer tick.

**Overlay (two modes):**
- Idle: small 36x36 circle with "i" icon, hoverable — shows transcription history panel on hover
- Active: 150x40 pill with audio-reactive dots, click-through (`WS_EX_TRANSPARENT`)

Rendered via `UpdateLayeredWindow` with pre-multiplied alpha BGRA buffers from numpy. Animates at ~30fps via `SetTimer`. Never steals focus — shown via `SW_SHOWNA`.

**Log panel:** Appears on hover over idle pill. Shows recent transcriptions with timestamps and copy buttons. Uses `pyperclip` for clipboard. Auto-hides with 300ms grace period.

**Color palette:** Dark blue (20,40,80), cyan (0,200,220), gray (140,140,150), white (230,240,255). Recording = cyan dots. Transcribing = white dots.

**Threading model:**
- Main thread: Win32 message loop (`GetMessageW`) handles `WM_HOTKEY` + `WM_TIMER`
- Background daemon: pystray tray icon
- Temporary daemon threads: `_wait_for_release()` polling, transcription

**Text input:** `type_text()` uses `SendInput` with `KEYEVENTF_UNICODE` to type directly into the focused window. No clipboard involved in the paste flow.

**Error handling:** All critical paths wrapped in try/except with `log.exception()`. `stop_and_transcribe()` has a `finally` block that always resets state to idle. `_hotkey_busy` flag prevents rapid-fire re-triggering.

## Configuration

All config is hardcoded at the top of `dictate.py`:

- `MODEL_NAME` — `"tiny"` (faster-whisper handles cache resolution and auto-download)
- `SAMPLE_RATE` — 16000 Hz
- `HOTKEY` — Ctrl+Shift+Space (via `RegisterHotKey`)
- Inference: CPU-only, int8 quantization, beam_size=1, English-only, no VAD filter

## Dependencies

Managed via pip in `.venv`. Listed in `requirements.txt`: `faster-whisper`, `sounddevice`, `numpy`, `pystray`, `pillow`, `pyperclip`.

## Logging

File-only logging to `dictate.log` in the script directory. Format: `HH:MM:SS.mmm MESSAGE`. No console output (especially when run via `pythonw.exe`).

## Notes

- No admin/elevated privileges required — uses `RegisterHotKey` (not low-level keyboard hooks).
