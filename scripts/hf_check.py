"""Check if a valid HuggingFace token exists. Used by setup.bat.

Exit codes: 0 = valid token exists, 1 = no token or invalid
"""

import sys


def main():
    try:
        from huggingface_hub import HfFolder
        token = HfFolder.get_token()
        if not token:
            return 1
    except Exception:
        return 1

    try:
        from huggingface_hub import whoami
        info = whoami()
        username = info.get("name", "unknown")
        print(f"   [OK] Already signed in as: {username}")
        return 0
    except Exception:
        return 1


if __name__ == "__main__":
    sys.exit(main())
