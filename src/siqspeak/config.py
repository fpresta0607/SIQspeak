from __future__ import annotations

import base64
import ctypes
import functools
import io
import json
import logging
import os
import sys
from typing import TYPE_CHECKING

from PIL import Image

if TYPE_CHECKING:
    from siqspeak.state import AppState

log = logging.getLogger("siqspeak")

# ---------------------------------------------------------------------------
# Project root detection
# ---------------------------------------------------------------------------


def _find_project_root() -> str:
    # When running as frozen exe, use the exe's directory for config/logs
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    # When running as package, find the root by looking for dictate.ico
    d = os.getcwd()
    if os.path.exists(os.path.join(d, "dictate.ico")):
        return d
    # Fallback: directory containing this file's grandparent (src/siqspeak/config.py -> root)
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


SCRIPT_DIR = _find_project_root()

# ---------------------------------------------------------------------------
# Config persistence
# ---------------------------------------------------------------------------
CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.json")

# Log persistence
LOG_FILE_PATH = os.path.join(SCRIPT_DIR, "transcriptions.jsonl")

# ---------------------------------------------------------------------------
# Model / transcription config
# ---------------------------------------------------------------------------
MODEL_NAME = "base.en"
SAMPLE_RATE = 16000

# Local prompt enhancement (optional, opt-in)
ENHANCEMENT_MODEL = "qwen3.5:2b"
ENHANCEMENT_MODELS = ("qwen3.5:2b", "qwen3.5:4b")

# Streaming transcription (type-as-you-talk)
STREAM_MODE = False                 # opt-in; toggled via settings panel
SILENCE_RMS_THRESHOLD = 0.015       # raw RMS below this = silence
SILENCE_DURATION = 0.7              # seconds of silence before dispatching chunk
MIN_CHUNK_DURATION = 0.5            # minimum audio length (seconds) to transcribe


# ---------------------------------------------------------------------------
# Win32 hotkey: Ctrl+Shift+Space (via low-level keyboard hook)
# ---------------------------------------------------------------------------
VK_SHIFT = 0x10            # either Shift key
VK_SPACE = 0x20            # Space bar
VK_CONTROL = 0x11          # either Ctrl key

# ---------------------------------------------------------------------------
# Color palette (matches dictate.ico: dark blue, cyan, gray, white)
# ---------------------------------------------------------------------------
DARK_BLUE = (20, 40, 80)
CYAN = (0, 200, 220)
GRAY = (140, 140, 150)
WHITE = (230, 240, 255)
PILL_BG = (15, 20, 35)
PILL_BG_ALPHA = 1.0

TRAY_COLORS = {
    "gray": (*GRAY, 255),
    "cyan": (*CYAN, 255),
    "blue": (*DARK_BLUE, 255),
}
STATE_TRAY_COLOR = {"idle": "gray", "recording": "cyan", "transcribing": "blue"}

