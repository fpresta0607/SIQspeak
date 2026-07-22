"""Tests for settings-panel layout, hit-testing, and rendering.

These are pure, Win32-free checks: y-to-action hit testing, small display
helpers, and premultiplied-BGRA render smoke tests across enhancement states.
"""
from __future__ import annotations

import numpy as np
import pytest

from siqspeak.overlay.panels.settings_panel import (
    SettingsAction,
    _mode_display,
    _model_requirement_label,
    _model_state_display,
    _render_settings_panel,
    _settings_layout,
    _settings_panel_height,
    _settings_render_signature,
    _status_display,
    _workspace_display,
    settings_action_at_y,
)
from siqspeak.state import AppState


def test_action_enum_has_stable_string_values() -> None:
    assert SettingsAction.MICROPHONE == "microphone"
    assert SettingsAction.MODE == "mode"
    assert SettingsAction.WORKSPACE == "workspace"
    assert SettingsAction.ENHANCER_MODEL == "enhancer_model"
    assert SettingsAction.INSTALL_MODEL == "install_model"
    assert SettingsAction.QUIT == "quit"


def test_default_mode_layout_hides_model_rows_and_maps_each_action() -> None:
    state = AppState()  # default mode: no local model needed
    rows = _settings_layout(state)

    assert [row.action for row in rows] == [
        SettingsAction.MICROPHONE,
        SettingsAction.MODE,
        SettingsAction.WORKSPACE,
        SettingsAction.QUIT,
    ]
    for row in rows:
        assert settings_action_at_y(state, row.y + 1) == row.action


@pytest.mark.parametrize("mode", ["code", "email"])
def test_active_mode_layout_shows_model_rows_and_maps_each_action(mode: str) -> None:
    state = AppState()
    state.enhancement_mode = mode
    rows = _settings_layout(state)

    assert [row.action for row in rows] == [
        SettingsAction.MICROPHONE,
        SettingsAction.MODE,
        SettingsAction.WORKSPACE,
        SettingsAction.ENHANCER_MODEL,
        SettingsAction.INSTALL_MODEL,
        SettingsAction.QUIT,
    ]
    for row in rows:
        assert settings_action_at_y(state, row.y + 1) == row.action


@pytest.mark.parametrize(
    ("mode", "label", "description_fragment"),
    [
        ("default", "Default", "raw transcript"),
        ("code", "Code", "coding brief"),
        ("email", "Email", "polished email"),
    ],
)
def test_mode_display_reflects_active_mode(
    mode: str, label: str, description_fragment: str,
) -> None:
    state = AppState()
    state.enhancement_mode = mode

    displayed_label, description = _mode_display(state)

    assert displayed_label == label
    assert description_fragment in description


def test_render_signature_changes_when_enhancement_mode_changes() -> None:
    state = AppState()
    before = _settings_render_signature(state)

    state.enhancement_mode = "code"

    assert _settings_render_signature(state) != before


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
    assert path.startswith("Not detected yet")
    assert "focused window" in path


def test_render_signature_changes_when_detected_workspace_changes() -> None:
    state = AppState()
    before = _settings_render_signature(state)

    state.workspace_detected_root = r"C:\dev\repo"

    assert _settings_render_signature(state) != before


def test_render_signature_changes_when_workspace_override_changes() -> None:
    state = AppState()
    before = _settings_render_signature(state)

    state.workspace_override = r"C:\dev\manual"

    assert _settings_render_signature(state) != before


def test_render_signature_changes_when_enhancement_model_changes() -> None:
    state = AppState()
    before = _settings_render_signature(state)

    state.enhancement_model = "qwen3.5:9b"

    assert _settings_render_signature(state) != before


def test_model_requirement_label_reflects_selected_model() -> None:
    state = AppState()
    state.enhancement_model = "qwen3.5:9b"

    label = _model_requirement_label(state)

    assert "qwen3.5:9b" in label
    assert "Best" in label
    assert "6.6 GB" in label
    assert "needs ~10 GB" in label


def test_model_state_display_ready_vs_download() -> None:
    state = AppState()
    state.enhancement_status = "ready"
    label, color = _model_state_display(state)
    assert label == "Ready"
    assert color == (40, 220, 80)

    state.enhancement_status = "model_missing"
    label, _color = _model_state_display(state)
    assert label == "Download"


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
        lambda s: setattr(s, "enhancement_mode", "code"),
        lambda s: setattr(s, "enhancement_mode", "email"),
        lambda s: setattr(s, "enhancement_mode", "default"),
        lambda s: setattr(s, "enhancement_status", "ollama_missing"),
        lambda s: setattr(s, "enhancement_status", "model_missing"),
        lambda s: (
            setattr(s, "enhancement_status", "pulling"),
            setattr(s, "enhancement_pull_progress", 0.6),
        ),
        lambda s: setattr(s, "enhancement_hardware", "31.7 GB RAM, 8.0 GB GPU"),
        lambda s: setattr(s, "workspace_detected_root", r"C:\dev\repo"),
        lambda s: setattr(s, "workspace_override", r"C:\dev\manual"),
        lambda s: setattr(s, "enhancement_model", "qwen3.5:2b"),
        lambda s: setattr(s, "enhancement_model", "qwen3.5:9b"),
        lambda s: (
            setattr(s, "enhancement_model", "qwen3.5:9b"),
            setattr(s, "enhancement_status", "ready"),
        ),
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
    busy.enhancement_mode = "code"
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
