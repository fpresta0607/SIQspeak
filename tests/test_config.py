"""Tests for config load/save."""
from __future__ import annotations

from siqspeak.config import _load_config, save_config, save_state_config
from siqspeak.state import AppState


def test_load_config_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr("siqspeak.config.CONFIG_PATH", str(tmp_path / "nonexistent.json"))
    result = _load_config()
    assert result == {}


def test_load_config_corrupt_json(tmp_path, monkeypatch):
    bad_file = tmp_path / "config.json"
    bad_file.write_text("not valid json {{{")
    monkeypatch.setattr("siqspeak.config.CONFIG_PATH", str(bad_file))
    result = _load_config()
    assert result == {}


def test_save_and_load_round_trip(tmp_path, monkeypatch):
    config_file = str(tmp_path / "config.json")
    monkeypatch.setattr("siqspeak.config.CONFIG_PATH", config_file)

    values = {"model": "base", "stream_mode": True, "device": "cpu"}
    save_config(values)

    result = _load_config()
    assert result["model"] == "base"
    assert result["stream_mode"] is True
    assert result["device"] == "cpu"


def test_save_state_config_does_not_persist_device(tmp_path, monkeypatch):
    config_file = str(tmp_path / "config.json")
    monkeypatch.setattr("siqspeak.config.CONFIG_PATH", config_file)

    state = AppState()
    state.loaded_model_name = "base"
    state.stream_mode = True
    state.pill_user_x = 100
    state.pill_user_y = 200
    state.device = "cuda"
    state.mic_device = 3

    save_state_config(state)

    result = _load_config()
    assert result == {
        "model": "base",
        "stream_mode": True,
        "pill_x": 100,
        "pill_y": 200,
        "mic_device": 3,
    }
