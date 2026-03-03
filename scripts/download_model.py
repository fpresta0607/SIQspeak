"""Pre-download the default Whisper model for bundling into the installer."""

import os
import sys

def main():
    model_name = sys.argv[1] if len(sys.argv) > 1 else "tiny"
    print(f"Downloading Whisper model: {model_name}")

    from faster_whisper import WhisperModel

    # This triggers the HuggingFace download to the default cache dir
    model = WhisperModel(model_name, device="cpu", compute_type="int8")
    del model

    # Find the cached model path
    from faster_whisper.utils import _MODELS
    from huggingface_hub import snapshot_download

    repo_id = _MODELS.get(model_name)
    if not repo_id:
        print(f"Unknown model: {model_name}")
        sys.exit(1)

    cache_dir = snapshot_download(repo_id, local_files_only=True)
    print(f"Model cached at: {cache_dir}")
    print("Done.")

if __name__ == "__main__":
    main()
