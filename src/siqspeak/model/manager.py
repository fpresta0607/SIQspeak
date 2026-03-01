from __future__ import annotations

import logging
import threading
import time

from faster_whisper import WhisperModel

from siqspeak.config import MODEL_SIZES_MB, save_config
from siqspeak.state import AppState

log = logging.getLogger("siqspeak")


def _is_model_cached(name: str) -> bool:
    """Check if a Whisper model is already downloaded in the HF cache."""
    from faster_whisper.utils import _MODELS
    from huggingface_hub import try_to_load_from_cache

    repo_id = _MODELS.get(name)
    if not repo_id:
        return False
    result = try_to_load_from_cache(repo_id, "model.bin")
    return isinstance(result, str)


def _check_internet() -> bool:
    """Quick connectivity check to Hugging Face Hub."""
    import urllib.request

    try:
        urllib.request.urlopen("https://huggingface.co", timeout=3)
        return True
    except Exception:
        return False


class _DownloadProgress:
    """tqdm-compatible class that writes download progress to state."""

    def __init__(self, *args, state: AppState | None = None, **kwargs):
        self._state = state
        self.total = kwargs.get("total", 0) or 0
        self.n = 0
        if self._state:
            self._state.download_progress = 0.0

    def update(self, n=1):
        self.n += n
        if self.total > 0 and self._state:
            self._state.download_progress = min(self.n / self.total, 1.0)

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def _save_state_config(state: AppState) -> None:
    """Persist current state values to config.json."""
    save_config({
        "model": state.loaded_model_name,
        "stream_mode": state.stream_mode,
        "pill_x": state.pill_user_x,
        "pill_y": state.pill_user_y,
        "device": state.device,
        "mic_device": state.mic_device,
    })


def _start_model_load(state: AppState, name: str) -> None:
    """Spawn a background thread to load a new Whisper model."""
    if state.model_loading:
        return
    state.model_loading = True
    state.model_loading_name = name
    log.info("Loading model: %s", name)

    def _load():
        try:
            new_model = WhisperModel(name, device=state.device, compute_type=state.compute_type)
            # Validate CUDA actually works by running minimal inference
            if state.device == "cuda":
                import numpy as np
                _silence = np.zeros(16000, dtype=np.float32)
                list(new_model.transcribe(_silence, beam_size=1)[0])
            state.model = new_model
            state.loaded_model_name = name
            _save_state_config(state)
            log.info("Model loaded: %s on %s", name, state.device)
        except Exception:
            if state.device == "cuda":
                log.warning("CUDA unavailable, falling back to CPU")
                state.device = "cpu"
                state.compute_type = "int8"
                try:
                    new_model = WhisperModel(name, device="cpu", compute_type="int8")
                    state.model = new_model
                    state.loaded_model_name = name
                    _save_state_config(state)
                    log.info("Model loaded: %s on cpu (CUDA fallback)", name)
                except Exception:
                    log.exception("Failed to load model %s", name)
            else:
                log.exception("Failed to load model %s", name)
        finally:
            state.model_loading = False

    threading.Thread(target=_load, daemon=True).start()


def _start_model_download_and_load(state: AppState, name: str) -> None:
    """Download a model from HF Hub, then load it."""
    if state.model_loading:
        return
    state.model_loading = True
    state.model_loading_name = name
    state.download_progress = 0.0
    state.download_error = None
    log.info("Downloading model: %s (~%d MB)", name, MODEL_SIZES_MB.get(name, 0))

    def _download_and_load():
        # Internet check
        if not _check_internet():
            state.download_error = "No internet"
            state.download_error_time = time.time()
            log.warning("No internet for model download: %s", name)
            state.model_loading = False
            return

        try:
            import huggingface_hub
            from faster_whisper.utils import _MODELS

            repo_id = _MODELS[name]
            allow_patterns = [
                "config.json", "preprocessor_config.json",
                "model.bin", "tokenizer.json", "vocabulary.*",
            ]

            # Build a tqdm_class factory that passes state through
            def _progress_factory(*args, **kwargs):
                return _DownloadProgress(*args, state=state, **kwargs)

            model_path = huggingface_hub.snapshot_download(
                repo_id, allow_patterns=allow_patterns,
                tqdm_class=_progress_factory,
            )
            state.download_progress = 1.0
            log.info("Download complete: %s, loading...", name)

            new_model = WhisperModel(model_path, device=state.device, compute_type=state.compute_type)
            state.model = new_model
            state.loaded_model_name = name
            _save_state_config(state)
            log.info("Model loaded: %s on %s", name, state.device)
        except Exception:
            state.download_error = "Download failed"
            state.download_error_time = time.time()
            log.exception("Failed to download/load model %s", name)
        finally:
            state.model_loading = False

    threading.Thread(target=_download_and_load, daemon=True).start()
