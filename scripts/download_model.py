"""Pre-download a curated Whisper model for bundling into the installer."""
from __future__ import annotations

import sys

from faster_whisper.utils import _MODELS


def main() -> int:
    model_name = sys.argv[1] if len(sys.argv) > 1 else "base.en"

    if model_name not in _MODELS:
        print(f"Unknown model: {model_name}")
        return 1

    print(f"Downloading Whisper model: {model_name}")

    from faster_whisper import WhisperModel

    try:
        # Loading the model triggers an anonymous download into the official
        # Hugging Face cache; we discard the handle once it is cached.
        WhisperModel(model_name, device="cpu", compute_type="int8")
    except Exception as error:
        print(f"Download failed: {error}")
        return 1

    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
