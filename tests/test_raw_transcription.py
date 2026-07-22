"""Tests for the raw transcription path."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from siqspeak.audio import recording
from siqspeak.state import AppState


@dataclass
class _Segment:
    text: str


class _FakeModel:
    def __init__(self, text: str) -> None:
        self._text = text
        self.kwargs: dict = {}

    def transcribe(self, audio: np.ndarray, **kwargs):
        self.kwargs = kwargs
        return [_Segment(self._text)], None


def test_transcription_log_keeps_raw_whisper_text(monkeypatch) -> None:
    raw_text = "open paren hello close paren"
    state = AppState()
    state.model = _FakeModel(raw_text)
    saved_entries: list[dict] = []
    monkeypatch.setattr(recording, "_save_log_entry", lambda _state, entry: saved_entries.append(entry))

    recording._transcribe_and_type(state, np.zeros(16000, dtype=np.float32), target_hwnd=None)

    assert state.transcription_log[-1]["text"] == raw_text
    assert saved_entries[-1]["text"] == raw_text
    assert state.model.kwargs["beam_size"] == 1
    assert state.model.kwargs["without_timestamps"] is True
    assert state.model.kwargs["condition_on_previous_text"] is False


def test_enhancer_not_called_in_default_mode(monkeypatch) -> None:
    raw_text = "please refactor the parser"
    state = AppState()
    state.model = _FakeModel(raw_text)
    state.enhancement_mode = "default"
    called = False

    def _spy(_raw: str, _title: str, _hwnd: int | None):
        nonlocal called
        called = True
        raise AssertionError("enhancer must not run in default mode")

    state.enhance_prompt = _spy
    monkeypatch.setattr(recording, "_save_log_entry", lambda _state, _entry: None)

    recording._transcribe_and_type(state, np.zeros(16000, dtype=np.float32), target_hwnd=None)

    assert called is False
    entry = state.transcription_log[-1]
    assert entry["text"] == raw_text
    assert entry["raw_text"] == raw_text
    assert entry["enhanced"] is False
