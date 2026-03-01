"""Tests for AppState dataclass."""
from __future__ import annotations

from siqspeak.state import AppState


def test_default_values():
    s = AppState()
    assert s.is_recording is False
    assert s.device == "cpu"
    assert s.compute_type == "int8"
    assert s.loaded_model_name == "tiny"
    assert s.stream_mode is False
    assert s.active_panel is None
    assert s.hover_zone is None
    assert s.should_quit is False


def test_state_is_mutable():
    s = AppState()
    s.is_recording = True
    s.loaded_model_name = "base"
    s.transcription_log.append({"text": "hello"})
    assert s.is_recording is True
    assert s.loaded_model_name == "base"
    assert len(s.transcription_log) == 1


def test_independent_instances():
    a = AppState()
    b = AppState()
    a.transcription_log.append({"text": "test"})
    assert len(b.transcription_log) == 0
