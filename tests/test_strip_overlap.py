"""Tests for streaming overlap dedup."""
from __future__ import annotations

import pytest

from siqspeak.audio.streaming import _strip_overlap


def test_no_overlap():
    result = _strip_overlap("new text here", ["old", "words"])
    assert result == "new text here"


def test_full_overlap():
    result = _strip_overlap("hello world foo", ["hello", "world"])
    assert result == "foo"


def test_partial_overlap():
    result = _strip_overlap("world foo bar", ["hello", "world"])
    assert result == "foo bar"


def test_case_insensitive():
    result = _strip_overlap("Hello World new", ["hello", "world"])
    assert result == "new"


def test_punctuation_ignored():
    result = _strip_overlap("hello, world. foo", ["hello", "world"])
    assert result == "foo"


def test_empty_tail():
    result = _strip_overlap("hello world", [])
    assert result == "hello world"


def test_empty_text():
    result = _strip_overlap("", ["hello"])
    assert result == ""


@pytest.mark.parametrize("tail,text,expected", [
    (["the", "quick"], "quick brown fox", "brown fox"),
    (["a", "b", "c"], "b c d e", "d e"),
    (["x"], "x y z", "y z"),
])
def test_parametrized_overlaps(tail: list[str], text: str, expected: str):
    assert _strip_overlap(text, tail) == expected
