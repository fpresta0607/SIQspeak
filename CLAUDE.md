# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

SIQspeak — a Windows desktop app that provides local speech-to-text via OpenAI's Whisper model. Runs in the system tray; hold Ctrl+Shift+Space to record, release to transcribe and auto-type into the active window.

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
  config.py                # constants, paths, colors, dimensions, config persistence, save_state_config()
  state.py                 # AppState dataclass — all mutable state (~100 fields)
  logging_setup.py         # configure_logging()
  hotkey.py                # on_hotkey_down(), _wait_for_release(), quit_app()
  tray.py                  # load_tray_icon(), make_icon(), set_state()
  audio/
    recording.py           # start_recording(), stop_and_enqueue(), transcription_worker_loop(), log persistence
    streaming.py           # _transcription_worker()
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
      settings_panel.py    # settings panel (mic, quit)
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
1. Hold Ctrl+Shift+Space → `WH_KEYBOARD_LL` hook in `win32/hooks.py` detects Ctrl+Shift+Space, suppresses the Space keystroke, posts `WM_APP+1` to message loop → `on_hotkey_down()` → `start_recording()` opens mic stream, saves `GetForegroundWindow()` as paste target (own overlay/panel windows filtered out), pill expands to active mode
2. Release Space → `_wait_for_release()` polling thread detects key-up (120s safety timeout) → `stop_and_enqueue()` stops mic, snapshots audio + target window, enqueues for async processing, hotkey released immediately
3. Background `transcription_worker_loop` dequeues audio → runs Whisper inference → logs raw text → restores foreground window → types text via `SendInput` Unicode events → pill returns to idle

**Overlay (two-window architecture):**
Two pre-created overlay windows with immutable extended styles — no runtime `SetWindowLongW` toggling:
- `idle_overlay_hwnd`: 160x44 toolbar with 3 clickable icon zones (info, model, settings). NO `WS_EX_TRANSPARENT`.
- `active_overlay_hwnd`: 180x44 pill with 6 audio-reactive dots. `WS_EX_TRANSPARENT` baked in at creation.

Mode switch = show/hide swap with position sync. `state.overlay_hwnd` always points to the currently visible window. Rendered via `UpdateLayeredWindow` with pre-multiplied alpha BGRA buffers from numpy. Animates at ~30fps via `SetTimer`.

**Panels (click-activated, one at a time):**
All panels share consistent styling: 14px corner radius, opaque background, header + separator, 20px padding. Screen-adaptive dimensions via `GetSystemMetrics`.

- **Log panel:** Recent transcriptions with timestamps and copy buttons. Persisted to `transcriptions.jsonl`. Mouse wheel scroll via `WH_MOUSE_LL` hook.
- **Model selector:** Cached models load on click. Uncached models require two-click confirmation with progress bar.
- **Settings panel:** Mic selector and Quit button.

**Streaming transcription (opt-in):**
When enabled, silence detection (~0.7s) dispatches audio to `_transcription_worker` via `queue.Queue`. Streaming types raw Whisper text incrementally.

**Threading model:**
- Main thread: Win32 message loop (`GetMessageW`)
- Background daemon: pystray tray icon
- Background daemon: `transcription_worker_loop` — processes queued audio jobs (transcribe + type)
- Temporary daemons: `_wait_for_release()`, model loading
- Streaming worker: `_transcription_worker` (when enabled)

**Text input:** `type_text()` uses `SendInput` with `KEYEVENTF_UNICODE`. No clipboard involved.

## Configuration

Settings persist to `config.json` (gitignored). Transcription runs CPU-only with `int8` compute.

**Persisted:** model name, stream mode, pill position, mic device index, enhancement enabled, enhancement model, workspace override.

**Constants in `config.py`:**
- `MODEL_NAME` — `"base.en"` default
- `SPEECH_MODELS` — curated English catalog: `tiny.en`, `base.en`, `small.en`, `distil-medium.en`, `distil-large-v3.5` (name/tier/size). `AVAILABLE_MODELS` and `MODEL_SIZES_MB` derive from it.
- `ENHANCEMENT_MODEL` — `"qwen3.5:2b"` default; `ENHANCEMENT_MODELS` = `("qwen3.5:2b", "qwen3.5:4b")`
- `SAMPLE_RATE` — 16000 Hz
- `HOTKEY` — Ctrl+Shift+Space (via `WH_KEYBOARD_LL` hook)
- `SILENCE_RMS_THRESHOLD` — `0.015`
- `SILENCE_DURATION` — `0.7s`
- `MIN_CHUNK_DURATION` — `0.5s`

## Prompt Enhancement (optional, off by default)

`src/siqspeak/enhancement/` adds opt-in local rewriting of a spoken request into a structured coding prompt before typing.

- **Raw vs. enhanced:** With the toggle off, the raw Whisper transcript is typed immediately. With it on, the overlay shows an `enhancing` state, a local model rewrites the transcript, then the structured prompt is typed. Enhancement adds latency; it is not instantaneous.
- **Local-only boundary:** `ollama.py` talks to `http://127.0.0.1:11434` only — no configurable remote endpoint. Transcript and prompt text never leave the machine and are never logged.
- **Agent Skill selection without execution:** `skills.py` parses only bounded YAML frontmatter (≤64 KiB reads, name-validated, description-capped) from workspace/user skill dirs to suggest skill names. Skill bodies are never opened or executed; names/descriptions are untrusted catalog data. `disable-model-invocation: true` skills are excluded from automatic candidates but honored when named explicitly.
- **Workspace override:** `workspace.py` resolves a trusted root from the manual override (wins) or by parsing an absolute path out of the foreground-window title and ascending to a Git root. It never scans drives or guesses.
- **Raw fallback:** Disabled toggle, unavailable Ollama, missing model, or a malformed response all fall back to typing the preserved raw transcript. Enhancement is lossless.

Requires [Ollama for Windows](https://ollama.com/download); `setup.bat` optionally pulls `qwen3.5:2b` (~2.7 GB). Enhancement package coverage: `pytest tests/test_skills.py tests/test_ollama.py tests/test_prompt.py tests/test_enhancement_service.py --cov=siqspeak.enhancement`.

## Dependencies

Canonical source: `pyproject.toml`. Legacy `requirements.txt` kept for backward compat.

Runtime: `faster-whisper`, `sounddevice`, `numpy`, `pystray`, `pillow`, `pyperclip`
Dev: `ruff`, `pyright`, `pytest`, `pytest-cov`

## Logging

File-only logging to `dictate.log`. Format: `HH:MM:SS.mmm MESSAGE`. No console output. Log rotates at 5 MB (keeps 3 backups) to prevent unbounded growth.

## Notes

- No admin privileges required
- `WH_MOUSE_LL` hook for scroll requires no special privileges
- Mouse hook callback kept as module-level ref in `win32/hooks.py` to prevent GC
