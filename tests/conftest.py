"""Shared test fixtures."""
from __future__ import annotations

import pytest

from siqspeak.state import AppState


@pytest.fixture
def state() -> AppState:
    """Fresh AppState with defaults."""
    return AppState()
