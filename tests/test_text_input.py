"""Tests for the SendInput event builder in ``win32.text_input``.

Exercises ``_build_inputs`` directly (it never touches ``user32``), so multi-line
output can be verified without injecting real keystrokes into the desktop.
"""
from __future__ import annotations

from siqspeak.win32.structs import (
    INPUT_KEYBOARD,
    KEYEVENTF_KEYUP,
    KEYEVENTF_UNICODE,
    VK_RETURN,
)
from siqspeak.win32.text_input import _build_inputs


def test_plain_text_is_unicode_down_up_pairs() -> None:
    inputs = _build_inputs("ab")

    assert len(inputs) == 4  # one down + up pair per char
    down_a, up_a, down_b, _up_b = inputs
    assert down_a.type == INPUT_KEYBOARD
    assert down_a.ki.wScan == ord("a")
    assert down_a.ki.wVk == 0
    assert down_a.ki.dwFlags == KEYEVENTF_UNICODE
    assert up_a.ki.dwFlags == KEYEVENTF_UNICODE | KEYEVENTF_KEYUP
    assert down_b.ki.wScan == ord("b")


def test_newline_is_a_real_enter_keypress_not_unicode() -> None:
    # The core fix: a '\n' must be an Enter (VK_RETURN) keypress. Typed as a
    # Unicode line feed it is ignored by most apps, collapsing multi-line output.
    inputs = _build_inputs("a\nb")

    assert len(inputs) == 6
    nl_down, nl_up = inputs[2], inputs[3]
    assert nl_down.ki.wVk == VK_RETURN
    assert nl_down.ki.dwFlags == 0  # NOT KEYEVENTF_UNICODE
    assert not nl_down.ki.dwFlags & KEYEVENTF_UNICODE
    assert nl_up.ki.wVk == VK_RETURN
    assert nl_up.ki.dwFlags == KEYEVENTF_KEYUP
    # surrounding characters stay Unicode
    assert inputs[0].ki.dwFlags == KEYEVENTF_UNICODE
    assert inputs[4].ki.wScan == ord("b")


def test_blank_lines_between_blocks_emit_two_enters() -> None:
    # Email drafts and the Code brief join blocks with '\n\n' — both must type.
    inputs = _build_inputs("x\n\ny")

    enters = [ev for ev in inputs if ev.ki.wVk == VK_RETURN and ev.ki.dwFlags == 0]
    assert len(enters) == 2  # two Enter key-downs -> a real blank line


def test_empty_text_builds_no_events() -> None:
    assert len(_build_inputs("")) == 0
