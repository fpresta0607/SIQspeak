# Contributing to SIQspeak

Thanks for your interest in contributing! This guide covers how to set up a development environment and submit changes.

## Development Setup

```bash
# Clone the repo
git clone https://github.com/fpresta0607/SIQspeak.git
cd SIQspeak

# Create virtual environment and install (editable + dev tools)
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
```

## Running

```bash
# With console (see log output)
python -m siqspeak

# Or use the legacy entry point
python dictate.py
```

Logs are written to `dictate.log` in the project root.

## Project Structure

```
src/siqspeak/
  app.py              # Entry point: main() + message_loop()
  config.py           # Constants, paths, config persistence
  state.py            # AppState dataclass (all mutable state)
  hotkey.py           # Hotkey handler
  tray.py             # System tray icon
  audio/              # Recording, streaming transcription, device enumeration
  model/              # Whisper model loading/downloading
  overlay/            # Pill rendering + panel UI (log, model, settings, welcome)
  interaction/        # Click handlers + hover detection
  win32/              # ctypes wrappers (windows, hooks, text input, DPI)
```

## Code Quality

```bash
# Lint
ruff check .
ruff format --check .

# Type check
pyright

# Test
pytest
```

All three must pass before submitting a PR.

## Branch Naming

- `feat/<name>` — new features
- `fix/<name>` — bug fixes
- `refactor/<name>` — code restructuring

## Commit Messages

Use [conventional commits](https://www.conventionalcommits.org/):

```
feat(audio): add noise gate for streaming mode
fix(overlay): pill position resets on monitor change
refactor(win32): extract DPI helpers into separate module
```

## Pull Requests

1. One logical change per PR
2. Include a description of what changed and why
3. Add tests for new functionality
4. Ensure `ruff check .` and `pytest` pass
5. Update `CLAUDE.md` if architecture changes

## Reporting Issues

Use the GitHub issue templates for bug reports and feature requests. Include:
- Windows version and Python version
- Model size in use
- Relevant `dictate.log` output
