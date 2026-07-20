from __future__ import annotations

import errno
import logging
import threading
import time

from faster_whisper import WhisperModel
from tqdm.auto import tqdm as _Tqdm

from siqspeak._frozen import bundled_model_path
from siqspeak.config import MODEL_SIZES_MB, save_state_config
from siqspeak.state import AppState

log = logging.getLogger("siqspeak")

# Public faster-whisper repos only need anonymous downloads.
_ALLOW_PATTERNS = [
    "config.json",
    "preprocessor_config.json",
    "model.bin",
    "tokenizer.json",
    "vocabulary.*",
]


def _is_model_cached(name: str) -> bool:
    """Check if a Whisper model is already downloaded in the HF cache."""
    from faster_whisper.utils import _MODELS
    from huggingface_hub import try_to_load_from_cache

    repo_id = _MODELS.get(name)
    if not repo_id:
        return False
    result = try_to_load_from_cache(repo_id, "model.bin")
    return isinstance(result, str)


def _make_progress_class(state: AppState) -> type[_Tqdm]:
    """Return a tqdm subclass that mirrors download progress onto ``state``.

    Subclassing tqdm keeps it compatible with ``snapshot_download``'s
    ``tqdm_class`` contract (``get_lock``/``set_lock`` and the full API) while
    reporting a determinate fraction to the model panel.
    """

    class _StateProgress(_Tqdm):
        def update(self, n: float | None = 1) -> bool | None:
            displayed = super().update(n)
            if self.total:
                state.download_progress = min(self.n / self.total, 1.0)
            return displayed

    return _StateProgress


def _classify_download_error(exc: BaseException) -> str:
    """Map a download exception to a short, actionable message for the panel."""
    if isinstance(exc, OSError) and getattr(exc, "errno", None) == errno.ENOSPC:
        return "Not enough disk space"
    if isinstance(exc, (ConnectionError, TimeoutError)):
        return "Network error - check connection"
    text = f"{type(exc).__name__} {exc}".lower()
    if any(token in text for token in ("connection", "timeout", "network", "url", "dns", "resolve")):
        return "Network error - check connection"
    return "Download failed"


def _start_model_load(state: AppState, name: str) -> None:
    """Spawn a background thread to load an already-available Whisper model."""
    if state.model_loading:
        return
    state.model_loading = True
    state.model_loading_name = name
    state.model_loading_start = time.time()
    state.model_loading_is_download = False
    log.info("Loading model: %s", name)

    def _load() -> None:
        try:
            # Use bundled model path if available (frozen/installer build)
            model_path = bundled_model_path(name) or name
            new_model = WhisperModel(model_path, device=state.device, compute_type=state.compute_type)
            state.model = new_model
            state.loaded_model_name = name
            state.download_error = None
            save_state_config(state)
            log.info("Model loaded: %s on %s", name, state.device)
        except Exception:
            log.exception("Failed to load model %s", name)
        finally:
            state.model_loading = False

    try:
        threading.Thread(target=_load, daemon=True).start()
    except Exception:
        log.exception("Failed to start model load thread")
        state.model_loading = False


def _start_model_download_and_load(state: AppState, name: str) -> None:
    """Anonymously download a public model from the HF Hub, then load it."""
    if state.model_loading:
        return
    state.model_loading = True
    state.model_loading_name = name
    state.model_loading_start = time.time()
    state.model_loading_is_download = True
    state.download_progress = 0.0
    state.download_error = None
    log.info("Downloading model: %s (~%d MB)", name, MODEL_SIZES_MB.get(name, 0))

    try:
        threading.Thread(target=_download_and_load, args=(state, name), daemon=True).start()
    except Exception:
        log.exception("Failed to start model download thread")
        state.model_loading = False


def _download_and_load(state: AppState, name: str) -> None:
    """Download a public model snapshot and load it. Runs on a worker thread."""
    try:
        import huggingface_hub
        from faster_whisper.utils import _MODELS

        repo_id = _MODELS[name]
        model_path = huggingface_hub.snapshot_download(
            repo_id,
            allow_patterns=_ALLOW_PATTERNS,
            tqdm_class=_make_progress_class(state),
        )

        state.download_progress = 1.0
        log.info("Download complete: %s, loading...", name)

        new_model = WhisperModel(model_path, device=state.device, compute_type=state.compute_type)
        state.model = new_model
        state.loaded_model_name = name
        state.download_error = None
        save_state_config(state)
        log.info("Model loaded: %s on %s", name, state.device)
    except Exception as exc:
        state.download_error = _classify_download_error(exc)
        state.download_error_time = time.time()
        log.exception("Failed to download/load model %s", name)
    finally:
        state.model_loading = False
