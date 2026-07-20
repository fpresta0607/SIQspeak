"""Catalog + source guards for the simplified public speech-model download flow."""
from __future__ import annotations

from pathlib import Path

import pytest
from faster_whisper.utils import _MODELS

from siqspeak.config import AVAILABLE_MODELS, MODEL_SIZES_MB, SPEECH_MODELS

ROOT = Path(__file__).resolve().parents[1]


def test_curated_ordering_labels_and_sizes() -> None:
    assert SPEECH_MODELS == (
        {"name": "tiny.en", "tier": "Fastest", "size_mb": 75},
        {"name": "base.en", "tier": "Default", "size_mb": 141},
        {"name": "small.en", "tier": "Balanced", "size_mb": 464},
        {"name": "distil-medium.en", "tier": "High Quality", "size_mb": 755},
        {"name": "distil-large-v3.5", "tier": "Best Quality", "size_mb": 1446},
    )
    assert AVAILABLE_MODELS == (
        "tiny.en",
        "base.en",
        "small.en",
        "distil-medium.en",
        "distil-large-v3.5",
    )
    assert MODEL_SIZES_MB == {
        "tiny.en": 75,
        "base.en": 141,
        "small.en": 464,
        "distil-medium.en": 755,
        "distil-large-v3.5": 1446,
    }


def test_curated_identifiers_are_accepted_by_whisper() -> None:
    for name in AVAILABLE_MODELS:
        assert name in _MODELS


@pytest.mark.parametrize("legacy", ["tiny", "base", "small"])
def test_legacy_configured_identifiers_still_accepted(legacy: str) -> None:
    # A user upgrading from an old config.json may still have a bare identifier.
    assert legacy in _MODELS


@pytest.mark.parametrize(("relative_path", "forbidden"), [
    (
        "src/siqspeak/model/manager.py",
        (
            "hf_auth",
            "has_token",
            "is_auth_error",
            "needs_hf_auth",
            "token=True",
            "_direct_download",
            "snapshots",
            "resolve/main",
            "urlretrieve",
        ),
    ),
    (
        "src/siqspeak/overlay/panels/model_panel.py",
        (
            "hf_auth",
            "has_token",
            "validate_token",
            "needs_hf_auth",
            "HuggingFace",
            "Sign In",
            "AUTH_BUTTONS",
        ),
    ),
    (
        "src/siqspeak/interaction/click_handlers.py",
        (
            "hf_auth",
            "_handle_hf_auth_click",
            "validate_token",
            "needs_hf_auth",
        ),
    ),
])
def test_no_hf_auth_or_direct_cdn_in_source(relative_path: str, forbidden: tuple[str, ...]) -> None:
    text = (ROOT / relative_path).read_text(encoding="utf-8")

    found = [token for token in forbidden if token in text]

    assert found == []


def test_hf_auth_module_is_deleted() -> None:
    assert not (ROOT / "src/siqspeak/hf_auth.py").exists()
    assert not (ROOT / "scripts/hf_check.py").exists()
    assert not (ROOT / "scripts/hf_login.py").exists()
