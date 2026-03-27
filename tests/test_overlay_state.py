"""Tests for overlay state transition architecture (two-window + PostThreadMessageW)."""
from __future__ import annotations

import pytest

from siqspeak.config import STATE_CODE, STATE_NAME, WM_APP_STATE
from siqspeak.state import AppState


# ---------------------------------------------------------------------------
# Config constants
# ---------------------------------------------------------------------------

def test_state_code_roundtrip():
    """STATE_CODE and STATE_NAME are inverse mappings."""
    for name, code in STATE_CODE.items():
        assert STATE_NAME[code] == name


def test_state_code_covers_all_states():
    expected = {"idle", "recording", "transcribing"}
    assert set(STATE_CODE.keys()) == expected
    assert set(STATE_NAME.values()) == expected


def test_wm_app_state_is_in_app_range():
    """WM_APP range is 0x8000–0xBFFF; our custom message must be in range."""
    assert 0x8000 <= WM_APP_STATE <= 0xBFFF


# ---------------------------------------------------------------------------
# AppState new fields
# ---------------------------------------------------------------------------

def test_state_has_overlay_fields():
    s = AppState()
    assert s.idle_overlay_hwnd is None
    assert s.active_overlay_hwnd is None
    assert s.overlay_hwnd is None
    assert s._main_thread_id == 0


def test_state_no_overlay_target_state():
    """overlay_target_state was removed — ensure it no longer exists."""
    s = AppState()
    assert not hasattr(s, "overlay_target_state")


def test_state_no_recording_start_time():
    """recording_start_time was removed (unused field)."""
    s = AppState()
    assert not hasattr(s, "recording_start_time")


# ---------------------------------------------------------------------------
# _set_pill_mode guards (no Win32 calls — tests early returns only)
# ---------------------------------------------------------------------------

def test_set_pill_mode_noop_same_mode():
    """_set_pill_mode returns immediately if mode hasn't changed."""
    from siqspeak.overlay.pill import _set_pill_mode

    s = AppState()
    s.pill_current_mode = "idle"
    # No HWNDs — would crash on Win32 calls if not early-returned
    _set_pill_mode(s, "idle")
    assert s.pill_current_mode == "idle"


def test_set_pill_mode_noop_no_hwnds():
    """_set_pill_mode returns if overlay HWNDs are not set."""
    from siqspeak.overlay.pill import _set_pill_mode

    s = AppState()
    s.pill_current_mode = "idle"
    s.idle_overlay_hwnd = None
    s.active_overlay_hwnd = None
    _set_pill_mode(s, "active")
    # Should not crash; mode should not change since guard returns early
    assert s.pill_current_mode == "idle"


# ---------------------------------------------------------------------------
# set_state guard (no message loop)
# ---------------------------------------------------------------------------

def test_set_state_guard_no_thread_id(caplog):
    """set_state logs warning and returns when _main_thread_id is 0."""
    from siqspeak.tray import set_state

    s = AppState()
    s._main_thread_id = 0
    with caplog.at_level("WARNING"):
        set_state(s, "recording")
    assert "before message loop started" in caplog.text
