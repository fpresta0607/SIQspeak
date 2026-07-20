"""Tests for stable, hover-free history-card layout and rendering."""
from __future__ import annotations

import time

import numpy as np

from siqspeak.config import _log_panel_dims
from siqspeak.overlay.panels import log_panel
from siqspeak.overlay.panels.log_panel import _layout_cards, _render_log_panel
from siqspeak.state import AppState


def _entry(
    text: str, *, enhanced: bool = False, ts: str = "12:00:00",
    epoch: float | None = None, **extra: object,
) -> dict:
    entry: dict = {
        "text": text,
        "timestamp": ts,
        "time_epoch": time.time() if epoch is None else epoch,
    }
    if enhanced:
        entry["enhanced"] = True
    entry.update(extra)
    return entry


def test_every_real_entry_has_a_visible_copy_control() -> None:
    state = AppState()
    state.transcription_log = [_entry("hello world"), _entry("second entry")]
    panel_w, max_h = _log_panel_dims()

    cards, is_empty = _layout_cards(state, panel_w, max_h, time.time())

    assert not is_empty
    assert cards
    assert all(card.show_copy for card in cards)


def test_enhanced_badge_only_for_enhanced_entries() -> None:
    state = AppState()
    state.transcription_log = [_entry("raw only"), _entry("fixed grammar", enhanced=True)]
    panel_w, max_h = _log_panel_dims()

    cards, _ = _layout_cards(state, panel_w, max_h, time.time())

    badge_by_text = {card.entry["text"]: card.show_badge for card in cards}
    assert badge_by_text["fixed grammar"] is True
    assert badge_by_text["raw only"] is False


def test_legacy_entry_without_raw_text_or_enhanced() -> None:
    state = AppState()
    state.transcription_log = [
        {"text": "old entry", "timestamp": "09:00:00", "time_epoch": time.time()},
    ]
    panel_w, max_h = _log_panel_dims()

    cards, _ = _layout_cards(state, panel_w, max_h, time.time())

    assert cards[0].show_badge is False
    assert cards[0].show_copy is True
    # Rendering a legacy entry must not raise.
    buf, _, _ = _render_log_panel(state)
    assert buf.dtype == np.uint8


def test_empty_history_shows_placeholder_without_copy() -> None:
    state = AppState()
    panel_w, max_h = _log_panel_dims()

    cards, is_empty = _layout_cards(state, panel_w, max_h, time.time())

    assert is_empty
    assert len(cards) == 1
    assert cards[0].show_copy is False
    assert cards[0].show_badge is False


def test_visible_entries_are_clipped_before_expensive_layout(monkeypatch) -> None:
    state = AppState()
    long_text = "word " * 60
    state.transcription_log = [_entry(long_text) for _ in range(50)]
    panel_w, max_h = _log_panel_dims()

    wrap_calls = 0
    real_wrap = log_panel._wrap_text

    def counting_wrap(*args: object, **kwargs: object) -> list[str]:
        nonlocal wrap_calls
        wrap_calls += 1
        return real_wrap(*args, **kwargs)

    monkeypatch.setattr(log_panel, "_wrap_text", counting_wrap)

    cards, _ = _layout_cards(state, panel_w, max_h, time.time())

    assert len(cards) < 50
    # Only visible cards (plus at most the one that overflows) get wrapped.
    assert wrap_calls <= len(cards) + 1
    assert wrap_calls < 50


def test_copy_confirmation_state_expires() -> None:
    state = AppState()
    state.transcription_log = [_entry("copy me")]
    state.copied_row = 0
    state.copied_time = time.time()
    panel_w, max_h = _log_panel_dims()

    fresh, _ = _layout_cards(state, panel_w, max_h, state.copied_time)
    assert fresh[0].is_copied is True

    stale, _ = _layout_cards(state, panel_w, max_h, state.copied_time + 5.0)
    assert stale[0].is_copied is False


def test_stable_dimensions_and_premultiplied_bgra() -> None:
    state = AppState()
    state.transcription_log = [_entry("consistent output")]

    buf1, w1, h1 = _render_log_panel(state)
    _, w2, h2 = _render_log_panel(state)

    assert (w1, h1) == (w2, h2)
    assert buf1.shape == (h1, w1, 4)
    assert buf1.dtype == np.uint8
    alpha = buf1[:, :, 3].astype(int)
    assert (buf1[:, :, 0] <= alpha + 1).all()
    assert (buf1[:, :, 1] <= alpha + 1).all()
    assert (buf1[:, :, 2] <= alpha + 1).all()