# ---------------------------------------------------------------------------
# Embedded Lucide-style icons (96x96 white-on-transparent PNGs, bold strokes)
# Rendered at high res for crisp LANCZOS downscaling to display size.
# ---------------------------------------------------------------------------
_ICON_INFO_B64 = "iVBORw0KGgoAAAANSUhEUgAAAGAAAABgCAYAAADimHc4AAACiklEQVR4nO2d227EMAhETdT//2UqVdUqajeb2AYP4DnvG5sZ42xu0BohhJBdkZYAVdWR34lI+PikkuAZDZHKgmcwRHYUPpIRsrPwEYxYOmBU4ZFGSBbhpVMUxJhDY3gPMCKEOAUeaS6v43sduDdYWbz/RpkffKUJ+K8geq6CCggtfJR5y+ogogmPjkF2XvUR4pk+QIVVj4ztaM54iq8nPI4f/jrgLnDE/3lxGNMzziOb+AjuYpnJwCOb+HozNmo7Gh2324CdVv4KE0xPwpXF94rxiHzyGxlnyT+XD2P0ZsGRSfxIWJnw1RIHr6dAsy6CR5Pm6vfTZuoknHXVWeJ+KyLLc9yIPNFuOAO4+hfciuDqn+dOw6EM4Oq30+TSAK5+Oz5peWRd/Xp6DuD5TMBbG/cHMh7ohdgRTChvgIJuRy814CqIKNtPZK40utI0XQZUgwaAoQHRDMh2EsvEO20fZwBPwM/p0YpbEBgaAIYGgKEBYGgAGBoAhgaAoQFgaAAYGgCGBoAxeTmXjGv1zwDedPPjnbbcgsDQADA0IKIBvU/2yfgbJcwAMDQAjPl3wjujlt8J83rAjk9aupQq2BH1KFXALJjnTkO3aik7oZ7VUpgF47h/J8wsaNMaHKuLU1RCDepn8EIMjMnLuTtmgRpVj+nKAJpgX7zEdAvaIRPUOEbz74Qrm6AO9fJcShV4miCgkmVexQrdqqUgTJBk4v/8tk1SvYylOsfnfh2Q+ZygC+bO8vXZy9dXK2WvGRs4VGjmoBVamERpjJNprmxjVbGNVdTmaRpoLq/jtwWwleE1obvXoSjXzDOLEVK9nW1UI2S3hs5/UbY0j4Um7gvWS7gJWRoSUXBCCCGk/fINNEe8jLUjW4wAAAAASUVORK5CYII="
_ICON_HEXAGON_B64 = "iVBORw0KGgoAAAANSUhEUgAAAGAAAABgCAYAAADimHc4AAABWUlEQVR42u3dO3KEMBREUXrK+98yjpxM5gDeR+duANRXoCoota4LAAAAAAAM4r7ve/L9Z1PwSUJA8YyfJiFbXzdTRGT7e767iJywwHaWkMnBfwc7cX3IhuAnL9TZurhOkZAts36qiGwNfoqIbA/+v9d+W0ROCL7z05CTgu8oIj4b1IrIabO+m4ScHny1iAi+VkQEXyshfo7UjvPz2Oq+JPy/sTw1ns+km+0gor0AEEAACCAABBAAAggAAQSAAAJAAAEggAAQQAAIIAAEEAACCCAABBAAAggAAQSAAAIwW8D0Hs+3x/bz5I2eskvy6r5R2z7hF6oKOnbxrN8pv/FpGNkVsUHEiraUqSLW9QVNWR9WN2Z1fhqO6ozrFMDRrYnVIvSGFs1KzblFQemOLhShPb1IhPMDitaHyZ8/nCFDgFOUrk3f6af9e/hsai/c2tboLEkAAAAAwB5+AfUSGJCBCSObAAAAAElFTkSuQmCC"
_ICON_GEAR_B64 = "iVBORw0KGgoAAAANSUhEUgAAAGAAAABgCAYAAADimHc4AAADAUlEQVR4nO2d246DMAxEcbX//8teUWmliqWQpLZn0sx5LrHx2CHkQrdNCCGEEEKIdXF3/0Zbd/wgjTswEK+2zcxQfhhb0C05GGj7Rx6VxgSBAHcZ5ondElv276gCwEAEQFSBE2b/jioADEyAyipw0uzfUQWAgSk/kp3eWBU91yCz/2l/A+PgaQG0APAuyJDTAODgUwiwOnABnGRCDgW0BL0zAK1dRla7GUAMj4xmZrI39XR0ZiCQtt/aqzTGMiZ3Ej+etqoMXd20gfpgBp8eq9xor+2qEVKTAJ84wxr8bBFar330NNjrEHvwM0TojdOtAMfGRoRgDn6UT2dxaRp1tTQ84vy76xiDP+p3xLA25CF8VH/W4F/5eLy/qId02apU1VutFb89t3DlE3RnXEZA/n43Q7XtpExu/TPyQTD8y20/WhtCZJQHdAOIKeeeeKVnx6hwHhy4bD9G2zfGh6IPtsnkSyth3cqZo9E3bAELMlE+RXXJ8CXJV67eH3pu+Or3DMuQtAKc8UmmzTAUpRHAFz2iFDYVkZF9RtxGlIgUFeCAjGSpAgoBsvtv5mcBrQCrIAHASAAwEgCMBABDK4AXnhHbVhfAEJtiSYamIQJkvSk6cRtfNxtqlRtiSbKfSgDk9kAkVALYxRx+TzCvfs+U/Ttakpx1SVKL8oBF+dE+Fb0zwort99hrPh+A2l+zEbTRS0+8ptkb6sVHT7U39E1AmQ7YRRByPqA1SLMEx2/8H4lJ+lTEq6FZ9uSc0ZI8kXtlhyugxYHZKsEB93pbAccGItRnrAQP2Ip+Fqu765q7oJHAM5zDrd5L2r2NciuA+biqg30rmYxjrQQnSAx9rAO9NrEVE3G2dkbbb+1tALJnUtH2eqB9AGadkPmk3QzgL0Su74ZiMdLvBS25JrwicAGc9D2gCvpvRVjyx7vRUI+CbLIvrEzZBa0OTIDKrDTgPzfdoQoAAxEA0ScbaRWoAsCUC4AckRhhFagCwFC9Bxjo6+kMc0JwfNGvpQghhBBCCLHV8wsqGXiPLBVKzgAAAABJRU5ErkJggg=="


