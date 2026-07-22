"""Grep-driven snippet retrieval for Code-mode context loading.

Given a bounded list of query terms and a workspace root, this module locates the
lines/sections that mention those terms and returns them as ``ContextFinding``s
tagged with ``path:line`` provenance — never whole files. It is the query-driven
replacement for whole-file pre-loading: fast, targeted, and source-aware.

The primary engine is a bounded ``os.walk`` + ``re`` scan in pure Python (no hard
dependency on ``ripgrep``). ``rg`` is used only as an optional fast-path to obtain
the candidate *file list*; the denylist, containment, size, and extension checks
plus all snippet extraction always run in Python, so the walk is correct on its
own and ``rg`` can never widen what is read.

Security: grepping arbitrary repo files is a new secret-exposure path, so secret
files (``.env*``, ``*.key``, ``*.pem``, ...) are denylisted before any read,
symlinks and out-of-root paths are rejected via the reused containment guard,
oversized files and minified lines are skipped, and this function never raises
and never logs file or snippet content.
"""
from __future__ import annotations

import fnmatch
import os
import re
import shutil
import subprocess
from pathlib import Path

from siqspeak.enhancement.context import ContextFinding, _is_within, _read_bounded

CREATE_NO_WINDOW = 0x08000000  # keep an optional rg call from flashing a console

# --- Hard bounds (all enforced across a single retrieval) ---
MAX_FILES_SEARCHED = 500
MAX_FILE_BYTES = 200 * 1024
MAX_LINE_BYTES = 2000
MAX_SNIPPET_CHARS = 1200
MAX_HITS = 8
MAX_TOTAL_CHARS = 10_000
CONTEXT_LINES = 3

RG_TIMEOUT_SECONDS = 5

# Directories never descended into (VCS, deps, build output, caches, worktrees).
PRUNE_DIRS = frozenset(
    {
        ".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build",
        ".worktrees", ".mypy_cache", ".pytest_cache", "target", ".next",
    }
)

# Only these extensions are treated as readable text; everything else is binary.
SOURCE_EXTENSIONS = frozenset(
    {
        ".py", ".js", ".ts", ".tsx", ".jsx", ".rs", ".go", ".java", ".c", ".cpp",
        ".h", ".hpp", ".cs", ".rb", ".php", ".sh", ".bat", ".ps1", ".html", ".css",
        ".sql",
    }
)
DOC_EXTENSIONS = frozenset({".md", ".rst", ".txt"})
CONFIG_EXTENSIONS = frozenset({".json", ".toml", ".cfg", ".ini", ".yaml", ".yml"})
ALLOWED_EXTENSIONS = SOURCE_EXTENSIONS | DOC_EXTENSIONS | CONFIG_EXTENSIONS

# Secret-file denylist (glob patterns, matched case-insensitively on the filename).
# Skipped entirely — never opened — even when the extension is otherwise allowed.
SECRET_FILE_PATTERNS = (
    ".env", ".env.*", "*.env", "*.key", "*.pem", "*.pfx", "id_rsa*", "id_ed25519*",
    "*.tfvars", "*.secret*", ".npmrc", ".netrc", "*.p12", "secrets.*", ".mcp.json",
)

_TYPE_WEIGHT = {"source": 3, "docs": 2, "config": 1}
_CATEGORY = {
    "source": "implementation_pattern",
    "docs": "architecture",
    "config": "tooling",
}
_MD_HEADER_RE = re.compile(r"^\s{0,3}#{1,6}\s")


def retrieve_snippets(terms: tuple[str, ...], root: Path) -> tuple[ContextFinding, ...]:
    """Return ranked, bounded, ``path:line``-attributed snippets matching ``terms``.

    Walks ``root`` (pruning noise dirs), reads only allowlisted text files that
    survive the secret denylist / symlink / containment / size guards, extracts a
    bounded snippet per hit (markdown section for docs, matching line ± context for
    code/config), then ranks by distinct-terms x file-type weight, dedups
    overlapping snippets, and enforces the ``MAX_*`` bounds. Read-only and local;
    never logs content and never raises — returns ``()`` on any failure.
    """
    if not terms or root is None:
        return ()
    try:
        root_path = Path(root)
        if not root_path.is_dir():
            return ()
        pattern = _build_pattern(terms)
        if pattern is None:
            return ()

        candidates = _candidate_files(root_path, pattern.pattern)
        scored: list[tuple[int, str, ContextFinding]] = []
        searched = 0
        for path in candidates:
            if searched >= MAX_FILES_SEARCHED:
                break
            file_type = _classify(path)
            if file_type is None or not _is_readable_file(path, root_path):
                continue
            text = _read_bounded(path, root=root_path)
            if text is None:
                continue
            searched += 1
            relpath = path.relative_to(root_path).as_posix()
            scored.extend(_search_text(text, pattern, relpath, file_type))
    except Exception:
        # Best-effort: any unexpected failure yields no findings, never propagates.
        return ()

    scored.sort(key=lambda item: (-item[0], item[1]))

    result: list[ContextFinding] = []
    total_chars = 0
    for _, _, finding in scored:
        if len(result) >= MAX_HITS:
            break
        if total_chars + len(finding.text) > MAX_TOTAL_CHARS:
            continue
        result.append(finding)
        total_chars += len(finding.text)
    return tuple(result)


def _build_pattern(terms: tuple[str, ...]) -> re.Pattern[str] | None:
    """Compile a case-insensitive alternation with identifier-aware boundaries.

    Uses ``[a-z0-9]`` lookarounds rather than ``\\b`` so ``_`` counts as a
    separator: ``transcription`` matches inside ``transcription_language`` (the
    snake_case codebase norm), while ``cat`` still won't match ``category``.
    camelCase identifiers are reached via query.py's whole-identifier term.
    """
    escaped = [re.escape(term) for term in terms if term]
    if not escaped:
        return None
    return re.compile(
        r"(?<![a-z0-9])(" + "|".join(escaped) + r")(?![a-z0-9])", re.IGNORECASE,
    )


