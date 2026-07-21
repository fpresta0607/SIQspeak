"""Tests for config load/save."""
from __future__ import annotations

from pathlib import Path

import pytest

from siqspeak.config import (
    ENHANCEMENT_MODEL,
    ENHANCEMENT_MODELS,
    MODEL_NAME,
    SPEECH_MODELS,
    _load_config,
    enhancement_model_spec,
    resolve_enhancement_model,
    save_config,
    save_state_config,
)
from siqspeak.state import AppState


def test_new_install_defaults_to_base_english() -> None:
    assert MODEL_NAME == "base.en"


def test_speech_model_catalog_is_curated() -> None:
    assert [item["name"] for item in SPEECH_MODELS] == [
        "tiny.en",
        "base.en",
        "small.en",
        "distil-medium.en",
        "distil-large-v3.5",
    ]
    assert SPEECH_MODELS[1]["tier"] == "Default"


def test_save_state_config_persists_enhancement_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("siqspeak.config.CONFIG_PATH", str(tmp_path / "config.json"))
    state = AppState()
    state.enhancement_enabled = True
    state.workspace_override = r"C:\dev\project"

    save_state_config(state)

    assert _load_config()["enhancement_model"] == ENHANCEMENT_MODEL
    assert _load_config()["enhancement_enabled"] is True
    assert _load_config()["workspace_override"] == r"C:\dev\project"


def test_enhancement_catalog_shape_and_order() -> None:
    assert [item["name"] for item in ENHANCEMENT_MODELS] == [
        "qwen3.5:2b",
        "qwen3.5:4b",
        "qwen3.5:9b",
    ]
    for spec in ENHANCEMENT_MODELS:
        assert set(spec) == {"name", "tier", "download_gb", "min_gb"}
    assert ENHANCEMENT_MODEL == "qwen3.5:4b"


def test_enhancement_model_spec_falls_back_to_default_for_unknown() -> None:
    assert enhancement_model_spec("qwen3.5:9b")["min_gb"] == 10.0
    assert enhancement_model_spec("bogus:99b")["name"] == ENHANCEMENT_MODEL


def test_persisted_valid_model_is_honored_invalid_falls_back() -> None:
    # The persisted selection is now authoritative when it is a real catalog
    # model; an unknown/stale name falls back to the default.
    assert resolve_enhancement_model("qwen3.5:2b") == "qwen3.5:2b"
    assert resolve_enhancement_model("qwen3.5:9b") == "qwen3.5:9b"
    assert resolve_enhancement_model("old-model:1b") == ENHANCEMENT_MODEL
    assert resolve_enhancement_model(None) == ENHANCEMENT_MODEL


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
        "enhancement_enabled": False,
        "enhancement_model": "qwen3.5:4b",
        "workspace_override": None,
    }