@functools.lru_cache(maxsize=32)
def _load_icon(b64: str, size: tuple[int, int], color: tuple[int, int, int]) -> Image.Image:
    """Decode a base64 PNG, resize it, and tint to the given RGB color (cached)."""
    data = base64.b64decode(b64)
    img = Image.open(io.BytesIO(data)).convert("RGBA").resize(size, Image.Resampling.LANCZOS)
    # Tint: use source alpha, replace RGB with target color
    _r, _g, _b, a = img.split()
    img = Image.merge("RGBA", (
        a.point(lambda p: int(p / 255 * color[0])),
        a.point(lambda p: int(p / 255 * color[1])),
        a.point(lambda p: int(p / 255 * color[2])),
        a,
    ))
    return img.copy()


# ---------------------------------------------------------------------------
# Overlay dimensions
# ---------------------------------------------------------------------------
# Idle: 3-icon toolbar (info, model, settings)
IDLE_W = 160
IDLE_H = 44
IDLE_ICON_ZONE_W = 52  # each icon zone width

# Active: compact pill with 6 dots
ACTIVE_W = 180
ACTIVE_H = 44
NUM_DOTS = 6
DOT_R = 3.5
DOT_SPACING = 20.0
DOT_START_X = (ACTIVE_W - (NUM_DOTS - 1) * DOT_SPACING) / 2
DOT_Y = ACTIVE_H / 2.0

# Log panel
LOG_PANEL_MAX_VISIBLE = 50
LOG_PANEL_PADDING = 16
LOG_PANEL_BG_ALPHA = 0.94

# Log persistence
LOG_IN_MEMORY_CAP = 50
LOG_FILE_MAX_ENTRIES = 500

# Model selector panel
MODEL_PANEL_ROW_H = 62
MODEL_PANEL_HEADER_H = 52
SPEECH_MODELS = (
    {"name": "tiny.en", "tier": "Fastest", "size_mb": 75},
    {"name": "base.en", "tier": "Default", "size_mb": 141},
    {"name": "small.en", "tier": "Balanced", "size_mb": 464},
    {"name": "distil-medium.en", "tier": "High Quality", "size_mb": 755},
    {"name": "distil-large-v3.5", "tier": "Best Quality", "size_mb": 1446},
)
AVAILABLE_MODELS = tuple(model["name"] for model in SPEECH_MODELS)
MODEL_SIZES_MB = {model["name"]: model["size_mb"] for model in SPEECH_MODELS}

