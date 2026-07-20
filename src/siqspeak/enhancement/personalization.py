"""Select a few *relevant* examples of the user's own phrasing for few-shot style.

This teaches the small enhancement model the user's tone and structure without any
fine-tuning: a bounded pool of past user-authored requests is built from local
Claude session transcripts and workspace plan objectives, then ranked against the
current request by transparent token overlap (mirroring ``rank_skill_candidates``).

Everything is local, read-only, and bounded — file counts, lines read, pool size,
and per-example length are all capped. Only the handful of short *selected* examples
ever leave the pool; whole sessions are never dumped, and no content is logged.
"""
from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path

MAX_SESSION_FILES = 20
MAX_LINES_PER_FILE = 2000
MAX_LINE_BYTES = 20000  # skip pathologically long JSONL lines before parsing
MAX_PLAN_FILES = 10     # cap the plan glob for consistency with context.py
MAX_POOL_SIZE = 300
MAX_PLAN_BYTES = 8 * 1024

MIN_EXAMPLE_CHARS = 20
MAX_EXAMPLE_CHARS = 400

_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_WORD_TOKEN_RE = re.compile(r"[a-z0-9]+")
_GOAL_RE = re.compile(r"\*\*goal:?\*\*\s*", re.IGNORECASE)
_CODE_MARKERS = ("```", "{", "}", ";", "()", "=>", "::")
# Drop candidates that look like leaked secrets so they never enter the prompt.
_SECRET_RE = re.compile(r"AKIA|sk-|ghp_|xox[baprs]-|Bearer |-----BEGIN")


def select_style_examples(
    raw_text: str,
    home: Path | None,
    workspace: Path | None,
    limit: int = 3,
) -> tuple[str, ...]:
    """Return up to ``limit`` past user requests most relevant to ``raw_text``.

    Candidates are ranked by request/candidate token overlap, then shortest first
    on ties, so the returned examples are both relevant and concise. An empty pool
    (no sessions, no plans, nothing that passes the filters) yields ``()``.
    """
    pool = _build_pool(home, workspace)
    if not pool:
        return ()
    request_tokens = _word_tokens(raw_text)
    scored = [
        (len(request_tokens & _word_tokens(candidate)), len(candidate), candidate)
        for candidate in pool
    ]
    scored.sort(key=lambda item: (-item[0], item[1]))
    return tuple(candidate for _, _, candidate in scored[:limit])


def _build_pool(home: Path | None, workspace: Path | None) -> list[str]:
    seen: set[str] = set()
    pool: list[str] = []
    for text in _iter_candidate_texts(home, workspace):
        normalized = _normalize(text)
        if normalized is None or normalized in seen:
            continue
        seen.add(normalized)
        pool.append(normalized)
        if len(pool) >= MAX_POOL_SIZE:
            break
    return pool


def _iter_candidate_texts(home: Path | None, workspace: Path | None) -> Iterator[str]:
    yield from _iter_session_texts(home)
    yield from _iter_plan_texts(workspace)


def _iter_session_texts(home: Path | None) -> Iterator[str]:
    for path in _session_files(home):
        try:
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                for line_number, line in enumerate(handle):
                    if line_number >= MAX_LINES_PER_FILE:
                        break
                    if len(line) > MAX_LINE_BYTES:
                        continue
                    text = _user_text_from_line(line)
                    if text:
                        yield text
        except OSError:
            continue


def _session_files(home: Path | None) -> list[Path]:
    if home is None:
        return []
    projects = Path(home) / ".claude" / "projects"
    if not projects.is_dir():
        return []
    # Global home files are trusted for location; skip symlinks only.
    files = [
        path for path in projects.rglob("*.jsonl")
        if path.is_file() and not path.is_symlink()
    ]
    files.sort(key=lambda path: -path.stat().st_mtime)
    return files[:MAX_SESSION_FILES]


def _user_text_from_line(line: str) -> str | None:
    stripped = line.strip()
    if not stripped:
        return None
    try:
        obj = json.loads(stripped)
    except ValueError:
        return None
    if not isinstance(obj, dict):
        return None

    message = obj.get("message")
    is_user = obj.get("type") == "user"
    if isinstance(message, dict):
        if message.get("role") == "user":
            is_user = True
        content = message.get("content")
    else:
        content = obj.get("content")
    if not is_user:
        return None
    return _content_text(content)


def _content_text(content: object) -> str | None:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [
            block["text"]
            for block in content
            if isinstance(block, dict)
            and block.get("type") == "text"
            and isinstance(block.get("text"), str)
        ]
        if parts:
            return " ".join(parts)
    return None


def _iter_plan_texts(workspace: Path | None) -> Iterator[str]:
    if workspace is None:
        return
    root = Path(workspace)
    plans_dir = root / "docs" / "plans"
    if not plans_dir.is_dir():
        return
    plans = sorted(plans_dir.glob("*.md"), key=lambda path: -path.stat().st_mtime)
    for path in plans[:MAX_PLAN_FILES]:
        if not _is_contained(path, root):
            continue
        objective = _plan_objective(path)
        if objective:
            yield objective


def _is_contained(path: Path, root: Path) -> bool:
    """Reject symlinks and paths whose resolved target escapes ``root``."""
    try:
        if path.is_symlink():
            return False
        resolved = path.resolve()
        root_resolved = root.resolve()
        return resolved == root_resolved or root_resolved in resolved.parents
    except OSError:
        return False


def _plan_objective(path: Path) -> str | None:
    """Return the plan's ``**Goal:**`` line, else its first non-heading paragraph."""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            raw = handle.read(MAX_PLAN_BYTES)
    except OSError:
        return None
    fallback: str | None = None
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = _GOAL_RE.search(stripped)
        if match:
            return stripped[match.end():] or stripped
        if fallback is None:
            fallback = stripped
    return fallback


def _normalize(text: str) -> str | None:
    collapsed = " ".join(_CONTROL_RE.sub(" ", text).split())
    if not MIN_EXAMPLE_CHARS <= len(collapsed) <= MAX_EXAMPLE_CHARS:
        return None
    if any(marker in collapsed for marker in _CODE_MARKERS):
        return None
    if _SECRET_RE.search(collapsed):
        return None
    return collapsed


def _word_tokens(text: str) -> set[str]:
    return set(_WORD_TOKEN_RE.findall(text.lower()))
