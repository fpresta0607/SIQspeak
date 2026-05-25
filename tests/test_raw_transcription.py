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