# Settings panel
SETTINGS_HEADER_H = 52

# Log panel rendering
LOG_HEADER_H = 72
LOG_LINE_H = 26

# History cards (stable, Fluent-inspired — no hover state)
LOG_CARD_MARGIN_X = 16    # card left/right inset from panel edge
LOG_CARD_PAD_X = 14       # card inner horizontal padding
LOG_CARD_PAD_Y = 12       # card inner vertical padding
LOG_CARD_GAP = 12         # vertical space between cards
LOG_CARD_RADIUS = 10
LOG_META_H = 20           # metadata row height (timestamp + Enhanced badge)
LOG_META_GAP = 6          # gap between primary text and metadata row
LOG_COPY_BTN_W = 40       # copy hit-column width at the card's right edge

LOG_CARD_FILL = (26, 33, 52)      # subtle raised card fill over PILL_BG
LOG_CARD_BORDER = (48, 58, 84)    # hairline card border
LOG_BADGE_FILL = (16, 46, 54)     # Enhanced badge background (cyan-tinted)
LOG_COPY_IDLE = (110, 120, 140)   # low-contrast always-visible copy icon
LOG_COPIED_GREEN = (40, 220, 80)

COPY_CONFIRM_SECONDS = 1.5

# Dot color mapping (recording/transcribing)
DOT_COLOR = {"recording": CYAN, "transcribing": WHITE}

# Welcome tooltip
WELCOME_W = 320
WELCOME_H = 70

# Zone-to-panel mapping
_ZONE_PANEL = {0: "info", 1: "model", 2: "settings"}

# Drag threshold (pixels of movement before click becomes a drag)
_DRAG_THRESHOLD = 5

# Win32 message constants
WM_TIMER = 0x0113
WM_APP_STATE = 0x8002  # custom message for overlay state transitions

# State codes for WM_APP_STATE wParam (PostThreadMessageW)
STATE_CODE: dict[str, int] = {"idle": 0, "recording": 1, "transcribing": 2, "enhancing": 3}
STATE_NAME: dict[int, str] = {0: "idle", 1: "recording", 2: "transcribing", 3: "enhancing"}


# ---------------------------------------------------------------------------
# Screen-adaptive dimension functions
# ---------------------------------------------------------------------------
def _screen_size() -> tuple[int, int]:
    """Get primary screen width and height."""
    user32 = ctypes.windll.user32
    return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)


def _log_panel_dims() -> tuple[int, int]:
    """Compute log panel width and max height based on screen size."""
    sw, sh = _screen_size()
    w = max(580, min(int(sw * 0.50), 1000))
    h = max(400, min(int(sh * 0.65), 1000))
    return w, h


def _model_panel_width() -> int:
    sw, _ = _screen_size()
    return max(380, min(int(sw * 0.30), 520))


def _settings_panel_width() -> int:
    sw, _ = _screen_size()
    return max(380, min(int(sw * 0.30), 520))


# ---------------------------------------------------------------------------
# Config persistence
# ---------------------------------------------------------------------------
def _load_config() -> dict:
    """Load config.json, return empty dict if missing/corrupt."""
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def save_config(values: dict) -> None:
    """Persist settings to config.json."""
    try:
        with open(CONFIG_PATH, "w") as f:
            json.dump(values, f, indent=2)
    except OSError:
        log.exception("Failed to save config")


def save_state_config(state: AppState) -> None:
    """Persist current state values to config.json."""
    save_config({
        "model": state.loaded_model_name,
        "stream_mode": state.stream_mode,
        "pill_x": state.pill_user_x,
        "pill_y": state.pill_user_y,
        "mic_device": state.mic_device,
        "enhancement_enabled": state.enhancement_enabled,
        "enhancement_model": state.enhancement_model,
        "workspace_override": state.workspace_override,
    })
