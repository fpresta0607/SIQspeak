"""Resolve trusted workspace roots without guessing.

Only two signals are trusted: an explicit manual override and an absolute
Windows path parsed out of the foreground-window title. No drive scans, user
profiles, recent-file databases, or editor caches.
"""
from __future__ import annotations

import re
from pathlib import Path

WINDOWS_PATH = re.compile(r"[A-Za-z]:\\[^|<>\"?*]+")


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
    foreground_title: str,
) -> Path | None:
    """Resolve a trusted workspace root, or None when unknown.

    A valid manual override always wins. Otherwise scan the foreground-window
    title for an existing absolute path and ascend to its Git root. Never guess.
    """
    if manual_override:
        manual = Path(manual_override).expanduser()
        if manual.is_dir():
            return manual.resolve()
    for match in WINDOWS_PATH.finditer(foreground_title):
        detected = Path(match.group(0).rstrip(" -"))
        if detected.exists():
            return find_repository_root(detected)
    return None
