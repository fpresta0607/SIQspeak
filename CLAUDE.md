# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

SIQspeak — a Windows desktop app that provides local speech-to-text via OpenAI's Whisper model. Runs in the system tray; hold Ctrl+Win to record, release to transcribe and auto-type into the active window.

## Running

```bash
# Preferred (as package)
.venv/Scripts/python.exe -m siqspeak

# Legacy entry point (backward-compatible shim)
.venv/Scripts/python.exe dictate.py

# Silent (no console window, production use)
.venv/Scripts/pythonw.exe -m siqspeak
```

## Dev Setup

```bash
python -m venv .venv
.venv/Scripts/activate
pip install -e ".[dev]"

# Lint
ruff check .

# Test
pytest
```

## Package Structure

```
src/siqspeak/
  __init__.py              # __version__, __app_name__
  __main__.py              # python -m siqspeak entry
  app.py                   # main() + message_loop() — orchestrator
  config.py                # constants, paths, colors, dimensions, config persistence, device_settings(), save_state_config()
  state.py                 # AppState dataclass — all mutable state (~100 fields)
  logging_setup.py         # configure_logging()
  hotkey.py                # on_hotkey_down(), _wait_for_release(), quit_app()
  text_processing.py       # postprocess_transcription() — spoken coding syntax → symbols
  tray.py                  # load_tray_icon(), make_icon(), set_state()
  audio/
    recording.py           # start_recording(), stop_and_enqueue(), transcription_worker_loop(), log persistence
    streaming.py           # _transcription_worker(), _strip_overlap()
    devices.py             # _get_input_devices()
  model/
    manager.py             # _start_model_load(), _start_model_download_and_load(), cache check
  overlay/
    rendering.py           # pill masks, idle/active frame rendering, BGRA conversion
    pill.py                # _pill_screen_rect(), _set_pill_mode() — swaps two overlay windows
    panels/
      __init__.py          # _hide_all_panels(), _toggle_panel(), _show_panel_window(), _update_panel_content()
      log_panel.py         # transcription log panel
      model_panel.py       # model selector panel
      settings_panel.py    # settings panel (stream, GPU, mic, quit)
      welcome.py           # welcome tooltip
  interaction/
    click_handlers.py      # idle pill click, model click, settings click
    hover.py               # cursor detection, copy hover/click
  win32/
    structs.py             # ctypes Structures (SIZEL, BLENDFUNCTION, INPUT, etc.)
    dpi.py                 # enable_dpi_awareness()
    text_input.py          # type_text(), focus_window()
    window.py              # _create_idle_overlay(), _create_active_overlay(), _create_panel_window(), _update_layered_window()
    hooks.py               # mouse hook install/uninstall/callback
```

Root `dictate.py` is a 3-line shim for backward compatibility with existing shortcuts.

## Architecture

**State management:** All mutable state lives in a single `AppState` dataclass (`state.py`). Every stateful function receives `state: AppState` as its first parameter. Thread-safe via atomic attribute writes under CPython GIL; `queue.Queue` for streaming dispatch. Overlay state transitions use `PostThreadMessageW` to deliver changes from background threads to the main message loop in order (`WM_APP_STATE` custom message).

**Flow:** `main()` (in `app.py`) loads model → starts pystray in background thread → runs unified Win32 message loop on main thread (handles hotkey, overlay animation, and hover/click events).

**Hotkey cycle (hold-to-record):**
1. Hold Ctrl+Win → `WH_KEYBOARD_LL` hook in `win32/hooks.py` detects Ctrl+Win, suppresses Start Menu (including Win key auto-repeats when Ctrl released first), posts `WM_APP+1` to message loop → `on_hotkey_down()` → `start_recording()` opens mic stream, saves `GetForegroundWindow()` as paste target (own overlay/panel windows filtered out), pill expands to active mode
2. Release Win → `_wait_for_release()` polling thread detects key-up (5s safety timeout) → `stop_and_enqueue()` stops mic, snapshots audio + target window, enqueues for async processing, hotkey released immediately
3. Background `transcription_worker_loop` dequeues audio → runs Whisper inference → postprocesses → restores foreground window → types text via `SendInput` Unicode events → pill returns to idle

