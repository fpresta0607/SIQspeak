from __future__ import annotations

import logging
import threading
import time

from faster_whisper import WhisperModel

from siqspeak._frozen import bundled_model_path
from siqspeak.config import MODEL_SIZES_MB, device_settings, save_state_config
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


def _direct_download_model(name: str, state=None) -> str | None:
    """Download model files directly from HuggingFace CDN without hub auth.
    
    Falls back to raw URL downloads when huggingface_hub auth fails.
    Returns the model directory path, or None on failure.
    """
    import os
    import urllib.request

    from faster_whisper.utils import _MODELS

    repo_id = _MODELS.get(name)
    if not repo_id:
        return None

    # e.g. "Systran/faster-whisper-tiny" -> cache dir
    cache_base = os.path.join(os.path.expanduser("~"), ".cache", "huggingface", "hub")
    safe_repo = repo_id.replace("/", "--")
    model_dir = os.path.join(cache_base, f"models--{safe_repo}", "snapshots", "main")
    os.makedirs(model_dir, exist_ok=True)

    base_url = f"https://huggingface.co/{repo_id}/resolve/main"
    files = ["model.bin", "config.json", "tokenizer.json", "preprocessor_config.json", "vocabulary.json", "vocabulary.txt"]

    for fname in files:
        dest = os.path.join(model_dir, fname)
        if os.path.exists(dest):
            continue
        url = f"{base_url}/{fname}"
        try:
            log.info("Direct downloading %s/%s", repo_id, fname)
            urllib.request.urlretrieve(url, dest)
        except Exception as e:
            log.warning("Direct download failed for %s: %s", fname, e)
            # model.bin is required, others are optional
            if fname == "model.bin":
                return None

    # Verify model.bin exists
    if os.path.exists(os.path.join(model_dir, "model.bin")):
        log.info("Direct download complete: %s", model_dir)
        return model_dir
    return None


def _make_progress_class(state: AppState):
    """Build a tqdm-compatible class that reports download progress to state.

    Returns a *class* (not an instance) because huggingface_hub's
    ``snapshot_download`` passes ``tqdm_class`` to ``tqdm.contrib.concurrent.thread_map``
    which calls ``tqdm_class.get_lock()`` — a plain function doesn't have that.
    """

    class _Progress:
        _lock = threading.Lock()

        @classmethod
        def get_lock(cls):
            return cls._lock

        @classmethod
        def set_lock(cls, lock):
            cls._lock = lock

        def __init__(self, iterable=None, *args, **kwargs):
            self._iterable = iterable
            self.total = kwargs.get("total", 0) or 0
            self.n = kwargs.get("initial", 0) or 0
            state.download_progress = 0.0

        def __iter__(self):
            if self._iterable is None:
                return
            for obj in self._iterable:
                yield obj
                self.update(1)

        def update(self, n=1):
            self.n += n
            if self.total > 0:
                state.download_progress = min(self.n / self.total, 1.0)

        def close(self):
            pass

        def refresh(self):
            pass

        def set_description(self, desc=None):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.close()

    return _Progress


def _start_model_load(state: AppState, name: str) -> None:
    """Spawn a background thread to load a new Whisper model."""
    if state.model_loading:
        return
    state.model_loading = True
    state.model_loading_name = name
    state.model_loading_start = time.time()
    state.model_loading_is_download = False
    state.model_hover_row = None
    log.info("Loading model: %s", name)

    def _load():
        try:
            # Use bundled model path if available (frozen/installer build)
            model_path = bundled_model_path(name) or name
            new_model = WhisperModel(model_path, device=state.device, compute_type=state.compute_type)
            # Validate CUDA actually works by running minimal inference
            if state.device == "cuda":
                import numpy as np
                _silence = np.zeros(16000, dtype=np.float32)
                list(new_model.transcribe(_silence, beam_size=1)[0])
            state.model = new_model
            state.loaded_model_name = name
            save_state_config(state)
            log.info("Model loaded: %s on %s", name, state.device)
        except Exception:
            if state.device == "cuda":
                log.warning("CUDA unavailable, falling back to CPU")
                state.device, state.compute_type = device_settings(False)
                try:
                    new_model = WhisperModel(name, device=state.device, compute_type=state.compute_type)
                    state.model = new_model
                    state.loaded_model_name = name
                    save_state_config(state)
                    log.info("Model loaded: %s on cpu (CUDA fallback)", name)
                except Exception:
                    log.exception("Failed to load model %s", name)
            else:
                log.exception("Failed to load model %s", name)
        finally:
            state.model_loading = False

    try:
        threading.Thread(target=_load, daemon=True).start()
    except Exception:
        log.exception("Failed to start model load thread")
        state.model_loading = False


def _start_model_download_and_load(state: AppState, name: str) -> None:
    """Download a model from HF Hub, then load it."""
    if state.model_loading:
        return
    state.model_loading = True
    state.model_loading_name = name
    state.model_loading_start = time.time()
    state.model_loading_is_download = True
    state.model_hover_row = None
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

            model_path = None
            try:
                model_path = huggingface_hub.snapshot_download(
                    repo_id, allow_patterns=allow_patterns,
                    tqdm_class=_make_progress_class(state),
                )
            except Exception as hub_err:
                log.warning("HF Hub download failed (%s), trying direct download...", hub_err)
                model_path = _direct_download_model(name, state)
                if not model_path:
                    raise RuntimeError(f"Both HF Hub and direct download failed for {name}")

            state.download_progress = 1.0
            log.info("Download complete: %s, loading...", name)

            new_model = WhisperModel(model_path, device=state.device, compute_type=state.compute_type)
            # Validate CUDA inference (cuBLAS is only loaded at transcribe time)
            if state.device == "cuda":
                import numpy as np
                _silence = np.zeros(16000, dtype=np.float32)
                list(new_model.transcribe(_silence, beam_size=1)[0])
            state.model = new_model
            state.loaded_model_name = name
            save_state_config(state)
            log.info("Model loaded: %s on %s", name, state.device)
        except Exception:
            if state.device == "cuda":
                log.warning("CUDA unavailable after download, falling back to CPU")
                state.device, state.compute_type = device_settings(False)
                try:
                    new_model = WhisperModel(model_path, device=state.device, compute_type=state.compute_type)
                    state.model = new_model
                    state.loaded_model_name = name
                    save_state_config(state)
                    log.info("Model loaded: %s on cpu (CUDA fallback)", name)
                except Exception:
                    state.download_error = "Load failed"
                    state.download_error_time = time.time()
                    log.exception("Failed to load model %s after CPU fallback", name)
            else:
                state.download_error = "Download failed"
                state.download_error_time = time.time()
                log.exception("Failed to download/load model %s", name)
        finally:
            state.model_loading = False

    try:
        threading.Thread(target=_download_and_load, daemon=True).start()
    except Exception:
        log.exception("Failed to start model download thread")
        state.model_loading = False
