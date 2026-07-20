"""Tests for log-panel pointer interaction after hover removal.

These are pure, Win32-free checks: coordinate-to-row hit testing, scroll-aware
entry selection, and source/behaviour guards proving pointer movement no longer
drives a history render.
"""
from __future__ import annotations

from pathlib import Path

from siqspeak.config import LOG_CARD_MARGIN_X, LOG_HEADER_H, LOG_PANEL_PADDING
from siqspeak.interaction.hover import _copy_row_at_position
from siqspeak.overlay.panels.log_panel import _visible_entries
from siqspeak.state import AppState

ROOT = Path(__file__).resolve().parent.parent


def test_pointer_hover_does_not_trigger_history_render() -> None:
    app_source = (ROOT / "src/siqspeak/app.py").read_text(encoding="utf-8")
    assert "_update_copy_hover" not in app_source
    assert "copy_hover_row" not in app_source


def test_update_copy_hover_helper_is_removed() -> None:
    import siqspeak.interaction.hover as hover

    assert not hasattr(hover, "_update_copy_hover")


def test_copy_hover_row_field_is_removed() -> None:
    assert not hasattr(AppState(), "copy_hover_row")


def test_copy_row_hit_test_matches_variable_height_rows() -> None:
    heights = [60, 80, 60]
    panel_w = 600
    x = panel_w - LOG_CARD_MARGIN_X - 6  # inside the copy column
    top = LOG_HEADER_H + LOG_PANEL_PADDING
    assert _copy_row_at_position(x, top + 10, panel_w, heights) == 0
    assert _copy_row_at_position(x, top + 60 + 10, panel_w, heights) == 1
    assert _copy_row_at_position(x, top + 140 + 10, panel_w, heights) == 2


def test_copy_row_hit_test_outside_column_returns_none() -> None:
    heights = [60]
    panel_w = 600
    top = LOG_HEADER_H + LOG_PANEL_PADDING
    assert _copy_row_at_position(100, top + 10, panel_w, heights) is None


def test_copy_row_hit_test_above_first_row_returns_none() -> None:
    heights = [60]
    panel_w = 600
    x = panel_w - LOG_CARD_MARGIN_X - 6
    assert _copy_row_at_position(x, 0, panel_w, heights) is None


def test_copy_row_hit_test_empty_heights_returns_none() -> None:
    assert _copy_row_at_position(590, 200, 600, []) is None


def test_visible_entries_are_newest_first() -> None:
    log = [{"text": f"e{i}"} for i in range(5)]
    visible = _visible_entries(log, 0, 3)
    assert [e["text"] for e in visible] == ["e4", "e3", "e2"]


def test_visible_entries_respects_scroll_offset() -> None:
    log = [{"text": f"e{i}"} for i in range(5)]
    visible = _visible_entries(log, 1, 3)
    assert [e["text"] for e in visible] == ["e3", "e2", "e1"]


def test_visible_entries_empty_history() -> None:
    assert _visible_entries([], 0, 50) == []
