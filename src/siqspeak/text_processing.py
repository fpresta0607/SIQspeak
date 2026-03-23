"""Post-process Whisper transcription output for coding syntax."""
from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Stopwords: "at <stopword>" should NOT become "@<stopword>"
# ---------------------------------------------------------------------------
_AT_STOPWORDS = {
    "the", "a", "an", "my", "your", "his", "her", "its", "our", "their",
    "this", "that", "once", "least", "most", "all", "first", "last",
    "home", "work", "school", "night", "noon", "risk", "best", "bay",
    "play", "hand", "war", "fault", "peace", "ease", "length", "large",
    "will", "issue", "stake", "present", "times", "sea", "point", "heart",
    "any", "some", "no", "every", "each", "which", "what", "one", "two",
}

# ---------------------------------------------------------------------------
# Tier 1 — Unambiguous multi-word phrases (longest first)
# ---------------------------------------------------------------------------
_TIER1_PHRASES: list[tuple[str, str]] = [
    # Brackets (longest variants first)
    (r"\bopen\s+curly\s+brace\b", "{"),
    (r"\bclose\s+curly\s+brace\b", "}"),
    (r"\bopen\s+square\s+bracket\b", "["),
    (r"\bclose\s+square\s+bracket\b", "]"),
    (r"\bopen\s+parenthesis\b", "("),
    (r"\bclose\s+parenthesis\b", ")"),
    (r"\bopen\s+curly\b", "{"),
    (r"\bclose\s+curly\b", "}"),
    (r"\bopen\s+paren\b", "("),
    (r"\bclose\s+paren\b", ")"),
    (r"\bopen\s+bracket\b", "["),
    (r"\bclose\s+bracket\b", "]"),
    (r"\bopen\s+brace\b", "{"),
    (r"\bclose\s+brace\b", "}"),
    # Arrow (must come before "greater than" to match "dash greater than" first)
    (r"\bdash\s+greater\s+than\b", "->"),
    (r"\bdash\s+arrow\b", "->"),
    # Comparison operators (longest first)
    (r"\bless\s+than\s+or\s+equals?\b", "<="),
    (r"\bgreater\s+than\s+or\s+equals?\b", ">="),
    (r"\bdouble\s+equals?\b", "=="),
    (r"\bnot\s+equals?\b", "!="),
    (r"\bless\s+than\b", "<"),
    (r"\bgreater\s+than\b", ">"),
    # Multi-word symbols
    (r"\bforward\s+slash\b", "/"),
    (r"\bback\s*slash\b", "\\\\"),
    (r"\bexclamation\s+point\b", "!"),
    (r"\bexclamation\s+mark\b", "!"),
    (r"\bquestion\s+mark\b", "?"),
    (r"\bdollar\s+sign\b", "$"),
    (r"\bnew\s*line\b", "\n"),
]

# ---------------------------------------------------------------------------
# Tier 2 — Unambiguous single-word replacements
# ---------------------------------------------------------------------------
_TIER2_WORDS: list[tuple[str, str]] = [
    (r"\bampersand\b", "&"),
    (r"\basterisk\b", "*"),
    (r"\btilde\b", "~"),
    (r"\bunderscore\b", "_"),
    (r"\bsemicolon\b", ";"),
    (r"\bhashtag\b", "#"),
    (r"\bcaret\b", "^"),
    (r"\bpipe\b", "|"),
    (r"\bcolon\b", ":"),
    (r"\bslash\b", "/"),
    (r"\bpercent\b", "%"),
    (r"\bequals\b", "="),
    (r"\bplus\b", "+"),
    (r"\bdash\b", "-"),
    (r"\bhyphen\b", "-"),
    (r"\bbang\b", "!"),
]

# ---------------------------------------------------------------------------
# Compile all fixed rules (Tier 1 + Tier 2)
# ---------------------------------------------------------------------------
_FIXED_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(pattern, re.IGNORECASE), repl)
    for pattern, repl in _TIER1_PHRASES + _TIER2_WORDS
]

# ---------------------------------------------------------------------------
# Tier 3 — Context-sensitive compiled patterns
# ---------------------------------------------------------------------------
_RE_AT = re.compile(r"\bat\s+(\w+)", re.IGNORECASE)
_RE_DOT = re.compile(r"(\w+)\s+dot\s+(\w+)", re.IGNORECASE)
_RE_HASH = re.compile(r"\bhash\s+(?=\w)", re.IGNORECASE)
_RE_STAR_GLOB = re.compile(r"(?<=\.)\s*star\b|\bstar\s*(?=\.)", re.IGNORECASE)

# Cleanup patterns
_RE_MULTI_SPACE = re.compile(r" {2,}")
_RE_SPACE_AFTER_OPEN = re.compile(r"([(\[{])\s+")
_RE_SPACE_BEFORE_CLOSE = re.compile(r"\s+([)\]}])")


def _replace_at(m: re.Match[str]) -> str:
    """Replace 'at <word>' → '@<word>' unless <word> is a stopword."""
    word = m.group(1)
    if word.lower() in _AT_STOPWORDS:
        return m.group(0)  # keep original
    return f"@{word}"


def postprocess_transcription(text: str) -> str:
    """Convert spoken coding syntax to symbols in transcribed text."""
    if not text:
        return text

    # Tier 1 + 2: fixed replacements
    for pattern, repl in _FIXED_RULES:
        text = pattern.sub(repl, text)

    # Tier 3: context-sensitive
    # Order matters: "dot" must run before "at" so "at readme dot md"
    # becomes "at readme.md" first, then "@readme.md" (not "@readme dot md").

    # "dot" between words → "." (loop for chains like "www dot google dot com")
    for _ in range(5):
        new_text = _RE_DOT.sub(r"\1.\2", text)
        if new_text == text:
            break
        text = new_text

    # "at <word>" → "@<word>" (unless stopword)
    text = _RE_AT.sub(_replace_at, text)

    # "hash <word>" → "#<word>"
    text = _RE_HASH.sub("#", text)

    # "star" adjacent to dots → "*" (glob patterns like "*.py")
    text = _RE_STAR_GLOB.sub("*", text)

    # Cleanup
    text = _RE_MULTI_SPACE.sub(" ", text)
    text = _RE_SPACE_AFTER_OPEN.sub(r"\1", text)
    text = _RE_SPACE_BEFORE_CLOSE.sub(r"\1", text)

    return text.strip()
