"""Tests for settings-panel layout, hit-testing, and rendering.

These are pure, Win32-free checks: y-to-action hit testing, small display
helpers, and premultiplied-BGRA render smoke tests across enhancement states.
"""
from __future__ import annotations

import numpy as np
import pytest

from siqspeak.overlay.panels.settings_panel import (
    SettingsAction,
    _model_short_label,
    _render_settings_panel,
    _settings_layout,
    _settings_panel_height,
    _status_display,
    _workspace_display,
    settings_action_at_y,
)
from siqspeak.state import AppState


def test_action_enum_has_stable_string_values() -> None:
    assert SettingsAction.MICROPHONE == "microphone"
    assert SettingsAction.ENHANCEMENT_TOGGLE == "enhancement_toggle"
    assert SettingsAction.WORKSPACE == "workspace"
    assert SettingsAction.ENHANCER_MODEL == "enhancer_model"
    assert SettingsAction.INSTALL_MODEL == "install_model"
    assert SettingsAction.QUIT == "quit"


def test_layout_orders_rows_and_maps_each_to_its_action() -> None:
    state = AppState()
    rows = _settings_layout(state)

    assert [row.action for row in rows] == [
        SettingsAction.MICROPHONE,
        SettingsAction.ENHANCEMENT_TOGGLE,
        SettingsAction.WORKSPACE,
        SettingsAction.ENHANCER_MODEL,
        SettingsAction.INSTALL_MODEL,
        SettingsAction.QUIT,
    ]
    for row in rows:
        assert settings_action_at_y(state, row.y + 1) == row.action


def test_action_at_y_within_header_is_none() -> None:
    state = AppState()
    assert settings_action_at_y(state, 4) is None


def test_action_at_y_below_last_row_is_none() -> None:
    state = AppState()
    assert settings_action_at_y(state, _settings_panel_height(state) + 40) is None


def test_expanded_microphone_band_covers_device_rows() -> None:
    state = AppState()
    state.mic_expanded = True
    state.mic_devices = [
        {"index": 0, "name": "Mic A"},
        {"index": 1, "name": "Mic B"},
    ]
    rows = _settings_layout(state)
    mic_row = rows[0]

    inside_device_list = mic_row.y + mic_row.height - 4
    assert settings_action_at_y(state, inside_device_list) == SettingsAction.MICROPHONE
    # Rows below shift down to make room for the expansion.
    assert rows[1].y >= mic_row.y + mic_row.height


def test_model_short_label_derives_size_suffix() -> None:
    assert _model_short_label("qwen3.5:2b") == "2b"
    assert _model_short_label("qwen3.5:4b") == "4b"
    assert _model_short_label("plainname") == "plainname"


def test_workspace_display_manual_override_wins() -> None:
    state = AppState()
    state.workspace_override = r"C:\dev\project"
    state.workspace_detected_root = r"C:\other"

    status, path = _workspace_display(state)

    assert status == "Manual"
    assert path == r"C:\dev\project"


def test_workspace_display_auto_when_only_detected() -> None:
    state = AppState()
    state.workspace_detected_root = r"C:\dev\repo"

    status, path = _workspace_display(state)

    assert status == "Auto"
    assert path == r"C:\dev\repo"


def test_workspace_display_not_detected() -> None:
    status, path = _workspace_display(AppState())
    assert status == "Auto"
    assert path == "Not detected"


@pytest.mark.parametrize(
    ("status", "expected_action"),
    [
        ("ollama_missing", "Get Ollama"),
        ("model_missing", "Download"),
        ("ready", None),
        (None, None),
    ],
)
def test_status_display_action_label(status: str | None, expected_action: str | None) -> None:
    state = AppState()
    state.enhancement_status = status
    _message, action = _status_display(state)
    assert action == expected_action


def test_status_display_pull_progress_shows_percentage() -> None:
    state = AppState()
    state.enhancement_status = "pulling"
    state.enhancement_pull_progress = 0.42

    message, action = _status_display(state)

    assert "42" in message
    assert action is None


def _assert_premultiplied_bgra(buf: np.ndarray, width: int, height: int) -> None:
    assert buf.dtype == np.uint8
    assert buf.shape == (height, width, 4)
    alpha = buf[:, :, 3].astype(int)
    assert (buf[:, :, 0] <= alpha + 1).all()
    assert (buf[:, :, 1] <= alpha + 1).all()
    assert (buf[:, :, 2] <= alpha + 1).all()


@pytest.mark.parametrize(
    "mutate",
    [
        lambda s: setattr(s, "enhancement_enabled", True),
        lambda s: setattr(s, "enhancement_enabled", False),
        lambda s: setattr(s, "enhancement_status", "ollama_missing"),
        lambda s: setattr(s, "enhancement_status", "model_missing"),
        lambda s: (
            setattr(s, "enhancement_status", "pulling"),
            setattr(s, "enhancement_pull_progress", 0.6),
        ),
        lambda s: setattr(s, "enhancement_model", "qwen3.5:2b"),
        lambda s: setattr(s, "enhancement_model", "qwen3.5:4b"),
        lambda s: setattr(s, "workspace_detected_root", r"C:\dev\repo"),
        lambda s: setattr(s, "workspace_override", r"C:\dev\manual"),
    ],
)
def test_render_states_produce_valid_premultiplied_bgra(mutate) -> None:
    state = AppState()
    mutate(state)

    buf, width, height = _render_settings_panel(state)

    _assert_premultiplied_bgra(buf, width, height)
    assert height == _settings_panel_height(state)


def test_render_width_is_stable_across_states() -> None:
    plain = AppState()
    busy = AppState()
    busy.enhancement_enabled = True
    busy.enhancement_status = "pulling"

    _buf_a, width_a, _h_a = _render_settings_panel(plain)
    _buf_b, width_b, _h_b = _render_settings_panel(busy)

    assert width_a == width_b


def test_expanded_microphone_grows_panel_height() -> None:
    collapsed = AppState()
    collapsed.mic_devices = [{"index": 0, "name": "Mic A"}]
    expanded = AppState()
    expanded.mic_devices = [{"index": 0, "name": "Mic A"}]
    expanded.mic_expanded = True

    assert _settings_panel_height(expanded) > _settings_panel_height(collapsed)
