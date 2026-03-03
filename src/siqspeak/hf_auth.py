"""HuggingFace authentication helpers for SIQspeak.

Handles token detection, validation, storage, and browser-based login flow.
Tokens are stored in the standard HuggingFace location (~/.cache/huggingface/token).
"""

from __future__ import annotations

import logging
import webbrowser

log = logging.getLogger("siqspeak")

# Pre-filled token creation URL — read-only scope, named "SIQspeak"
TOKEN_URL = (
    "https://huggingface.co/settings/tokens/new"
    "?tokenName=SIQspeak&globalPermissions=read"
)
SIGNUP_URL = "https://huggingface.co/join"


def has_token() -> bool:
    """Check if a HuggingFace token exists locally."""
    try:
        from huggingface_hub import HfFolder
        token = HfFolder.get_token()
        return token is not None and len(token.strip()) > 0
    except Exception:
        return False


def get_token() -> str | None:
    """Return the stored HF token, or None."""
    try:
        from huggingface_hub import HfFolder
        return HfFolder.get_token()
    except Exception:
        return None


def validate_token(token: str | None = None) -> str | None:
    """Validate a token (or the stored one). Returns username on success, None on failure."""
    try:
        from huggingface_hub import whoami
        if token:
            info = whoami(token=token)
        else:
            info = whoami()
        username = info.get("name") or info.get("fullname") or "authenticated"
        log.info("HF token valid — user: %s", username)
        return username
    except Exception as e:
        log.warning("HF token validation failed: %s", e)
        return None


def save_token(token: str) -> bool:
    """Save and validate a HuggingFace token. Returns True on success."""
    token = token.strip()
    if not token:
        return False

    # Validate before saving
    username = validate_token(token)
    if not username:
        return False

    try:
        from huggingface_hub import login
        login(token=token, add_to_git_credential=False)
        log.info("HF token saved for user: %s", username)
        return True
    except Exception as e:
        log.error("Failed to save HF token: %s", e)
        return False


def open_signup() -> None:
    """Open HuggingFace signup page in the default browser."""
    log.info("Opening HF signup: %s", SIGNUP_URL)
    webbrowser.open(SIGNUP_URL)


def open_token_page() -> None:
    """Open HuggingFace token creation page in the default browser."""
    log.info("Opening HF token page: %s", TOKEN_URL)
    webbrowser.open(TOKEN_URL)


def is_auth_error(exc: Exception) -> bool:
    """Check if an exception indicates an authentication/authorization failure."""
    msg = str(exc).lower()
    auth_indicators = [
        "401",
        "403",
        "unauthorized",
        "forbidden",
        "authentication",
        "access denied",
        "gated repo",
        "log in",
        "token",
    ]
    return any(ind in msg for ind in auth_indicators)
