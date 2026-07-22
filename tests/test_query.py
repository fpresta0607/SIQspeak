"""Tests for query-term extraction used by grep context retrieval."""
from __future__ import annotations

import pytest

from siqspeak.enhancement.query import STOPWORDS, extract_query_terms


def test_basic_sentence_keeps_content_drops_stopwords() -> None:
    terms = extract_query_terms("Please add validation to the login function")
    assert terms == ("validation", "login", "function")
    assert not (set(terms) & STOPWORDS)


def test_snake_case_split_into_parts_and_whole_kept() -> None:
    terms = extract_query_terms("update enhancement_mode config")
    assert terms == ("update", "enhancement", "mode", "enhancement_mode", "config")


def test_camel_case_split_into_parts_and_whole_kept() -> None:
    terms = extract_query_terms("call extractContext helper")
    assert terms == ("call", "extract", "context", "extractcontext", "helper")


def test_kebab_case_split_into_parts_and_whole_kept() -> None:
    terms = extract_query_terms("fix kebab-case handling")
    assert terms == ("fix", "kebab", "case", "kebab-case", "handling")


def test_double_quoted_phrase_preserved_as_single_term() -> None:
    terms = extract_query_terms('add a "dark mode toggle" to settings')
    assert "dark mode toggle" in terms
    assert "settings" in terms


def test_single_quoted_phrase_preserved_as_single_term() -> None:
    terms = extract_query_terms("implement 'user login' flow")
    assert "user login" in terms
    assert "flow" in terms


def test_contraction_apostrophe_is_not_a_quote() -> None:
    # A word-internal apostrophe must not open a spurious quoted phrase.
    terms = extract_query_terms("don't remove the cache layer")
    assert not any(" " in term for term in terms)
    assert "cache" in terms
    assert "layer" in terms


def test_numbers_and_single_characters_dropped() -> None:
    terms = extract_query_terms("retry 3 times x y payload")
    assert terms == ("retry", "times", "payload")


def test_dedupe_preserves_first_seen_order() -> None:
    terms = extract_query_terms("cache the cache and refresh cache")
    assert terms == ("cache", "refresh")


def test_limit_is_respected() -> None:
    request = "alpha beta gamma delta epsilon zeta eta theta iota kappa"
    assert len(extract_query_terms(request, limit=4)) == 4
    assert extract_query_terms(request, limit=4) == ("alpha", "beta", "gamma", "delta")


@pytest.mark.parametrize("value", ["", "   ", "\t\n  "])
def test_empty_or_whitespace_returns_empty(value: str) -> None:
    assert extract_query_terms(value) == ()


@pytest.mark.parametrize("value", [None, 123, ["term"], {"a": 1}])
def test_non_string_input_guarded_to_empty(value: object) -> None:
    assert extract_query_terms(value) == ()  # type: ignore[arg-type]


def test_stopwords_only_input_returns_empty() -> None:
    assert extract_query_terms("please add the to of and") == ()
