"""Tests for transcription post-processing (spoken coding syntax → symbols)."""
from __future__ import annotations

import pytest

from siqspeak.text_processing import postprocess_transcription


# ---------------------------------------------------------------------------
# Tier 1: Unambiguous multi-word phrases
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("spoken,expected", [
    ("open paren", "("),
    ("close paren", ")"),
    ("open parenthesis", "("),
    ("close parenthesis", ")"),
    ("open bracket", "["),
    ("close bracket", "]"),
    ("open square bracket", "["),
    ("close square bracket", "]"),
    ("open brace", "{"),
    ("close brace", "}"),
    ("open curly", "{"),
    ("close curly", "}"),
    ("open curly brace", "{"),
    ("close curly brace", "}"),
    ("forward slash", "/"),
    ("backslash", "\\"),
    ("back slash", "\\"),
    ("double equals", "=="),
    ("not equals", "!="),
    ("not equal", "!="),
    ("less than", "<"),
    ("greater than", ">"),
    ("less than or equal", "<="),
    ("greater than or equals", ">="),
    ("exclamation point", "!"),
    ("exclamation mark", "!"),
    ("question mark", "?"),
    ("dollar sign", "$"),
    ("dash greater than", "->"),
    ("dash arrow", "->"),
])
def test_tier1_multi_word(spoken: str, expected: str):
    assert postprocess_transcription(spoken) == expected


def test_newline():
    # "new line" is replaced with \n; surrounding spaces are preserved
    assert "\n" in postprocess_transcription("hello new line world")
    assert "\n" in postprocess_transcription("hello newline world")


# ---------------------------------------------------------------------------
# Tier 2: Unambiguous single-word replacements
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("spoken,expected", [
    ("ampersand", "&"),
    ("asterisk", "*"),
    ("tilde", "~"),
    ("underscore", "_"),
    ("semicolon", ";"),
    ("hashtag", "#"),
    ("caret", "^"),
    ("pipe", "|"),
    ("colon", ":"),
    ("slash", "/"),
    ("percent", "%"),
    ("equals", "="),
    ("plus", "+"),
    ("dash", "-"),
    ("hyphen", "-"),
    ("bang", "!"),
])
def test_tier2_single_word(spoken: str, expected: str):
    assert postprocess_transcription(spoken) == expected


# ---------------------------------------------------------------------------
# Tier 3: Context-sensitive
# ---------------------------------------------------------------------------
class TestAtSymbol:
    def test_at_before_filename(self):
        assert postprocess_transcription("at readme") == "@readme"

    def test_at_before_dotted_name(self):
        assert postprocess_transcription("at readme dot md") == "@readme.md"

    def test_at_before_username(self):
        assert postprocess_transcription("at user dot name") == "@user.name"

    def test_at_preserved_before_stopword(self):
        assert postprocess_transcription("I was at the store") == "I was at the store"
        assert postprocess_transcription("check at least three") == "check at least three"
        assert postprocess_transcription("at home") == "at home"
        assert postprocess_transcription("at work") == "at work"
        assert postprocess_transcription("at first") == "at first"
        assert postprocess_transcription("at last") == "at last"
        assert postprocess_transcription("at once") == "at once"
        assert postprocess_transcription("at all") == "at all"


class TestDot:
    def test_dot_joins_words(self):
        assert postprocess_transcription("app dot py") == "app.py"

    def test_dot_chain(self):
        assert postprocess_transcription("www dot google dot com") == "www.google.com"

    def test_dot_triple_chain(self):
        assert postprocess_transcription("foo dot bar dot baz dot qux") == "foo.bar.baz.qux"


class TestHash:
    def test_hash_before_word(self):
        assert postprocess_transcription("hash include") == "#include"

    def test_hash_before_number(self):
        result = postprocess_transcription("hash 42")
        assert result == "#42"


class TestStarGlob:
    def test_star_dot_py(self):
        assert postprocess_transcription("star dot py") == "*.py"


# ---------------------------------------------------------------------------
# Arrow: bare "arrow" should NOT be replaced
# ---------------------------------------------------------------------------
def test_bare_arrow_preserved():
    assert postprocess_transcription("press the arrow key") == "press the arrow key"


def test_dash_arrow_replaced():
    assert postprocess_transcription("dash arrow") == "->"


# ---------------------------------------------------------------------------
# Combined / integration
# ---------------------------------------------------------------------------
def test_combined_brackets_and_content():
    result = postprocess_transcription("open paren hello close paren")
    assert result == "(hello)"


def test_combined_at_with_dotted_path():
    result = postprocess_transcription("at src slash utils dot py")
    assert result == "@src / utils.py"


def test_combined_comparison():
    result = postprocess_transcription("if x less than or equal y")
    assert result == "if x <= y"


def test_multiple_symbols_in_sentence():
    result = postprocess_transcription("use ampersand ampersand for and")
    assert result == "use & & for and"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------
def test_empty_string():
    assert postprocess_transcription("") == ""


def test_plain_text_unchanged():
    assert postprocess_transcription("hello world this is a test") == "hello world this is a test"


def test_case_insensitive():
    assert postprocess_transcription("Open Paren") == "("
    assert postprocess_transcription("FORWARD SLASH") == "/"


def test_no_double_replacement():
    """'not equals' → '!=' (not '! =' from separate rules)."""
    assert postprocess_transcription("not equals") == "!="


def test_ordering_double_equals_before_equals():
    """'double equals' → '==' (not '= =' from 'equals' rule)."""
    assert postprocess_transcription("double equals") == "=="
