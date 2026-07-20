"""Tests for the enhanced transcription path (opt-in local prompt enhancement)."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from siqspeak.audio import recording
from siqspeak.enhancement.prompt import EnhancementResult
from siqspeak.state import AppState


@dataclass
class _Segment:
    text: str


class _FakeModel:
    def __init__(self, text: str) -> None:
        self._text = text

    def transcribe(self, audio: np.ndarray, **kwargs):
        return [_Segment(self._text)], None


def _instrument(monkeypatch) -> list[tuple]:
    """Record ordered side effects (state changes, focus, typing)."""
    events: list[tuple] = []
    monkeypatch.setattr(recording, "_save_log_entry", lambda _state, _entry: None)
    monkeypatch.setattr(recording, "set_state", lambda _state, name: events.append(("state", name)))
    monkeypatch.setattr(recording, "focus_window", lambda hwnd: events.append(("focus", hwnd)))
    monkeypatch.setattr(recording, "type_text", lambda text: events.append(("type", text)))
    monkeypatch.setattr(recording.time, "sleep", lambda *_a, **_k: None)
    # Resolve the target window's title deterministically from its handle.
    monkeypatch.setattr(recording, "window_title", lambda hwnd: f"title#{hwnd}")
    return events


def test_enhancing_state_precedes_typing(monkeypatch) -> None:
    events = _instrument(monkeypatch)
    state = AppState()
    state.model = _FakeModel("raw words")
    state.enhancement_enabled = True
    state.enhance_prompt = lambda raw, title, hwnd: EnhancementResult(
        raw, "FINAL " + raw, ("systematic-debugging",), True,
    )

    recording._transcribe_and_type(state, np.zeros(16000, dtype=np.float32), target_hwnd=123)

    kinds = [e[0] for e in events]
    assert ("state", "enhancing") in events
    assert kinds.index("state") < kinds.index("type")


def test_successful_enhancement_types_final_text(monkeypatch) -> None:
    events = _instrument(monkeypatch)
    state = AppState()
    state.model = _FakeModel("raw words")
    state.enhancement_enabled = True
    state.enhance_prompt = lambda raw, title, hwnd: EnhancementResult(
        raw, "FINAL " + raw, ("systematic-debugging",), True,
    )

    recording._transcribe_and_type(state, np.zeros(16000, dtype=np.float32), target_hwnd=123)

    assert ("type", "FINAL raw words") in events
    entry = state.transcription_log[-1]
    assert entry["text"] == "FINAL raw words"
    assert entry["raw_text"] == "raw words"
    assert entry["enhanced"] is True


def test_enhancer_receives_target_window_title_and_hwnd(monkeypatch) -> None:
    _instrument(monkeypatch)
    seen: list[tuple[str, int | None]] = []
    state = AppState()
    state.model = _FakeModel("raw words")
    state.enhancement_enabled = True

    def _enhance(raw: str, title: str, hwnd: int | None) -> EnhancementResult:
        seen.append((title, hwnd))
        return EnhancementResult(raw, "FINAL", (), True)

    state.enhance_prompt = _enhance

    recording._transcribe_and_type(state, np.zeros(16000, dtype=np.float32), target_hwnd=456)

    # The window the user dictated into (target_hwnd), not the live foreground —
    # its title and its raw handle (for terminal-CWD detection) are both passed.
    assert seen == [("title#456", 456)]


def test_failed_enhancement_types_raw_text(monkeypatch) -> None:
    events = _instrument(monkeypatch)
    state = AppState()
    state.model = _FakeModel("raw words")
    state.enhancement_enabled = True
    state.enhance_prompt = lambda raw, title, hwnd: EnhancementResult(raw, raw, (), False, "enhancement_failed")

    recording._transcribe_and_type(state, np.zeros(16000, dtype=np.float32), target_hwnd=55)

    assert ("type", "raw words") in events
    entry = state.transcription_log[-1]
    assert entry["text"] == "raw words"
    assert entry["raw_text"] == "raw words"
    assert entry["enhanced"] is False


def test_focus_restoration_uses_original_target(monkeypatch) -> None:
    events = _instrument(monkeypatch)
    state = AppState()
    state.model = _FakeModel("raw words")
    state.enhancement_enabled = True
    state.enhance_prompt = lambda raw, title, hwnd: EnhancementResult(raw, "FINAL", (), True)

    recording._transcribe_and_type(state, np.zeros(16000, dtype=np.float32), target_hwnd=999)

    assert ("focus", 999) in events


def test_window_title_failure_still_logs_and_types(monkeypatch) -> None:
    # A window_title() failure must not sink the block: the raw transcript is
    # still enhanced (with an empty title), logged, and typed.
    events = _instrument(monkeypatch)

    def _boom(_hwnd):
        raise RuntimeError("GetWindowTextW failed")

    monkeypatch.setattr(recording, "window_title", _boom)
    seen_titles: list[str] = []
    state = AppState()
    state.model = _FakeModel("raw words")
    state.enhancement_enabled = True

    def _enhance(raw: str, title: str, hwnd: int | None) -> EnhancementResult:
        seen_titles.append(title)
        return EnhancementResult(raw, "FINAL " + raw, (), True)

    state.enhance_prompt = _enhance

    recording._transcribe_and_type(state, np.zeros(16000, dtype=np.float32), target_hwnd=321)

    # Title resolution failed -> empty string handed to the enhancer.
    assert seen_titles == [""]
    assert ("type", "FINAL raw words") in events
    assert state.transcription_log[-1]["raw_text"] == "raw words"


def test_new_recording_suppresses_typing(monkeypatch) -> None:
    events = _instrument(monkeypatch)
    state = AppState()
    state.model = _FakeModel("raw words")
    state.enhancement_enabled = True
    state.is_recording = True  # a new recording started while we transcribed
    state.enhance_prompt = lambda raw, title, hwnd: EnhancementResult(raw, "FINAL", (), True)

    recording._transcribe_and_type(state, np.zeros(16000, dtype=np.float32), target_hwnd=77)

    assert not any(e[0] == "type" for e in events)
    # enhancement still ran and the log still stores the final text
    assert state.transcription_log[-1]["text"] == "FINAL"
