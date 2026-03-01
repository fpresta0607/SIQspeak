# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

Whisper Dictation — a single-file Windows desktop app that provides local speech-to-text via OpenAI's Whisper model. Runs in the system tray; hold Ctrl+Shift+Space to record, release to transcribe and auto-paste into the active window.

## Running

```bash
# Normal (with console)
.venv/Scripts/python.exe dictate.py

# Silent (no console window, production use)
.venv/Scripts/pythonw.exe dictate.py
```

There is no build step, test suite, or linter configured. The app is a single `dictate.py` file.

## Architecture

Single-file monolith (`dictate.py`, ~350 lines). No modules, no packages.

**Flow:** `main()` loads model → starts pystray in background thread → runs unified Win32 message loop on main thread (handles both hotkey and overlay animation).

**Hotkey cycle (hold-to-record):**
1. Hold Ctrl+Shift+Space → `RegisterHotKey` fires `on_hotkey_down()` → `start_recording()` opens mic stream, saves `GetForegroundWindow()` as paste target, shimmer ring appears
2. Release Space → `_wait_for_release()` polling thread detects key-up via `GetAsyncKeyState` → `stop_and_transcribe()` runs Whisper inference (ring turns blue), restores foreground window via `AttachThreadInput` + `SetForegroundWindow`, copies text to clipboard, simulates Ctrl+V paste, restores old clipboard, ring disappears

**State management:** `set_state("idle" | "recording" | "transcribing")` drives both tray icon color and overlay visibility. Thread-safe via atomic global write (`_overlay_target_state`) under CPython GIL; main thread reads it each timer tick.

**Overlay:** Win32 layered window (`CreateWindowExW` with `WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOPMOST | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW`). Rendered via `UpdateLayeredWindow` with pre-multiplied alpha BGRA buffers from numpy. Anti-aliased ring with rotating shimmer highlight and soft outer glow. Animates at ~30fps via `SetTimer`. Never steals focus — shown via `SW_SHOWNA`.

**Color palette:** Matches dictate.ico — dark blue (20,40,80), cyan (0,200,220), gray (140,140,150), white (230,240,255). Recording = cyan ring with white shimmer. Transcribing = white ring with cyan shimmer.

**Threading model (2 threads):**
- Main thread: Win32 message loop (`GetMessageW`) handles `WM_HOTKEY` + `WM_TIMER`
- Background daemon: pystray tray icon
- Temporary daemon threads: `_wait_for_release()` polling, transcription

**Paste targeting:** `start_recording()` saves `GetForegroundWindow()` → `_target_hwnd`. Before pasting, `focus_window()` uses `AttachThreadInput` trick to reliably restore focus to the target window.

**Error handling:** All critical paths (model loading, mic open, transcription, paste, focus restore) wrapped in try/except with `log.exception()`. `stop_and_transcribe()` has a `finally` block that always resets state to idle. `_hotkey_busy` flag prevents rapid-fire re-triggering.

**Key globals:** `is_recording`, `audio_chunks`, `model`, `icon`, `mic_stream`, `_target_hwnd`, `_overlay_target_state`, `_overlay_hwnd`, `_hotkey_busy`, `_should_quit`.

## Configuration

All config is hardcoded at the top of `dictate.py`:

- `MODEL_NAME` — `"tiny"` (faster-whisper handles cache resolution and auto-download)
- `SAMPLE_RATE` — 16000 Hz
- `HOTKEY` — Ctrl+Shift+Space (via `RegisterHotKey`)
- Inference: CPU-only, int8 quantization, beam_size=1, English-only, no VAD filter

## Dependencies

Managed via pip in `.venv`. Key packages: `faster-whisper`, `sounddevice`, `pyperclip`, `pystray`, `pillow`, `numpy`. No requirements.txt or pyproject.toml exists — install state lives only in the venv.

## Logging

File-only logging to `dictate.log` in the script directory. Format: `HH:MM:SS.mmm MESSAGE`. No console output (especially when run via `pythonw.exe`).

## Notes

- No admin/elevated privileges required — uses `RegisterHotKey` (not low-level keyboard hooks).
