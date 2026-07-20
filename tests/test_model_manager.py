"""Behavioural tests for the public (token-free) model download manager."""
from __future__ import annotations

import errno

import huggingface_hub
import pytest

from siqspeak.config import AVAILABLE_MODELS
from siqspeak.model import manager
from siqspeak.state import AppState


class _FakeModel:
    def __init__(self, path: str, device: str, compute_type: str) -> None:
        self.path = path
        self.device = device
        self.compute_type = compute_type


@pytest.fixture
def state() -> AppState:
    st = AppState()
    st.model_loading = True  # download launcher sets this; helper clears it
    st.model_loading_name = "base.en"
    st.model_loading_is_download = True
    return st


def test_snapshot_download_is_public_and_token_free(
    state: AppState, monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded: dict[str, object] = {}

    def fake_snapshot(repo_id: str, **kwargs: object) -> str:
        recorded["repo_id"] = repo_id
        recorded["kwargs"] = kwargs
        return r"C:\cache\base.en"

    monkeypatch.setattr(huggingface_hub, "snapshot_download", fake_snapshot)
    monkeypatch.setattr(manager, "WhisperModel", _FakeModel)

    manager._download_and_load(state, "base.en")

    assert recorded["repo_id"] == "Systran/faster-whisper-base.en"
    assert "token" not in recorded["kwargs"]
    assert recorded["kwargs"].get("allow_patterns")


def test_successful_download_loads_model_and_reports_progress(
    state: AppState, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        huggingface_hub, "snapshot_download", lambda repo_id, **kw: r"C:\cache\base.en",
    )
    monkeypatch.setattr(manager, "WhisperModel", _FakeModel)

    manager._download_and_load(state, "base.en")

    assert isinstance(state.model, _FakeModel)
    assert state.loaded_model_name == "base.en"
    assert state.download_progress == 1.0
    assert state.download_error is None
    assert state.model_loading is False


def test_network_failure_maps_to_actionable_error(
    state: AppState, monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"n": 0}

    def boom(repo_id: str, **kw: object) -> str:
        calls["n"] += 1
        raise ConnectionError("name resolution failed")

    monkeypatch.setattr(huggingface_hub, "snapshot_download", boom)
    monkeypatch.setattr(manager, "WhisperModel", _FakeModel)
    monkeypatch.setattr(manager, "_RETRY_BACKOFF_SECONDS", 0)

    manager._download_and_load(state, "base.en")

    assert state.download_error is not None
    assert "network" in state.download_error.lower()
    assert state.model_loading is False
    # A persistent network error is retried up to the cap before giving up.
    assert calls["n"] == manager._MAX_DOWNLOAD_ATTEMPTS


def test_transient_network_error_resumes_and_succeeds(
    state: AppState, monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"n": 0}

    def flaky(repo_id: str, **kw: object) -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            raise ConnectionError("connection reset")
        return r"C:\cache\base.en"

    monkeypatch.setattr(huggingface_hub, "snapshot_download", flaky)
    monkeypatch.setattr(manager, "WhisperModel", _FakeModel)
    monkeypatch.setattr(manager, "_RETRY_BACKOFF_SECONDS", 0)

    manager._download_and_load(state, "base.en")

    assert calls["n"] == 2  # failed once, resumed, then succeeded
    assert isinstance(state.model, _FakeModel)
    assert state.loaded_model_name == "base.en"
    assert state.download_error is None
    assert state.model_loading is False


def test_storage_failure_is_not_retried(
    state: AppState, monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"n": 0}

    def boom(repo_id: str, **kw: object) -> str:
        calls["n"] += 1
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(huggingface_hub, "snapshot_download", boom)
    monkeypatch.setattr(manager, "WhisperModel", _FakeModel)
    monkeypatch.setattr(manager, "_RETRY_BACKOFF_SECONDS", 0)

    manager._download_and_load(state, "base.en")

    assert calls["n"] == 1  # non-transient: no point retrying


def test_storage_failure_maps_to_actionable_error(
    state: AppState, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(repo_id: str, **kw: object) -> str:
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(huggingface_hub, "snapshot_download", boom)
    monkeypatch.setattr(manager, "WhisperModel", _FakeModel)

    manager._download_and_load(state, "base.en")

    assert state.download_error is not None
    assert "space" in state.download_error.lower() or "disk" in state.download_error.lower()
    assert state.model_loading is False


def test_download_never_sets_auth_state(
    state: AppState, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        huggingface_hub, "snapshot_download", lambda repo_id, **kw: r"C:\cache\base.en",
    )
    monkeypatch.setattr(manager, "WhisperModel", _FakeModel)

    manager._download_and_load(state, "base.en")

    assert not hasattr(state, "needs_hf_auth")
    assert not hasattr(state, "hf_pending_model")


@pytest.mark.parametrize("name", list(AVAILABLE_MODELS))
def test_cache_detection_for_each_curated_identifier(
    name: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        huggingface_hub, "try_to_load_from_cache", lambda repo_id, filename: r"C:\cache\model.bin",
    )
    assert manager._is_model_cached(name) is True

    monkeypatch.setattr(
        huggingface_hub, "try_to_load_from_cache", lambda repo_id, filename: None,
    )
    assert manager._is_model_cached(name) is False
