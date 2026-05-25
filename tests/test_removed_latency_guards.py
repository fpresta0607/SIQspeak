"""Source guards for removed latency-heavy transcription features."""
from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(("relative_path", "forbidden"), [
    (
        "src/siqspeak/audio/recording.py",
        ("postprocess_transcription", "Deduplicate words at VAD segment boundaries"),
    ),
    (
        "src/siqspeak/audio/streaming.py",
        (
            "postprocess_transcription",
            "def _strip_overlap",
            "_strip_overlap(",
            "_HALLUCINATION_PATTERNS",
            "prev_chunk_tail",
            "device_settings",
            "cublas",
            "cuda",
        ),
    ),
    (
        "src/siqspeak/config.py",
        ("_HALLUCINATION_PATTERNS", "OVERLAP_FRAMES", "OVERLAP_TAIL_WORDS", "DEFAULT_HAS_CUDA", "device_settings"),
    ),
    ("src/siqspeak/state.py", ("has_cuda", "prev_chunk_tail")),
    ("src/siqspeak/app.py", ("ctranslate2", "has_cuda", "device_settings", "cuda", "CUDA")),
    ("src/siqspeak/model/manager.py", ("device_settings", "cuda", "CUDA")),
    ("src/siqspeak/interaction/click_handlers.py", ("device_settings", "GPU", "has_cuda")),
    ("src/siqspeak/overlay/panels/settings_panel.py", ("Use GPU", "has_cuda")),
    ("setup.bat", ("nvidia-smi", "nvidia-cublas-cu12", "nvidia-cudnn-cu12", "GPU acceleration")),
])
def test_removed_latency_feature_strings_stay_removed(relative_path: str, forbidden: tuple[str, ...]) -> None:
    text = (ROOT / relative_path).read_text(encoding="utf-8")

    found = [token for token in forbidden if token in text]

    assert found == []
