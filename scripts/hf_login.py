"""Validate and save a HuggingFace token. Used by setup.bat.

Usage: python scripts/hf_login.py <token>
Exit codes: 0 = success, 1 = invalid/failed
"""

import sys


def main():
    if len(sys.argv) < 2:
        print("   [!] No token provided.")
        return 1

    token = sys.argv[1].strip()

    if not token.startswith("hf_"):
        print("   [!] Token should start with hf_")
        print("       Make sure you copied the full token from HuggingFace.")
        return 1

    try:
        from huggingface_hub import whoami
        info = whoami(token=token)
        username = info.get("name", "unknown")
    except Exception as e:
        print(f"   [!] Token validation failed: {e}")
        print("       Check that you copied the full token and try again.")
        return 1

    try:
        from huggingface_hub import login
        login(token=token, add_to_git_credential=False)
        print(f"   [OK] Signed in as: {username}")
        print("   [OK] Token saved. You will not need to do this again.")
        return 0
    except Exception as e:
        print(f"   [!] Token save failed: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
