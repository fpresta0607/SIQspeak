"""Source guards for the modernized installer and download helper.

These assert against the text of ``setup.bat`` and ``scripts/download_model.py``
rather than executing the batch installer.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SETUP = (ROOT / "setup.bat").read_text(encoding="utf-8")
DOWNLOAD = (ROOT / "scripts" / "download_model.py").read_text(encoding="utf-8")


def test_installer_has_no_huggingface_signin_or_token_flow() -> None:
    lowered = SETUP.lower()
    for forbidden in (
        "huggingface",
        "hf_token",
        "hf_check",
        "hf_login",
        "access token",
        "settings/tokens",
    ):
        assert forbidden not in lowered, f"stale HF reference: {forbidden!r}"


def test_installer_has_no_inline_cdn_fallback() -> None:
    assert "urllib.request" not in SETUP
    assert "resolve/main" not in SETUP


def test_installer_downloads_base_english_by_default() -> None:
    assert "download_model.py base.en" in SETUP
    assert "download_model.py tiny" not in SETUP


def test_installer_confirms_prompt_enhancer_explicitly() -> None:
    assert (
        'set /p ENHANCER="   Download the optional local prompt enhancer (~3.4 GB)? [Y/N]: "'
        in SETUP
    )


def test_installer_default_ollama_model_is_qwen() -> None:
    assert "ollama pull qwen3.5:4b" in SETUP


def test_installer_pulls_ollama_only_on_confirmed_path() -> None:
    assert "where ollama" in SETUP
    assert 'if /i "!ENHANCER!"=="Y"' in SETUP

    enhancer_index = SETUP.index("set /p ENHANCER")
    pull_index = SETUP.index("ollama pull qwen3.5:4b")
    assert enhancer_index < pull_index

    # The pull must sit behind the confirmation gate.
    gate_index = SETUP.index('if /i "!ENHANCER!"=="Y"')
    assert enhancer_index < gate_index < pull_index


def test_installer_missing_ollama_shows_install_guidance() -> None:
    lowered = SETUP.lower()
    assert "ollama.com/download" in lowered
    assert "rerun setup.bat" in lowered


def test_installer_keeps_shortcut_and_run_flow() -> None:
    assert "create_shortcut.ps1" in SETUP
    assert "Run SIQspeak now" in SETUP
    assert "-m siqspeak" in SETUP


def test_download_helper_defaults_to_base_english() -> None:
    assert '"base.en"' in DOWNLOAD
    assert '"tiny"' not in DOWNLOAD


def test_download_helper_drops_unused_os_import() -> None:
    assert "import os" not in DOWNLOAD


def test_download_helper_validates_through_faster_whisper() -> None:
    assert "_MODELS" in DOWNLOAD


def test_download_helper_returns_nonzero_exit_on_failure() -> None:
    assert "sys.exit(main())" in DOWNLOAD
    assert "return 1" in DOWNLOAD
