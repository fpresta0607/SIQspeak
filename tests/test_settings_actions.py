"""Tests for settings click-action helpers and the native folder-dialog guard.

The folder dialog is exercised through its injectable seams so no real Windows
dialog opens and no working directory is changed. Click helpers are pure state
mutations validated against persisted config.
"""
from __future__ import annotations

import pytest

from siqspeak.app import _should_resolve
from siqspeak.config import _load_config
from siqspeak.interaction import click_handlers
from siqspeak.interaction.click_handlers import (
    _apply_enhancement_toggle,
    _apply_workspace_selection,
    _install_model_action,
)
from siqspeak.state import AppState
from siqspeak.win32 import folder_dialog


@pytest.mark.parametrize(
    ("last_external", "last_resolved", "expected"),
    [
        (None, None, False),        # nothing focused yet
        (100, None, True),          # first focus -> resolve once
        (100, 100, False),          # same window -> skip
        (200, 100, True),           # switched window -> resolve again
        (None, 100, False),         # lost focus, keep last resolve sticky
    ],
)
def test_should_resolve_only_on_window_change(
    last_external: int | None, last_resolved: int | None, expected: bool,
) -> None:
    assert _should_resolve(last_external, last_resolved) is expected


@pytest.fixture
def _cfg(tmp_path, monkeypatch):
    monkeypatch.setattr("siqspeak.config.CONFIG_PATH", str(tmp_path / "config.json"))
    return tmp_path


def test_toggle_enhancement_flips_and_persists(_cfg) -> None:
    state = AppState()
    assert state.enhancement_enabled is False

    _apply_enhancement_toggle(state)

    assert state.enhancement_enabled is True
    assert _load_config()["enhancement_enabled"] is True

    _apply_enhancement_toggle(state)
    assert state.enhancement_enabled is False


def test_workspace_selection_persists_valid_folder(_cfg) -> None:
    state = AppState()

    changed = _apply_workspace_selection(state, r"C:\dev\project")

    assert changed is True
    assert state.workspace_override == r"C:\dev\project"
    assert _load_config()["workspace_override"] == r"C:\dev\project"


def test_workspace_selection_ignores_cancelled_pick(_cfg) -> None:
    state = AppState()
    state.workspace_override = r"C:\existing"

    changed = _apply_workspace_selection(state, None)

    assert changed is False
    assert state.workspace_override == r"C:\existing"


def test_install_action_opens_download_when_ollama_missing(monkeypatch) -> None:
    state = AppState()
    state.enhancement_status = "ollama_missing"
    events: list[object] = []
    monkeypatch.setattr(click_handlers, "_open_ollama_download", lambda: events.append("open"))
    monkeypatch.setattr(click_handlers, "_start_model_pull", lambda s: events.append("pull"))

    _install_model_action(state)

    assert events == ["open"]


def test_install_action_starts_pull_when_model_missing(monkeypatch) -> None:
    state = AppState()
    state.enhancement_status = "model_missing"
    events: list[object] = []
    monkeypatch.setattr(click_handlers, "_start_model_pull", lambda s: events.append(s))
    monkeypatch.setattr(click_handlers, "_open_ollama_download", lambda: events.append("open"))
    monkeypatch.setattr(click_handlers, "can_run_model", lambda _min_gb: (True, "31.7 GB RAM, 8.0 GB GPU"))

    _install_model_action(state)

    assert events == [state]


def test_install_action_blocks_pull_when_hardware_insufficient(monkeypatch) -> None:
    state = AppState()
    state.enhancement_status = "model_missing"
    events: list[object] = []
    monkeypatch.setattr(click_handlers, "_start_model_pull", lambda s: events.append("pull"))
    monkeypatch.setattr(click_handlers, "can_run_model", lambda _min_gb: (False, "2.0 GB RAM"))

    _install_model_action(state)

    assert events == []
    assert state.enhancement_status == "error"
    assert state.enhancement_error is not None
    assert "2.0 GB RAM" in state.enhancement_error


def test_install_action_is_noop_when_ready(monkeypatch) -> None:
    state = AppState()
    state.enhancement_status = "ready"
    events: list[object] = []
    monkeypatch.setattr(click_handlers, "_start_model_pull", lambda s: events.append("pull"))
    monkeypatch.setattr(click_handlers, "_open_ollama_download", lambda: events.append("open"))

    _install_model_action(state)

    assert events == []


# --- Native folder dialog: guarded seams, never opens a real dialog ---


def test_select_folder_returns_none_on_cancel(monkeypatch) -> None:
    freed: list[int] = []
    monkeypatch.setattr(folder_dialog, "_browse_for_folder", lambda title, hwnd: 0)
    monkeypatch.setattr(
        folder_dialog, "_path_from_pidl",
        lambda pidl: pytest.fail("must not resolve a null item id"),
    )
    monkeypatch.setattr(folder_dialog, "_co_task_mem_free", lambda pidl: freed.append(pidl))

    assert folder_dialog.select_folder() is None
    assert freed == []


def test_select_folder_returns_path_and_frees_item_id(monkeypatch) -> None:
    freed: list[int] = []
    monkeypatch.setattr(folder_dialog, "_browse_for_folder", lambda title, hwnd: 4242)
    monkeypatch.setattr(folder_dialog, "_path_from_pidl", lambda pidl: r"C:\dev\chosen")
    monkeypatch.setattr(folder_dialog, "_co_task_mem_free", lambda pidl: freed.append(pidl))

    assert folder_dialog.select_folder() == r"C:\dev\chosen"
    assert freed == [4242]


def test_select_folder_frees_item_id_even_when_path_missing(monkeypatch) -> None:
    freed: list[int] = []
    monkeypatch.setattr(folder_dialog, "_browse_for_folder", lambda title, hwnd: 99)
    monkeypatch.setattr(folder_dialog, "_path_from_pidl", lambda pidl: None)
    monkeypatch.setattr(folder_dialog, "_co_task_mem_free", lambda pidl: freed.append(pidl))

    assert folder_dialog.select_folder() is None
    assert freed == [99]
