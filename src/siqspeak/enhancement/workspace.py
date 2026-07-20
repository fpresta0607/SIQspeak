"""Resolve trusted workspace roots without guessing.

Three signals are trusted, in order: an explicit manual override, the working
directory of the focused terminal's shell, and an absolute Windows path parsed
out of the dictated window's title. No drive scans, user profiles, recent-file
databases, or editor caches.
"""
from __future__ import annotations

import re
from pathlib import Path

from siqspeak.enhancement.terminal import terminal_cwd

DRIVE_START = re.compile(r"[A-Za-z]:\\")
_FORBIDDEN_PATH_CHARS = re.compile(r'[|<>"?*]')
_MIN_DIR_LEN = 3  # a drive root like ``C:\``


def _longest_existing_dir_prefix(candidate: str) -> Path | None:
    """Return the longest prefix of ``candidate`` that names an existing dir.

    Window titles append junk after an embedded path (``" — Cursor"``,
    ``" - recording.py"``); trimming one character at a time from the right
    recovers the real directory. Bounded by the candidate length, stops at
    drive-root width, and never raises on a malformed candidate.
    """
    text = candidate
    while len(text.rstrip()) >= _MIN_DIR_LEN:
        trimmed = text.rstrip()
        try:
            if Path(trimmed).is_dir():
                return Path(trimmed)
        except (OSError, ValueError):
            pass
        text = text[:-1]
    return None


def find_repository_root(path: Path) -> Path | None:
    """Ascend from a path to the nearest directory containing `.git`."""
    candidate = path.resolve()
    if candidate.is_file():
        candidate = candidate.parent
    for current in (candidate, *candidate.parents):
        if (current / ".git").exists():
            return current
    return None


def resolve_workspace(
    manual_override: str | None,
    window_title: str,
    window_hwnd: int | None = None,
) -> Path | None:
    """Resolve a trusted workspace root, or None when unknown.

    Precedence: (1) a valid manual override always wins; (2) the focused
    terminal's shell working directory (``window_hwnd``), ascended to its Git
    root; (3) an existing absolute path parsed from ``window_title`` — the title
    of the window dictated into, captured at record start — ascended to its Git
    root. Never guess.
    """
    if manual_override:
        manual = Path(manual_override).expanduser()
        if manual.is_dir():
            return manual.resolve()
    cwd = terminal_cwd(window_hwnd)
    if cwd is not None:
        terminal_root = find_repository_root(cwd)
        if terminal_root is not None:
            return terminal_root
    for match in DRIVE_START.finditer(window_title):
        tail = _FORBIDDEN_PATH_CHARS.split(window_title[match.start():], maxsplit=1)[0]
        detected = _longest_existing_dir_prefix(tail)
        if detected is None:
            continue
        root = find_repository_root(detected)
        if root is not None:
            return root
    return None
