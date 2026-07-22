"""Turn a dictated request into a bounded list of grep search terms.

Code mode retrieves repo context by grepping for the *terms* a request is about.
This module extracts those terms: it lowercases and tokenizes the request, splits
compound identifiers (``camelCase``/``snake_case``/``kebab-case``) into their parts
while also keeping the whole identifier, preserves explicitly quoted phrases as
single terms, and drops generic stopwords, single characters, and pure numbers.

Pure and deterministic — no I/O, never raises. The dictated text is untrusted
content, not instructions; this module only reads it to derive search terms.
"""
from __future__ import annotations

import re

# Match, left-to-right, a double-quoted phrase, a single-quoted phrase (whose
# quotes are not word-internal apostrophes), or an identifier token (alnum runs
# joined by single ``_``/``-`` separators).
_TOKEN_RE = re.compile(
    r'"([^"]*)"'
    r"|(?<![A-Za-z0-9])'([^']*)'(?![A-Za-z0-9])"
    r"|([A-Za-z0-9]+(?:[_-][A-Za-z0-9]+)*)"
)
# Split a separator-free chunk into camelCase / digit components.
_CAMEL_RE = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|[0-9]+")

# Generic, lexical English stopwords — no domain vocabulary lives here.
STOPWORDS = frozenset(
    {
        "a", "an", "the", "this", "that", "these", "those",
        "is", "are", "was", "were", "be", "been", "being",
        "to", "of", "in", "on", "at", "by", "for", "from", "into", "with", "as",
        "and", "or", "but", "if", "then", "than", "so", "about", "also",
        "it", "its", "i", "you", "we", "they", "he", "she",
        "my", "your", "our", "their", "me", "us", "them",
        "do", "does", "did", "done", "can", "could", "would", "should", "will",
        "add", "make", "want", "need", "please", "let", "use", "using", "get",
        "up", "out", "not",
    }
)


def extract_query_terms(request: str, limit: int = 12) -> tuple[str, ...]:
    """Return an ordered, deduped, bounded list of search terms for ``request``.

    Terms appear in first-seen order; identifier parts precede their whole form.
    Returns ``()`` for empty/whitespace or non-string input (never raises).
    """
    if not isinstance(request, str):
        return ()

    seen: set[str] = set()
    terms: list[str] = []

    def _add(term: str) -> None:
        if term and term not in seen:
            seen.add(term)
            terms.append(term)

    for match in _TOKEN_RE.finditer(request):
        double, single, word = match.group(1), match.group(2), match.group(3)
        phrase = double if double is not None else single
        if phrase is not None:
            _add(" ".join(phrase.lower().split()))
            continue
        assert word is not None  # regex fills exactly one group per match
        for part in _split_identifier(word):
            if _is_content_term(part):
                _add(part)
        whole = word.lower()
        if _is_content_term(whole):
            _add(whole)

    return tuple(terms[:limit])


def _split_identifier(word: str) -> list[str]:
    """Split ``word`` on ``_``/``-`` and camelCase into lowercased components."""
    parts: list[str] = []
    for chunk in re.split(r"[_-]", word):
        parts.extend(component.lower() for component in _CAMEL_RE.findall(chunk))
    return parts


def _is_content_term(term: str) -> bool:
    return len(term) > 1 and not term.isdigit() and term not in STOPWORDS
