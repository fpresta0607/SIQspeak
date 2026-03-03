"""Helpers for running as a frozen (PyInstaller) application."""

from __future__ import annotations

import os
import sys


def is_frozen() -> bool:
    """Return True if running inside a PyInstaller bundle."""
    return getattr(sys, "frozen", False)


def frozen_base() -> str:
    """Return the base directory of the PyInstaller bundle, or cwd."""
    if is_frozen():
        return sys._MEIPASS  # type: ignore[attr-defined]
    return os.getcwd()


def bundled_model_path(model_name: str) -> str | None:
    """Return the path to a bundled model, or None if not bundled."""
    if not is_frozen():
        return None
    candidate = os.path.join(frozen_base(), "models", model_name)
    if os.path.isdir(candidate) and os.path.exists(os.path.join(candidate, "model.bin")):
        return candidate
    return None
