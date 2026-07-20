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
    for match in WINDOWS_PATH.finditer(window_title):
        detected = Path(match.group(0).rstrip(" -"))
        if detected.exists():
            return find_repository_root(detected)
    return None