def _candidate_files(root: Path, pattern_source: str) -> list[Path]:
    """Return candidate file paths, preferring an ``rg`` file list, else a walk.

    The ``rg`` fast-path only narrows the *file list*; every returned file still
    passes the denylist/containment/size/extension guards and Python snippet
    extraction downstream, so ``rg`` can never widen what is read. Any ``rg``
    absence, error, or timeout falls through to the authoritative Python walk.
    """
    rg_files = _rg_candidate_files(root, pattern_source)
    if rg_files is not None:
        return rg_files
    return _walk_candidate_files(root)


def _walk_candidate_files(root: Path) -> list[Path]:
    """Enumerate files under ``root`` with ``os.walk``, pruning noise directories."""
    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name not in PRUNE_DIRS]
        for filename in filenames:
            files.append(Path(dirpath) / filename)
    return files


def _rg_candidate_files(root: Path, pattern_source: str) -> list[Path] | None:
    """Ask ``rg -l -i`` for files that match, or ``None`` to trigger the walk.

    ``None`` means "use the Python walk": returned when ``rg`` is absent or on any
    error/timeout. A clean ``rg`` run returns its (possibly empty) file list.
    """
    if shutil.which("rg") is None:
        return None
    try:
        completed = subprocess.run(
            ["rg", "-l", "-i", "--", pattern_source, str(root)],
            capture_output=True,
            text=True,
            timeout=RG_TIMEOUT_SECONDS,
            creationflags=CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    # rg exit codes: 0 = matches, 1 = no matches (both valid); anything else → walk.
    if completed.returncode not in (0, 1):
        return None
    return [Path(line) for line in completed.stdout.splitlines() if line.strip()]


def _is_readable_file(path: Path, root: Path) -> bool:
    """Apply the security/size guards that gate whether a file may be opened."""
    name = path.name.lower()
    if any(fnmatch.fnmatch(name, pattern) for pattern in SECRET_FILE_PATTERNS):
        return False
    try:
        if path.is_symlink() or not path.is_file():
            return False
        if not _is_within(path, root):
            return False
        if path.stat().st_size > MAX_FILE_BYTES:
            return False
    except OSError:
        return False
    return True


def _classify(path: Path) -> str | None:
    """Return ``source`` / ``docs`` / ``config`` for allowlisted files, else None."""
    suffix = path.suffix.lower()
    if suffix in SOURCE_EXTENSIONS:
        return "source"
    if suffix in DOC_EXTENSIONS:
        return "docs"
    if suffix in CONFIG_EXTENSIONS:
        return "config"
    return None


def _search_text(
    text: str,
    pattern: re.Pattern[str],
    relpath: str,
    file_type: str,
) -> list[tuple[int, str, ContextFinding]]:
    """Find hits in ``text`` and build deduped, scored snippet findings for a file."""
    lines = text.splitlines()
    hits: list[tuple[int, int, int, frozenset[str]]] = []  # start, end, anchor, terms
    for index, line in enumerate(lines):
        if len(line) > MAX_LINE_BYTES:
            continue
        matched = {match.group(0).lower() for match in pattern.finditer(line)}
        if not matched:
            continue
        start, end = _snippet_bounds(lines, index, file_type)
        hits.append((start, end, index, frozenset(matched)))

    if not hits:
        return []

    scored: list[tuple[int, str, ContextFinding]] = []
    for start, end, anchor, terms in _merge_hits(hits):
        snippet = "\n".join(lines[start:end]).strip()[:MAX_SNIPPET_CHARS]
        if not snippet:
            continue
        distinct = len(terms)
        score = distinct * _TYPE_WEIGHT[file_type]
        confidence = "high" if distinct >= 2 else "medium"
        source_path = f"{relpath}:{anchor + 1}"
        finding = ContextFinding(
            source_path=source_path,
            category=_CATEGORY[file_type],
            text=snippet,
            confidence=confidence,
        )
        scored.append((score, source_path, finding))
    return scored


def _snippet_bounds(lines: list[str], index: int, file_type: str) -> tuple[int, int]:
    """Return the ``[start, end)`` line range for the snippet around a hit."""
    if file_type == "docs":
        return _markdown_section_bounds(lines, index)
    start = max(0, index - CONTEXT_LINES)
    end = min(len(lines), index + CONTEXT_LINES + 1)
    return start, end


def _markdown_section_bounds(lines: list[str], index: int) -> tuple[int, int]:
    """Return the enclosing markdown section: nearest header above → next header."""
    start = 0
    for i in range(index, -1, -1):
        if _MD_HEADER_RE.match(lines[i]):
            start = i
            break
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if _MD_HEADER_RE.match(lines[i]):
            end = i
            break
    return start, end


def _merge_hits(
    hits: list[tuple[int, int, int, frozenset[str]]],
) -> list[tuple[int, int, int, frozenset[str]]]:
    """Merge hits whose line ranges overlap into one snippet, unioning terms."""
    merged: list[tuple[int, int, int, frozenset[str]]] = []
    for start, end, anchor, terms in sorted(hits, key=lambda hit: hit[0]):
        if merged and start < merged[-1][1]:
            prev_start, prev_end, prev_anchor, prev_terms = merged[-1]
            merged[-1] = (
                prev_start,
                max(prev_end, end),
                prev_anchor,
                prev_terms | terms,
            )
        else:
            merged.append((start, end, anchor, terms))
    return merged