**Overlay (two-window architecture):**
Two pre-created overlay windows with immutable extended styles — no runtime `SetWindowLongW` toggling:
- `idle_overlay_hwnd`: 160x44 toolbar with 3 clickable icon zones (info, model, settings). NO `WS_EX_TRANSPARENT`.
- `active_overlay_hwnd`: 180x44 pill with 6 audio-reactive dots. `WS_EX_TRANSPARENT` baked in at creation.

Mode switch = show/hide swap with position sync. `state.overlay_hwnd` always points to the currently visible window. Rendered via `UpdateLayeredWindow` with pre-multiplied alpha BGRA buffers from numpy. Animates at ~30fps via `SetTimer`.

**Panels (click-activated, one at a time):**
All panels share consistent styling: 14px corner radius, opaque background, header + separator, 20px padding. Screen-adaptive dimensions via `GetSystemMetrics`.

- **Log panel:** Recent transcriptions with timestamps and copy buttons. Persisted to `transcriptions.jsonl`. Mouse wheel scroll via `WH_MOUSE_LL` hook.
- **Model selector:** Cached models load on click. Uncached models require two-click confirmation with progress bar.
- **Settings panel:** Stream mode toggle, GPU toggle (CUDA only), mic selector, Quit button.

**Streaming transcription (opt-in):**
When enabled, silence detection (~0.7s) dispatches audio to `_transcription_worker` via `queue.Queue` with overlap for boundary context. Hallucination filter + `_strip_overlap()` dedup. Types results incrementally.

**Threading model:**
- Main thread: Win32 message loop (`GetMessageW`)
- Background daemon: pystray tray icon
- Background daemon: `transcription_worker_loop` — processes queued audio jobs (transcribe + type)
- Temporary daemons: `_wait_for_release()`, model loading
- Streaming worker: `_transcription_worker` (when enabled)

**Text input:** `type_text()` uses `SendInput` with `KEYEVENTF_UNICODE`. No clipboard involved.

## Configuration

Settings persist to `config.json` (gitignored). Auto-detects GPU on first launch. `setup.bat` auto-detects NVIDIA GPU via `nvidia-smi` and installs CUDA runtime packages; app validates CUDA at model load with silent CPU fallback.

**Persisted:** model name, stream mode, pill position, device (cuda/cpu), mic device index.

**Constants in `config.py`:**
- `MODEL_NAME` — `"tiny"` default
- `SAMPLE_RATE` — 16000 Hz
- `HOTKEY` — Ctrl+Win (via `WH_KEYBOARD_LL` hook)
- `SILENCE_RMS_THRESHOLD` — `0.015`
- `SILENCE_DURATION` — `0.7s`
- `MIN_CHUNK_DURATION` — `0.5s`
- `OVERLAP_FRAMES` — `5` callbacks
- `OVERLAP_TAIL_WORDS` — `4` words

## Dependencies

Canonical source: `pyproject.toml`. Legacy `requirements.txt` kept for backward compat.

Runtime: `faster-whisper`, `sounddevice`, `numpy`, `pystray`, `pillow`, `pyperclip`
GPU (optional): `nvidia-cublas-cu12`, `nvidia-cudnn-cu12` — auto-installed by `setup.bat` if NVIDIA GPU detected
Dev: `ruff`, `pyright`, `pytest`, `pytest-cov`

## Logging

File-only logging to `dictate.log`. Format: `HH:MM:SS.mmm MESSAGE`. No console output. Log rotates at 5 MB (keeps 3 backups) to prevent unbounded growth.

## Notes

- No admin privileges required
- `WH_MOUSE_LL` hook for scroll requires no special privileges
- Mouse hook callback kept as module-level ref in `win32/hooks.py` to prevent GC
