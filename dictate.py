"""
SIQspeak — hold Ctrl+Shift+Space to record, release to transcribe and paste.

Runs silently in the system tray. Gray = idle, Cyan = recording, Blue = transcribing.
Floating pill with 3-icon toolbar (info, model selector, settings); click to toggle panels.
"""

import base64
import ctypes
import ctypes.wintypes
import io
import logging
import math
import os
import queue
import sys
import threading
import time

if sys.executable and sys.executable.endswith("pythonw.exe"):
    sys.stdout = open(os.devnull, "w")
    sys.stderr = open(os.devnull, "w")

import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel
import pyperclip
from PIL import Image, ImageDraw, ImageFont
from pystray import Icon, MenuItem, Menu

# ---------------------------------------------------------------------------
# DPI awareness — must be set before any Win32 calls
# ---------------------------------------------------------------------------
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
except Exception:
    pass

# ---------------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s.%(msecs)03d %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.FileHandler(os.path.join(SCRIPT_DIR, "dictate.log"), encoding="utf-8"),
    ],
)
log = logging.getLogger("dictate")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
MODEL_NAME = "tiny"
SAMPLE_RATE = 16000

# Streaming transcription (type-as-you-talk)
STREAM_MODE = False                 # opt-in; toggled via settings panel
SILENCE_RMS_THRESHOLD = 0.015       # raw RMS below this = silence
SILENCE_DURATION = 0.7              # seconds of silence before dispatching chunk
MIN_CHUNK_DURATION = 0.5            # minimum audio length (seconds) to transcribe

# Known Whisper hallucination phrases (matched after lowercasing + stripping punctuation)
_HALLUCINATION_PATTERNS = {
    "thank you", "thanks for watching", "subscribe",
    "like and subscribe", "see you next time",
    "please subscribe", "you", "bye", "goodbye",
    "thanks for watching and see you next time",
}

# Win32 hotkey: Ctrl+Shift+Space
HOTKEY_ID = 1
HOTKEY_MOD = 0x0002 | 0x0004  # MOD_CONTROL | MOD_SHIFT
VK_SPACE = 0x20

# ---------------------------------------------------------------------------
# Color palette (matches dictate.ico: dark blue, cyan, gray, white)
# ---------------------------------------------------------------------------
DARK_BLUE = (20, 40, 80)
CYAN = (0, 200, 220)
GRAY = (140, 140, 150)
WHITE = (230, 240, 255)
PILL_BG = (15, 20, 35)
PILL_BG_ALPHA = 0.88

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


def _load_icon(b64: str, size: tuple[int, int], color: tuple[int, int, int]) -> Image.Image:
    """Decode a base64 PNG, resize it, and tint to the given RGB color."""
    data = base64.b64decode(b64)
    img = Image.open(io.BytesIO(data)).convert("RGBA").resize(size, Image.LANCZOS)
    # Tint: use source alpha, replace RGB with target color
    r, g, b, a = img.split()
    img = Image.merge("RGBA", (
        a.point(lambda p: int(p / 255 * color[0])),
        a.point(lambda p: int(p / 255 * color[1])),
        a.point(lambda p: int(p / 255 * color[2])),
        a,
    ))
    return img

# ---------------------------------------------------------------------------
# Globals
# ---------------------------------------------------------------------------
is_recording = False
audio_chunks: list[np.ndarray] = []
model: WhisperModel | None = None
icon: Icon | None = None
mic_stream: sd.InputStream | None = None
_target_hwnd = None
_overlay_target_state = "idle"
_should_quit = False
_overlay_hwnd = None
_hotkey_busy = False
_current_level = 0.0   # audio RMS (0..1), written by mic callback
_display_level = 0.0   # smoothed for rendering
_log_panel_hwnd = None
_model_panel_hwnd = None
_settings_panel_hwnd = None
_active_panel: str | None = None  # "info" | "model" | "settings" | None
_transcription_log: list[dict] = []  # {text, timestamp, time_epoch}
_copy_debounce = False
_copy_hover_row: int | None = None   # which log row's copy btn is hovered
_copied_row: int | None = None       # which row just got copied (show checkmark)
_copied_time: float = 0.0            # when the copy happened
_log_entry_heights: list[int] = []   # cached row heights for click hit-testing

# Streaming transcription state
_stream_queue: queue.Queue | None = None
_stream_worker: threading.Thread | None = None
_silence_count = 0                  # consecutive silent audio callbacks
_transcribed_idx = 0                # audio_chunks index: everything before this is dispatched
_stream_focus_done = False          # focus target window only once per session
_stream_texts: list[str] = []       # collect typed texts for transcription log entry
_pill_current_mode = "idle"  # tracks which pill size is displayed

# Drag-to-reposition state
_drag_active = False
_drag_pending = False       # mouse down on pill, waiting to see if it's a drag or click
_drag_start_x = 0
_drag_start_y = 0
_drag_pill_x = 0
_drag_pill_y = 0
_pill_user_x: int | None = None  # user-chosen pill X (None = default center)
_pill_user_y: int | None = None  # user-chosen pill Y (None = default bottom)

_idle_click_debounce = False
_model_click_debounce = False
_settings_click_debounce = False
_model_loading = False
_model_loading_name = ""
_loaded_model_name = MODEL_NAME
_download_progress: float = 0.0
_download_confirm_name: str | None = None
_download_error: str | None = None
_download_error_time: float = 0.0
_welcome_hwnd = None
_welcome_shown = False
_welcome_show_time = 0.0
_hover_zone: int | None = None  # which icon zone (0/1/2) cursor is over


def _set_hover_zone(zone: int | None) -> None:
    global _hover_zone
    _hover_zone = zone

# ---------------------------------------------------------------------------
# Tray icon
# ---------------------------------------------------------------------------


_tray_icon_img: Image.Image | None = None


def _load_tray_icon() -> Image.Image:
    global _tray_icon_img
    if _tray_icon_img is None:
        ico_path = os.path.join(SCRIPT_DIR, "dictate.ico")
        from PIL import ImageFilter
        # Two-step downscale + sharpen for crisp tray icon
        src = Image.open(ico_path).convert("RGBA")
        _tray_icon_img = (
            src.resize((128, 128), Image.LANCZOS)
               .resize((64, 64), Image.LANCZOS)
               .filter(ImageFilter.UnsharpMask(radius=1.0, percent=60, threshold=2))
        )
    return _tray_icon_img


def make_icon(_color: str = "") -> Image.Image:
    return _load_tray_icon()


def set_state(state: str) -> None:
    global _overlay_target_state
    _overlay_target_state = state


# ---------------------------------------------------------------------------
# Win32 structs
# ---------------------------------------------------------------------------
class SIZEL(ctypes.Structure):
    _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [
        ("BlendOp", ctypes.c_ubyte),
        ("BlendFlags", ctypes.c_ubyte),
        ("SourceConstantAlpha", ctypes.c_ubyte),
        ("AlphaFormat", ctypes.c_ubyte),
    ]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", ctypes.wintypes.DWORD),
        ("biWidth", ctypes.c_long),
        ("biHeight", ctypes.c_long),
        ("biPlanes", ctypes.wintypes.WORD),
        ("biBitCount", ctypes.wintypes.WORD),
        ("biCompression", ctypes.wintypes.DWORD),
        ("biSizeImage", ctypes.wintypes.DWORD),
        ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long),
        ("biClrUsed", ctypes.wintypes.DWORD),
        ("biClrImportant", ctypes.wintypes.DWORD),
    ]


INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
VK_CONTROL = 0x11


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.wintypes.WORD),
        ("wScan", ctypes.wintypes.WORD),
        ("dwFlags", ctypes.wintypes.DWORD),
        ("time", ctypes.wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.wintypes.DWORD),
        ("dwFlags", ctypes.wintypes.DWORD),
        ("time", ctypes.wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", ctypes.wintypes.DWORD),
        ("wParamL", ctypes.wintypes.WORD),
        ("wParamH", ctypes.wintypes.WORD),
    ]


class INPUT(ctypes.Structure):
    class _INPUT(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]

    _anonymous_ = ("_input",)
    _fields_ = [
        ("type", ctypes.wintypes.DWORD),
        ("_input", _INPUT),
    ]


# ---------------------------------------------------------------------------
# Text input via SendInput KEYEVENTF_UNICODE (no clipboard needed)
# ---------------------------------------------------------------------------
def type_text(text: str, release_modifiers: bool = True) -> None:
    """Type text into the focused window using Unicode keyboard events."""
    user32 = ctypes.windll.user32

    if release_modifiers:
        # Release any held modifiers first (Ctrl, Shift, Alt from hotkey)
        release = (INPUT * 3)()
        for i, vk in enumerate((VK_CONTROL, 0x10, 0x12)):
            release[i].type = INPUT_KEYBOARD
            release[i].ki.wVk = vk
            release[i].ki.dwFlags = KEYEVENTF_KEYUP
        user32.SendInput(3, ctypes.pointer(release[0]), ctypes.sizeof(INPUT))
        time.sleep(0.05)

    # Send each character as a Unicode key down + key up pair
    n = len(text) * 2
    inputs = (INPUT * n)()
    for i, char in enumerate(text):
        code = ord(char)
        inputs[i * 2].type = INPUT_KEYBOARD
        inputs[i * 2].ki.wVk = 0
        inputs[i * 2].ki.wScan = code
        inputs[i * 2].ki.dwFlags = KEYEVENTF_UNICODE
        inputs[i * 2 + 1].type = INPUT_KEYBOARD
        inputs[i * 2 + 1].ki.wVk = 0
        inputs[i * 2 + 1].ki.wScan = code
        inputs[i * 2 + 1].ki.dwFlags = KEYEVENTF_UNICODE | KEYEVENTF_KEYUP
    user32.SendInput(n, ctypes.pointer(inputs[0]), ctypes.sizeof(INPUT))


def focus_window(hwnd: int) -> None:
    """Bring a window to the foreground reliably."""
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    fg = user32.GetForegroundWindow()
    if fg == hwnd:
        return
    # Alt key trick: grants foreground rights to the calling process
    user32.keybd_event(0x12, 0, 0, 0)         # Alt down
    user32.keybd_event(0x12, 0, 0x0002, 0)    # Alt up
    # AttachThreadInput for cross-thread focus
    our_tid = kernel32.GetCurrentThreadId()
    fg_tid = user32.GetWindowThreadProcessId(fg, None)
    attached = False
    if our_tid != fg_tid:
        user32.AttachThreadInput(our_tid, fg_tid, True)
        attached = True
    user32.SetForegroundWindow(hwnd)
    user32.BringWindowToTop(hwnd)
    if attached:
        user32.AttachThreadInput(our_tid, fg_tid, False)


# ---------------------------------------------------------------------------
# Overlay: idle icon + active pill with audio-reactive dots
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
LOG_PANEL_MAX_VISIBLE = 20
LOG_PANEL_PADDING = 16
LOG_PANEL_BG_ALPHA = 0.94
_log_scroll_offset = 0  # scroll offset (number of entries scrolled)

# Model selector panel
MODEL_PANEL_ROW_H = 62
MODEL_PANEL_HEADER_H = 52
AVAILABLE_MODELS = ["tiny", "base", "small", "medium", "large-v2", "large-v3"]
MODEL_SIZES_MB = {
    "tiny": 75, "base": 141, "small": 464,
    "medium": 1460, "large-v2": 2947, "large-v3": 2948,
}

# Settings panel
SETTINGS_HEADER_H = 52


def _screen_size() -> tuple[int, int]:
    """Get primary screen width and height."""
    user32 = ctypes.windll.user32
    return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)


def _log_panel_dims() -> tuple[int, int]:
    """Compute log panel width and max height based on screen size."""
    sw, sh = _screen_size()
    w = max(500, min(int(sw * 0.45), 900))
    h = max(400, min(int(sh * 0.65), 1000))
    return w, h


def _model_panel_width() -> int:
    sw, _ = _screen_size()
    return max(340, min(int(sw * 0.25), 440))


def _settings_panel_width() -> int:
    sw, _ = _screen_size()
    return max(300, min(int(sw * 0.22), 380))


# ---------------------------------------------------------------------------
# Low-level mouse hook for wheel scroll support
# ---------------------------------------------------------------------------
_wheel_delta = 0  # accumulated wheel delta since last check

class _MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", ctypes.wintypes.POINT),
        ("mouseData", ctypes.wintypes.DWORD),
        ("flags", ctypes.wintypes.DWORD),
        ("time", ctypes.wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]

_HOOKPROC = ctypes.WINFUNCTYPE(
    ctypes.c_long, ctypes.c_int, ctypes.wintypes.WPARAM, ctypes.wintypes.LPARAM
)

def _mouse_hook_proc(nCode, wParam, lParam):
    global _wheel_delta
    try:
        if nCode >= 0 and wParam == 0x020A:  # WM_MOUSEWHEEL
            data = ctypes.cast(lParam, ctypes.POINTER(_MSLLHOOKSTRUCT)).contents
            delta = ctypes.c_short((data.mouseData >> 16) & 0xFFFF).value
            _wheel_delta += delta
    except Exception:
        pass
    return ctypes.windll.user32.CallNextHookEx(_mouse_hook, nCode, wParam, lParam)

# Must prevent GC of the callback
_mouse_hook_callback = _HOOKPROC(_mouse_hook_proc)
_mouse_hook = None


def _make_pill_mask(w: int, h: int) -> np.ndarray:
    """SDF-based rounded rectangle mask."""
    py, px = np.mgrid[:h, :w]
    cx, cy = w / 2.0, h / 2.0
    hw, hh = w / 2.0 - 2, h / 2.0 - 2
    radius = hh  # fully rounded ends
    dx = np.maximum(np.abs(px - cx) - hw + radius, 0).astype(np.float32)
    dy = np.maximum(np.abs(py - cy) - hh + radius, 0).astype(np.float32)
    sdf = np.sqrt(dx ** 2 + dy ** 2) - radius
    return np.clip(0.5 - sdf, 0, 1).astype(np.float32)


def _make_pill_bg(w: int, h: int, mask: np.ndarray) -> np.ndarray:
    """Pre-multiplied alpha BGRA background buffer."""
    bg = np.zeros((h, w, 4), dtype=np.float32)
    alpha = mask * PILL_BG_ALPHA
    bg[:, :, 0] = PILL_BG[2] / 255.0 * alpha  # B
    bg[:, :, 1] = PILL_BG[1] / 255.0 * alpha  # G
    bg[:, :, 2] = PILL_BG[0] / 255.0 * alpha  # R
    bg[:, :, 3] = alpha
    return bg


# Pre-compute active pill mask + background
_active_mask = _make_pill_mask(ACTIVE_W, ACTIVE_H)
_active_bg = _make_pill_bg(ACTIVE_W, ACTIVE_H, _active_mask)

# Pre-compute idle circle mask + background
_idle_mask = _make_pill_mask(IDLE_W, IDLE_H)
_idle_bg = _make_pill_bg(IDLE_W, IDLE_H, _idle_mask)


def _build_idle_frame(hover_zone: int | None = None) -> np.ndarray:
    """Pre-render idle toolbar: 3-icon pill (info | model | settings).
    hover_zone: 0 (info), 1 (model), 2 (settings), or None for no hover.
    """
    buf = _idle_bg.copy()
    img = Image.new("RGBA", (IDLE_W, IDLE_H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Zone centers: 3 zones of IDLE_ICON_ZONE_W each
    zone_w = IDLE_ICON_ZONE_W
    zone_centers = [zone_w // 2, IDLE_W // 2, IDLE_W - zone_w // 2]

    # Zone boundaries for hover highlight
    zone_lefts = [0, zone_w, IDLE_W - zone_w]
    zone_rights = [zone_w, IDLE_W - zone_w, IDLE_W]

    # Draw hover highlight behind the hovered zone
    if hover_zone is not None and 0 <= hover_zone <= 2:
        zl = zone_lefts[hover_zone] + 2
        zr = zone_rights[hover_zone] - 2
        draw.rounded_rectangle(
            [zl, 3, zr, IDLE_H - 3],
            radius=8,
            fill=(255, 255, 255, 25),
        )

    # Separator lines between zones
    for sep_x in [zone_w, IDLE_W - zone_w]:
        draw.line([(sep_x, 10), (sep_x, IDLE_H - 10)], fill=(*GRAY, 60))

    # Icon colors: brighten on hover
    default_colors = [CYAN, WHITE, GRAY]
    hover_colors = [(100, 240, 255), (255, 255, 255), (200, 200, 210)]
    colors = [
        hover_colors[i] if hover_zone == i else default_colors[i]
        for i in range(3)
    ]

    # Load and paste Lucide icons (26x26, centered in each zone)
    icon_size = (26, 26)
    icon_imgs = [
        _load_icon(_ICON_INFO_B64, icon_size, colors[0]),
        _load_icon(_ICON_HEXAGON_B64, icon_size, colors[1]),
        _load_icon(_ICON_GEAR_B64, icon_size, colors[2]),
    ]

    for icon_img, cx in zip(icon_imgs, zone_centers):
        ix = cx - icon_img.width // 2
        iy = IDLE_H // 2 - icon_img.height // 2
        img.paste(icon_img, (ix, iy), icon_img)

    # Composite onto pill background
    pixels = np.array(img, dtype=np.float32) / 255.0
    src_a = pixels[:, :, 3]
    inv = 1.0 - src_a
    for c_src, c_dst in ((2, 0), (1, 1), (0, 2)):
        buf[:, :, c_dst] = pixels[:, :, c_src] * src_a + buf[:, :, c_dst] * inv
    buf[:, :, 3] = src_a + buf[:, :, 3] * inv
    return (buf * 255).clip(0, 255).astype(np.uint8)


def _draw_centered_text(
    draw: ImageDraw.ImageDraw, text: str, cx: int, cy: int,
    font: ImageFont.FreeTypeFont, fill: tuple,
) -> None:
    """Draw text centered at (cx, cy)."""
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = cx - tw // 2 - bbox[0]
    y = cy - th // 2 - bbox[1]
    draw.text((x, y), text, fill=fill, font=font)


DOT_COLOR = {"recording": CYAN, "transcribing": WHITE}


def _render_frame(state: str, phase: float) -> np.ndarray:
    """Render one frame of the active pill (recording/transcribing dots)."""
    global _display_level

    buf = _active_bg.copy()

    # Smooth audio level for display
    _display_level += 0.3 * (_current_level - _display_level)
    level = _display_level

    color = DOT_COLOR.get(state, CYAN)

    for i in range(NUM_DOTS):
        cx = DOT_START_X + i * DOT_SPACING
        cy = DOT_Y

        if state == "recording":
            center_dist = abs(i - (NUM_DOTS - 1) / 2) / ((NUM_DOTS - 1) / 2)
            dot_level = level * (1 - center_dist * 0.4)
            scale = 0.4 + dot_level * 2.2
            bright = 0.35 + dot_level * 0.65
            scale += 0.12 * math.sin(phase * 2.5 + i * 0.5)
        else:
            wave = (math.sin(phase * 3.0 + i * 0.6) + 1) / 2
            scale = 0.5 + wave * 1.2
            bright = 0.35 + wave * 0.65

        r = DOT_R * max(scale, 0.2)

        margin = r + 4
        x1 = max(0, int(cx - margin))
        x2 = min(ACTIVE_W, int(cx + margin + 1))
        y1 = max(0, int(cy - margin))
        y2 = min(ACTIVE_H, int(cy + margin + 1))
        if x1 >= x2 or y1 >= y2:
            continue

        lx = np.arange(x1, x2, dtype=np.float32)
        ly = np.arange(y1, y2, dtype=np.float32)
        gx, gy = np.meshgrid(lx, ly)
        dist = np.sqrt((gx - cx) ** 2 + (gy - cy) ** 2)

        dot_mask = np.clip(1.0 - (dist - r) / 1.2, 0, 1)
        glow_mask = np.clip(1.0 - (dist - r * 1.3) / 3.0, 0, 1) * 0.2
        combined = np.clip(dot_mask + glow_mask, 0, 1)

        src_alpha = combined * bright
        inv = 1.0 - src_alpha
        for c in range(3):
            src_pm = color[c] / 255.0 * src_alpha
            buf[y1:y2, x1:x2, 2 - c] = src_pm + buf[y1:y2, x1:x2, 2 - c] * inv
        buf[y1:y2, x1:x2, 3] = src_alpha + buf[y1:y2, x1:x2, 3] * inv

    return (buf * 255).clip(0, 255).astype(np.uint8)


def _update_layered_window(hwnd: int, buf: np.ndarray, w: int, h: int) -> None:
    """Blit BGRA buffer to a layered window via UpdateLayeredWindow."""
    if not hwnd:
        return
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32

    hdc_screen = user32.GetDC(0)
    hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)

    bmi = BITMAPINFOHEADER()
    bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.biWidth = w
    bmi.biHeight = -h  # top-down
    bmi.biPlanes = 1
    bmi.biBitCount = 32

    bits = ctypes.c_void_p()
    hbm = gdi32.CreateDIBSection(
        hdc_mem, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0,
    )
    old_bm = gdi32.SelectObject(hdc_mem, hbm)
    ctypes.memmove(bits, buf.ctypes.data, buf.nbytes)

    pt_src = ctypes.wintypes.POINT(0, 0)
    size = SIZEL(w, h)
    blend = BLENDFUNCTION(0, 0, 255, 1)

    user32.UpdateLayeredWindow(
        hwnd, hdc_screen, None, ctypes.byref(size),
        hdc_mem, ctypes.byref(pt_src), 0, ctypes.byref(blend), 2,
    )

    gdi32.SelectObject(hdc_mem, old_bm)
    gdi32.DeleteObject(hbm)
    gdi32.DeleteDC(hdc_mem)
    user32.ReleaseDC(0, hdc_screen)


def _create_overlay_window() -> int:
    """Create a layered, topmost popup window for the pill (starts idle size, NOT click-through)."""
    user32 = ctypes.windll.user32
    WS_EX = (
        0x00080000  # WS_EX_LAYERED
        | 0x00000008  # WS_EX_TOPMOST
        | 0x08000000  # WS_EX_NOACTIVATE
        | 0x00000080  # WS_EX_TOOLWINDOW
    )
    # Note: no WS_EX_TRANSPARENT — idle pill is hoverable
    if _pill_user_x is not None:
        x = _pill_user_x
        y = _pill_user_y
    else:
        sw = user32.GetSystemMetrics(0)
        sh = user32.GetSystemMetrics(1)
        x = (sw - IDLE_W) // 2
        y = sh - IDLE_H - 80
    return user32.CreateWindowExW(
        WS_EX, "STATIC", "", 0x80000000,  # WS_POPUP
        x, y, IDLE_W, IDLE_H,
        None, None, None, None,
    )



def _pill_screen_rect() -> tuple[int, int, int, int]:
    """Return (x, y, w, h) of the pill window on screen."""
    user32 = ctypes.windll.user32
    rect = ctypes.wintypes.RECT()
    user32.GetWindowRect(_overlay_hwnd, ctypes.byref(rect))
    return rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top


def _set_pill_mode(mode: str) -> None:
    """Switch pill between idle (36x36) and active (150x40) mode."""
    global _pill_current_mode
    if _pill_current_mode == mode or not _overlay_hwnd:
        return
    _pill_current_mode = mode
    user32 = ctypes.windll.user32
    sw = user32.GetSystemMetrics(0)
    sh = user32.GetSystemMetrics(1)

    if mode == "idle":
        w, h = IDLE_W, IDLE_H
        # Remove WS_EX_TRANSPARENT (hoverable)
        style = user32.GetWindowLongW(_overlay_hwnd, -20)  # GWL_EXSTYLE
        user32.SetWindowLongW(_overlay_hwnd, -20, style & ~0x00000020)
    else:
        w, h = ACTIVE_W, ACTIVE_H
        # Add WS_EX_TRANSPARENT (click-through during recording/transcribing)
        style = user32.GetWindowLongW(_overlay_hwnd, -20)
        user32.SetWindowLongW(_overlay_hwnd, -20, style | 0x00000020)

    if _pill_user_x is not None:
        x = _pill_user_x
        y = _pill_user_y
    else:
        x = (sw - w) // 2
        y = sh - h - 80
    # SWP_NOACTIVATE | SWP_NOZORDER
    user32.SetWindowPos(_overlay_hwnd, None, x, y, w, h, 0x0010 | 0x0004)


def _wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    """Word-wrap text to fit within max_width pixels."""
    words = text.split()
    if not words:
        return [text]
    lines = []
    current = words[0]
    for word in words[1:]:
        test = current + " " + word
        if font.getlength(test) <= max_width:
            current = test
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


LOG_HEADER_H = 72
LOG_COPY_BTN_W = 48
LOG_TEXT_LEFT = 90
LOG_LINE_H = 28


def _render_log_panel() -> tuple[np.ndarray, int, int]:
    """Render the log panel and return (bgra_buffer, width, height)."""
    global _log_entry_heights
    panel_w, max_h = _log_panel_dims()

    total_entries = len(_transcription_log)
    max_vis = LOG_PANEL_MAX_VISIBLE
    # Apply scroll offset: offset=0 shows newest, offset>0 shows older
    end = total_entries - _log_scroll_offset
    start = max(0, end - max_vis)
    entries = list(reversed(_transcription_log[start:end]))
    if not entries:
        entries = [{"text": "No transcriptions yet", "timestamp": "", "time_epoch": 0}]

    try:
        font_header = ImageFont.truetype("seguisb.ttf", 22)
        font_sub = ImageFont.truetype("segoeui.ttf", 15)
        font_text = ImageFont.truetype("seguisb.ttf", 18)
        font_ts = ImageFont.truetype("segoeui.ttf", 14)
        font_check = ImageFont.truetype("seguisb.ttf", 20)
        font_scroll = ImageFont.truetype("segoeui.ttf", 14)
    except OSError:
        font_header = ImageFont.load_default()
        font_sub = font_header
        font_text = font_header
        font_ts = font_header
        font_check = font_header
        font_scroll = font_header

    text_max_w = panel_w - LOG_TEXT_LEFT - LOG_COPY_BTN_W - 20

    entry_layouts = []
    for entry in entries:
        text = entry.get("text", "")
        lines = _wrap_text(text, font_text, text_max_w) if text else [""]
        row_h = max(len(lines) * LOG_LINE_H + 20, 54)
        entry_layouts.append((lines, row_h))

    _log_entry_heights = [rh for _, rh in entry_layouts]
    content_h = sum(_log_entry_heights)
    panel_h = min(LOG_HEADER_H + LOG_PANEL_PADDING * 2 + content_h + 8, max_h)

    img = Image.new("RGBA", (panel_w, panel_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    draw.rounded_rectangle(
        [0, 0, panel_w - 1, panel_h - 1],
        radius=14,
        fill=(PILL_BG[0], PILL_BG[1], PILL_BG[2], int(LOG_PANEL_BG_ALPHA * 255)),
    )

    draw.text((20, 14), "Transcription Log", fill=(*WHITE, 230), font=font_header)
    draw.text((20, 42), "Hold Ctrl+Shift+Space to dictate  \u2022  Release to transcribe",
              fill=(*GRAY, 150), font=font_sub)
    draw.line([(20, LOG_HEADER_H - 4), (panel_w - 20, LOG_HEADER_H - 4)], fill=(*GRAY, 50))

    # Scroll indicators
    can_scroll_up = _log_scroll_offset > 0
    can_scroll_down = total_entries > _log_scroll_offset + max_vis
    if can_scroll_up:
        draw.text((panel_w - 34, 16), "\u25b2", fill=(*CYAN, 150), font=font_scroll)
    if can_scroll_down:
        draw.text((panel_w - 34, panel_h - 22), "\u25bc", fill=(*CYAN, 150), font=font_scroll)

    is_copied_fresh = _copied_row is not None and (time.time() - _copied_time) < 1.5

    y = LOG_HEADER_H + LOG_PANEL_PADDING
    for idx, (entry, (wrapped_lines, row_h)) in enumerate(zip(entries, entry_layouts)):
        if y + row_h > panel_h:
            break

        ts = entry.get("timestamp", "")
        if ts:
            draw.text((20, y + 12), ts, fill=(*GRAY, 150), font=font_ts)

        for li, line in enumerate(wrapped_lines):
            draw.text((LOG_TEXT_LEFT, y + 10 + li * LOG_LINE_H), line,
                       fill=(*WHITE, 245), font=font_text)

        # Copy button with hover / copied states (38x36)
        copy_x = panel_w - LOG_COPY_BTN_W - 8
        btn_cy = y + row_h // 2
        is_hover = (_copy_hover_row == idx)
        is_just_copied = (is_copied_fresh and _copied_row == idx)

        btn_hw = 19  # half-width
        btn_hh = 18  # half-height

        if is_just_copied:
            draw.rounded_rectangle(
                [copy_x, btn_cy - btn_hh, copy_x + btn_hw * 2, btn_cy + btn_hh],
                radius=6, fill=(40, 180, 80, 100),
            )
            _draw_centered_text(draw, "\u2713", copy_x + btn_hw, btn_cy,
                                font_check, (40, 220, 80, 255))
        elif is_hover:
            draw.rounded_rectangle(
                [copy_x, btn_cy - btn_hh, copy_x + btn_hw * 2, btn_cy + btn_hh],
                radius=6, fill=(*CYAN, 90),
            )
            draw.rectangle([copy_x + 9, btn_cy - 11, copy_x + 21, btn_cy + 6],
                            outline=(*CYAN, 255), width=2)
            draw.rectangle([copy_x + 16, btn_cy - 7, copy_x + 28, btn_cy + 10],
                            outline=(*CYAN, 255), width=2)
        else:
            draw.rounded_rectangle(
                [copy_x, btn_cy - btn_hh, copy_x + btn_hw * 2, btn_cy + btn_hh],
                radius=6, fill=(*CYAN, 40),
            )
            draw.rectangle([copy_x + 9, btn_cy - 11, copy_x + 21, btn_cy + 6],
                            outline=(*CYAN, 150), width=1)
            draw.rectangle([copy_x + 16, btn_cy - 7, copy_x + 28, btn_cy + 10],
                            outline=(*CYAN, 150), width=1)

        if idx < len(entries) - 1:
            div_y = y + row_h - 1
            draw.line([(20, div_y), (panel_w - 20, div_y)], fill=(*GRAY, 30))

        y += row_h

    return _rgba_to_premul_bgra(img), panel_w, panel_h


def _show_panel_window(hwnd: int, buf: np.ndarray, pw: int, ph: int) -> None:
    """Position a panel window above the pill and show it."""
    if not hwnd or not _overlay_hwnd:
        return
    user32 = ctypes.windll.user32
    px, py, pill_w, _ = _pill_screen_rect()
    pill_center_x = px + pill_w // 2
    panel_x = pill_center_x - pw // 2
    panel_y = py - ph - 8
    # Clamp to screen edges with 8px margin
    sw, sh = _screen_size()
    panel_x = max(8, min(panel_x, sw - pw - 8))
    panel_y = max(8, panel_y)
    user32.SetWindowPos(hwnd, None, panel_x, panel_y, pw, ph, 0x0010 | 0x0004)
    _update_layered_window(hwnd, buf, pw, ph)
    user32.ShowWindow(hwnd, 8)  # SW_SHOWNA


def _show_log_panel() -> None:
    """Render and display the log panel above the pill."""
    global _active_panel, _log_scroll_offset
    if not _log_panel_hwnd or not _overlay_hwnd:
        return
    # Reset scroll to newest on fresh open (not on re-render from scroll)
    if _active_panel != "info":
        _log_scroll_offset = 0
    buf, pw, ph = _render_log_panel()
    _show_panel_window(_log_panel_hwnd, buf, pw, ph)
    _active_panel = "info"


def _hide_log_panel() -> None:
    global _active_panel
    if _log_panel_hwnd and _active_panel == "info":
        ctypes.windll.user32.ShowWindow(_log_panel_hwnd, 0)  # SW_HIDE
        _active_panel = None


# ---------------------------------------------------------------------------
# Model selector panel
# ---------------------------------------------------------------------------
def _create_panel_window() -> int:
    """Create a generic layered panel window (NOT click-through)."""
    user32 = ctypes.windll.user32
    WS_EX = (
        0x00080000  # WS_EX_LAYERED
        | 0x00000008  # WS_EX_TOPMOST
        | 0x08000000  # WS_EX_NOACTIVATE
        | 0x00000080  # WS_EX_TOOLWINDOW
    )
    return user32.CreateWindowExW(
        WS_EX, "STATIC", "", 0x80000000,
        0, 0, 10, 10,
        None, None, None, None,
    )


def _rgba_to_premul_bgra(img: Image.Image) -> np.ndarray:
    """Convert RGBA PIL image to pre-multiplied BGRA numpy buffer."""
    pixels = np.array(img, dtype=np.float32) / 255.0
    bgra = np.zeros_like(pixels)
    bgra[:, :, 0] = pixels[:, :, 2] * pixels[:, :, 3]  # B
    bgra[:, :, 1] = pixels[:, :, 1] * pixels[:, :, 3]  # G
    bgra[:, :, 2] = pixels[:, :, 0] * pixels[:, :, 3]  # R
    bgra[:, :, 3] = pixels[:, :, 3]
    return (bgra * 255).clip(0, 255).astype(np.uint8)


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
    """tqdm-compatible class that writes download progress to a global."""

    def __init__(self, *args, **kwargs):
        global _download_progress
        self.total = kwargs.get("total", 0) or 0
        self.n = 0
        _download_progress = 0.0

    def update(self, n=1):
        global _download_progress
        self.n += n
        if self.total > 0:
            _download_progress = min(self.n / self.total, 1.0)

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def _render_model_panel() -> tuple[np.ndarray, int, int]:
    """Render the model selector panel with cache/download status."""
    row_count = len(AVAILABLE_MODELS)
    panel_w = _model_panel_width()
    panel_h = MODEL_PANEL_HEADER_H + row_count * MODEL_PANEL_ROW_H + 16

    img = Image.new("RGBA", (panel_w, panel_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle(
        [0, 0, panel_w - 1, panel_h - 1], radius=14,
        fill=(PILL_BG[0], PILL_BG[1], PILL_BG[2], int(0.94 * 255)),
    )

    try:
        font_title = ImageFont.truetype("seguisb.ttf", 22)
        font = ImageFont.truetype("seguisb.ttf", 18)
        font_small = ImageFont.truetype("seguisb.ttf", 14)
        font_check = ImageFont.truetype("seguisb.ttf", 20)
    except OSError:
        font_title = ImageFont.load_default()
        font = font_title
        font_small = font
        font_check = font

    # Header
    draw.text((20, 12), "Models", fill=(*WHITE, 230), font=font_title)
    draw.line([(20, MODEL_PANEL_HEADER_H - 4), (panel_w - 20, MODEL_PANEL_HEADER_H - 4)],
              fill=(*GRAY, 50))

    ORANGE = (255, 160, 50)

    for idx, name in enumerate(AVAILABLE_MODELS):
        y = MODEL_PANEL_HEADER_H + idx * MODEL_PANEL_ROW_H
        is_loaded = (name == _loaded_model_name)
        is_this_loading = (_model_loading and name == _model_loading_name)
        is_downloading = (is_this_loading and _download_progress < 1.0
                          and _download_progress > 0.0)
        is_download_starting = (is_this_loading and _download_progress == 0.0
                                and not _is_model_cached(name))
        is_confirming = (name == _download_confirm_name and not _model_loading)
        has_error = (_download_error and name == _model_loading_name
                     and not _model_loading)
        is_cached = _is_model_cached(name) if not is_loaded else True
        size_mb = MODEL_SIZES_MB.get(name, 0)

        # Vertically center text in row
        text_y = y + (MODEL_PANEL_ROW_H - 18) // 2

        if has_error:
            draw.text((54, text_y), name, fill=(*ORANGE, 240), font=font)
            draw.text((panel_w - 20, text_y + 2), _download_error,
                      fill=(*ORANGE, 200), font=font_small, anchor="ra")
        elif is_downloading or is_download_starting:
            draw.text((54, text_y - 4), name, fill=(*CYAN, 220), font=font)
            if is_downloading:
                pct_text = f"{int(_download_progress * 100)}%"
                draw.text((panel_w - 20, text_y - 2), pct_text,
                          fill=(*CYAN, 200), font=font_small, anchor="ra")
                bar_x = 54
                bar_y = y + MODEL_PANEL_ROW_H - 16
                bar_w = panel_w - 54 - 20
                bar_h = 4
                draw.rounded_rectangle(
                    [bar_x, bar_y, bar_x + bar_w, bar_y + bar_h],
                    radius=2, fill=(*GRAY, 40))
                fill_w = int(bar_w * _download_progress)
                if fill_w > 0:
                    draw.rounded_rectangle(
                        [bar_x, bar_y, bar_x + fill_w, bar_y + bar_h],
                        radius=2, fill=(*CYAN, 200))
            else:
                draw.text((panel_w - 20, text_y - 2), "connecting...",
                          fill=(*GRAY, 150), font=font_small, anchor="ra")
        elif is_this_loading:
            draw.text((20, text_y), "...", fill=(*CYAN, 200), font=font_small)
            draw.text((54, text_y), name, fill=(*CYAN, 220), font=font)
            draw.text((panel_w - 20, text_y + 2), "loading...",
                      fill=(*GRAY, 150), font=font_small, anchor="ra")
        elif is_confirming:
            draw.rounded_rectangle(
                [4, y + 2, panel_w - 4, y + MODEL_PANEL_ROW_H - 2],
                radius=8, fill=(*CYAN, 20))
            draw.text((54, y + 10), name, fill=(*CYAN, 255), font=font)
            confirm_text = f"Download ~{size_mb} MB?"
            draw.text((54, y + 32), confirm_text,
                      fill=(*CYAN, 180), font=font_small)
            draw.text((panel_w - 20, y + 20), "click to confirm",
                      fill=(*CYAN, 140), font=font_small, anchor="ra")
        elif is_loaded:
            draw.text((20, text_y - 2), "\u2713", fill=(*CYAN, 255), font=font_check)
            draw.text((54, text_y), name, fill=(*CYAN, 255), font=font)
        elif is_cached:
            draw.text((54, text_y), name, fill=(*WHITE, 220), font=font)
            draw.text((panel_w - 20, text_y + 2), "ready",
                      fill=(*GRAY, 100), font=font_small, anchor="ra")
        else:
            draw.text((54, text_y), name, fill=(*WHITE, 180), font=font)
            size_label = f"~{size_mb} MB" if size_mb < 1000 else f"~{size_mb / 1000:.1f} GB"
            draw.text((panel_w - 20, text_y + 2), size_label,
                      fill=(*GRAY, 100), font=font_small, anchor="ra")

        if idx < row_count - 1:
            div_y = y + MODEL_PANEL_ROW_H - 1
            draw.line([(20, div_y), (panel_w - 20, div_y)], fill=(*GRAY, 35))

    return _rgba_to_premul_bgra(img), panel_w, panel_h


def _show_model_panel() -> None:
    global _active_panel
    if not _model_panel_hwnd or not _overlay_hwnd:
        return
    buf, pw, ph = _render_model_panel()
    _show_panel_window(_model_panel_hwnd, buf, pw, ph)
    _active_panel = "model"


def _hide_model_panel() -> None:
    global _active_panel
    if _model_panel_hwnd and _active_panel == "model":
        ctypes.windll.user32.ShowWindow(_model_panel_hwnd, 0)
        _active_panel = None


# ---------------------------------------------------------------------------
# Settings panel
# ---------------------------------------------------------------------------
def _render_settings_panel() -> tuple[np.ndarray, int, int]:
    """Render settings panel with stream toggle and Quit button."""
    panel_w = _settings_panel_width()
    # Dynamic height: header + stream row + gap + quit btn + bottom pad
    stream_row_h = 44
    quit_btn_h = 44
    panel_h = SETTINGS_HEADER_H + stream_row_h + 12 + quit_btn_h + 20

    img = Image.new("RGBA", (panel_w, panel_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle(
        [0, 0, panel_w - 1, panel_h - 1], radius=14,
        fill=(PILL_BG[0], PILL_BG[1], PILL_BG[2], int(0.94 * 255)),
    )

    try:
        font_title = ImageFont.truetype("seguisb.ttf", 22)
        font = ImageFont.truetype("seguisb.ttf", 17)
        font_toggle = ImageFont.truetype("seguisb.ttf", 14)
        font_btn = ImageFont.truetype("seguisb.ttf", 18)
    except OSError:
        font_title = ImageFont.load_default()
        font = font_title
        font_toggle = font
        font_btn = font

    # Header
    draw.text((20, 12), "Settings", fill=(*WHITE, 230), font=font_title)
    draw.line([(20, SETTINGS_HEADER_H - 4), (panel_w - 20, SETTINGS_HEADER_H - 4)],
              fill=(*GRAY, 50))

    # Stream toggle row
    row_y = SETTINGS_HEADER_H + 8
    label = "Stream mode"
    draw.text((20, row_y + 10), label, font=font, fill=(230, 240, 255, 220))

    # Toggle pill
    pill_w, pill_h = 56, 28
    pill_x = panel_w - pill_w - 20
    pill_y = row_y + 8
    if STREAM_MODE:
        draw.rounded_rectangle(
            [pill_x, pill_y, pill_x + pill_w, pill_y + pill_h],
            radius=pill_h // 2, fill=(*CYAN, 180))
        knob_x = pill_x + pill_w - pill_h + 4
        draw.ellipse([knob_x, pill_y + 4, knob_x + pill_h - 8, pill_y + pill_h - 4],
                     fill=(255, 255, 255, 240))
        draw.text((pill_x + 8, pill_y + 6), "ON", font=font_toggle, fill=(15, 20, 35, 220))
    else:
        draw.rounded_rectangle(
            [pill_x, pill_y, pill_x + pill_w, pill_y + pill_h],
            radius=pill_h // 2, fill=(*GRAY, 80))
        knob_x = pill_x + 4
        draw.ellipse([knob_x, pill_y + 4, knob_x + pill_h - 8, pill_y + pill_h - 4],
                     fill=(*GRAY, 200))
        draw.text((pill_x + pill_w - 30, pill_y + 6), "OFF", font=font_toggle, fill=(*GRAY, 200))

    # Quit button — red rounded rect
    btn_x = 20
    btn_y = row_y + stream_row_h + 12
    btn_w = panel_w - 40
    btn_h = quit_btn_h
    draw.rounded_rectangle(
        [btn_x, btn_y, btn_x + btn_w, btn_y + btn_h],
        radius=8, fill=(180, 40, 40, 220),
    )
    _draw_centered_text(draw, "Quit", panel_w // 2, btn_y + btn_h // 2, font_btn, (255, 255, 255, 240))

    return _rgba_to_premul_bgra(img), panel_w, panel_h


def _show_settings_panel() -> None:
    global _active_panel
    if not _settings_panel_hwnd or not _overlay_hwnd:
        return
    buf, pw, ph = _render_settings_panel()
    _show_panel_window(_settings_panel_hwnd, buf, pw, ph)
    _active_panel = "settings"


def _hide_settings_panel() -> None:
    global _active_panel
    if _settings_panel_hwnd and _active_panel == "settings":
        ctypes.windll.user32.ShowWindow(_settings_panel_hwnd, 0)
        _active_panel = None


# ---------------------------------------------------------------------------
# Welcome tooltip (first-run, auto-dismisses after 5s)
# ---------------------------------------------------------------------------
WELCOME_W = 320
WELCOME_H = 70


def _render_welcome() -> np.ndarray:
    """Render the welcome tooltip."""
    img = Image.new("RGBA", (WELCOME_W, WELCOME_H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle(
        [0, 0, WELCOME_W - 1, WELCOME_H - 1], radius=12,
        fill=(PILL_BG[0], PILL_BG[1], PILL_BG[2], int(0.94 * 255)),
    )

    try:
        font_main = ImageFont.truetype("segoeuib.ttf", 15)  # bold
        font_sub = ImageFont.truetype("segoeui.ttf", 12)
    except OSError:
        try:
            font_main = ImageFont.truetype("segoeui.ttf", 15)
        except OSError:
            font_main = ImageFont.load_default()
        font_sub = font_main

    # Main line: "Hold Ctrl+Shift+Space to dictate" with hotkey in cyan
    prefix = "Hold "
    hotkey = "Ctrl+Shift+Space"
    suffix = " to dictate"
    x = 20
    y_main = 16
    draw.text((x, y_main), prefix, fill=(*WHITE, 230), font=font_main)
    x += int(font_main.getlength(prefix))
    draw.text((x, y_main), hotkey, fill=(*CYAN, 255), font=font_main)
    x += int(font_main.getlength(hotkey))
    draw.text((x, y_main), suffix, fill=(*WHITE, 230), font=font_main)

    # Sub line
    draw.text((20, 42), "Release to transcribe and auto-type", fill=(*GRAY, 180), font=font_sub)

    return _rgba_to_premul_bgra(img)


def _show_welcome() -> None:
    """Show the welcome tooltip above the pill."""
    global _welcome_shown, _welcome_show_time
    if not _welcome_hwnd or not _overlay_hwnd:
        return
    buf = _render_welcome()
    _show_panel_window(_welcome_hwnd, buf, WELCOME_W, WELCOME_H)
    _welcome_shown = True
    _welcome_show_time = time.time()


def _hide_welcome() -> None:
    """Hide the welcome tooltip."""
    if _welcome_hwnd:
        ctypes.windll.user32.ShowWindow(_welcome_hwnd, 0)


# ---------------------------------------------------------------------------
# Unified panel management
# ---------------------------------------------------------------------------
def _hide_all_panels() -> None:
    """Hide whichever panel is currently active."""
    global _active_panel
    if _active_panel == "info" and _log_panel_hwnd:
        ctypes.windll.user32.ShowWindow(_log_panel_hwnd, 0)
    elif _active_panel == "model" and _model_panel_hwnd:
        ctypes.windll.user32.ShowWindow(_model_panel_hwnd, 0)
    elif _active_panel == "settings" and _settings_panel_hwnd:
        ctypes.windll.user32.ShowWindow(_settings_panel_hwnd, 0)
    _active_panel = None


_PANEL_SHOW = {
    "info": _show_log_panel,
    "model": _show_model_panel,
    "settings": _show_settings_panel,
}


def _toggle_panel(name: str) -> None:
    """Toggle a panel: if it's active close it, otherwise open it (closing any other)."""
    if _active_panel == name:
        _hide_all_panels()
    else:
        _hide_all_panels()
        _PANEL_SHOW[name]()


# ---------------------------------------------------------------------------
# Click handlers
# ---------------------------------------------------------------------------
def _get_idle_icon_zone(cursor_x: int, pill_left: int) -> int | None:
    """Map cursor X to icon zone 0 (info), 1 (model), 2 (settings), or None."""
    rx = cursor_x - pill_left
    if rx < 0 or rx >= IDLE_W:
        return None
    zone = rx // IDLE_ICON_ZONE_W
    return min(zone, 2)


_ZONE_PANEL = {0: "info", 1: "model", 2: "settings"}


_DRAG_THRESHOLD = 5  # pixels of movement before click becomes a drag


def _handle_idle_pill_click() -> None:
    """Handle click/drag on idle pill. Short click = toggle panel; drag = reposition."""
    global _idle_click_debounce, _drag_active, _drag_pending
    global _drag_start_x, _drag_start_y, _drag_pill_x, _drag_pill_y
    global _pill_user_x, _pill_user_y
    user32 = ctypes.windll.user32

    mouse_down = bool(user32.GetAsyncKeyState(0x01) & 0x8000)

    if not mouse_down:
        # --- Mouse released ---
        if _drag_active:
            # End drag — save position
            px, py, _, _ = _pill_screen_rect()
            _pill_user_x = px
            _pill_user_y = py
            _drag_active = False
            _drag_pending = False
            _idle_click_debounce = True
            return

        if _drag_pending:
            # Was pressed on pill but didn't move enough — treat as click
            _drag_pending = False
            rect = ctypes.wintypes.RECT()
            user32.GetWindowRect(_overlay_hwnd, ctypes.byref(rect))
            zone = _get_idle_icon_zone(_drag_start_x, rect.left)
            if zone is not None:
                _toggle_panel(_ZONE_PANEL[zone])
            _idle_click_debounce = True
            return

        _idle_click_debounce = False
        return

    # --- Mouse is down ---
    if _idle_click_debounce:
        return

    if _drag_active:
        # Continue dragging — move pill to follow cursor
        pt = ctypes.wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        new_x = _drag_pill_x + (pt.x - _drag_start_x)
        new_y = _drag_pill_y + (pt.y - _drag_start_y)
        user32.SetWindowPos(_overlay_hwnd, None, new_x, new_y, IDLE_W, IDLE_H, 0x0010 | 0x0004)
        # Reposition open panel to follow
        if _active_panel and _active_panel in _PANEL_SHOW:
            _PANEL_SHOW[_active_panel]()
        return

    if _drag_pending:
        # Check if cursor has moved enough to start a drag
        pt = ctypes.wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        dx = abs(pt.x - _drag_start_x)
        dy = abs(pt.y - _drag_start_y)
        if dx > _DRAG_THRESHOLD or dy > _DRAG_THRESHOLD:
            _drag_active = True
            _hide_all_panels()
        return

    # Fresh click — check what's under cursor
    if not _is_cursor_over_hwnd(_overlay_hwnd):
        # Click outside pill — dismiss panels if also outside active panel
        if _active_panel:
            active_hwnd = {
                "info": _log_panel_hwnd,
                "model": _model_panel_hwnd,
                "settings": _settings_panel_hwnd,
            }.get(_active_panel)
            if not _is_cursor_over_hwnd(active_hwnd):
                _hide_all_panels()
                _idle_click_debounce = True
        return

    # Mouse down on pill — start tracking for drag-or-click
    pt = ctypes.wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    rect = ctypes.wintypes.RECT()
    user32.GetWindowRect(_overlay_hwnd, ctypes.byref(rect))
    _drag_start_x = pt.x
    _drag_start_y = pt.y
    _drag_pill_x = rect.left
    _drag_pill_y = rect.top
    _drag_pending = True


def _handle_model_click() -> None:
    """Detect click on a model row — two-click confirmation for uncached models."""
    global _model_click_debounce, _download_confirm_name
    user32 = ctypes.windll.user32

    if not (user32.GetAsyncKeyState(0x01) & 0x8000):
        _model_click_debounce = False
        return
    if _model_click_debounce:
        return
    if _model_loading or not _model_panel_hwnd or _active_panel != "model":
        return
    if not _is_cursor_over_hwnd(_model_panel_hwnd):
        # Click outside panel — cancel confirmation if pending
        if _download_confirm_name:
            _download_confirm_name = None
            _show_model_panel()
        return

    _model_click_debounce = True
    pt = ctypes.wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    rect = ctypes.wintypes.RECT()
    user32.GetWindowRect(_model_panel_hwnd, ctypes.byref(rect))

    ry = pt.y - rect.top - MODEL_PANEL_HEADER_H
    row = ry // MODEL_PANEL_ROW_H
    if 0 <= row < len(AVAILABLE_MODELS):
        name = AVAILABLE_MODELS[row]
        if name == _loaded_model_name:
            return

        if _is_model_cached(name):
            # Cached: load immediately
            _download_confirm_name = None
            _start_model_load(name)
        elif name == _download_confirm_name:
            # Second click: confirmed — start download + load
            _download_confirm_name = None
            _start_model_download_and_load(name)
        else:
            # First click on uncached model: show confirmation
            _download_confirm_name = name
            _show_model_panel()



def _handle_settings_click() -> None:
    """Detect click on stream toggle or Quit button in the settings panel."""
    global _should_quit, _settings_click_debounce, STREAM_MODE
    user32 = ctypes.windll.user32

    if not (user32.GetAsyncKeyState(0x01) & 0x8000):
        _settings_click_debounce = False
        return
    if _settings_click_debounce:
        return
    if not _settings_panel_hwnd or _active_panel != "settings":
        return
    if not _is_cursor_over_hwnd(_settings_panel_hwnd):
        return

    _settings_click_debounce = True

    # Get click position relative to panel
    pt = ctypes.wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    rect = ctypes.wintypes.RECT()
    user32.GetWindowRect(_settings_panel_hwnd, ctypes.byref(rect))
    ry = pt.y - rect.top

    # Header: 0..SETTINGS_HEADER_H, Stream toggle: header+8..+52, Quit: header+64+
    if ry < SETTINGS_HEADER_H:
        return  # clicked header area
    elif ry < SETTINGS_HEADER_H + 56:
        # Toggle stream mode
        STREAM_MODE = not STREAM_MODE
        log.info("STREAM_MODE toggled to %s", STREAM_MODE)
        buf, pw, ph = _render_settings_panel()
        _show_panel_window(_settings_panel_hwnd, buf, pw, ph)
    else:
        # Quit button
        _should_quit = True
        if icon:
            icon.stop()


# ---------------------------------------------------------------------------
# Background model loading
# ---------------------------------------------------------------------------
def _start_model_load(name: str) -> None:
    """Spawn a background thread to load a new Whisper model."""
    global _model_loading, _model_loading_name
    if _model_loading:
        return
    _model_loading = True
    _model_loading_name = name
    log.info("Loading model: %s", name)

    # Re-render panel to show loading state
    if _active_panel == "model" and _model_panel_hwnd:
        buf, pw, ph = _render_model_panel()
        _show_panel_window(_model_panel_hwnd, buf, pw, ph)

    def _load():
        global model, _model_loading, _loaded_model_name
        try:
            new_model = WhisperModel(name, device="cpu", compute_type="int8")
            model = new_model
            _loaded_model_name = name
            log.info("Model loaded: %s", name)
        except Exception:
            log.exception("Failed to load model %s", name)
        finally:
            _model_loading = False

    threading.Thread(target=_load, daemon=True).start()


def _start_model_download_and_load(name: str) -> None:
    """Download a model from HF Hub, then load it."""
    global _model_loading, _model_loading_name, _download_progress, _download_error
    if _model_loading:
        return
    _model_loading = True
    _model_loading_name = name
    _download_progress = 0.0
    _download_error = None
    log.info("Downloading model: %s (~%d MB)", name, MODEL_SIZES_MB.get(name, 0))

    # Re-render panel to show download state
    if _active_panel == "model" and _model_panel_hwnd:
        buf, pw, ph = _render_model_panel()
        _show_panel_window(_model_panel_hwnd, buf, pw, ph)

    def _download_and_load():
        global model, _model_loading, _loaded_model_name
        global _download_error, _download_error_time, _download_progress

        # Internet check
        if not _check_internet():
            _download_error = "No internet"
            _download_error_time = time.time()
            log.warning("No internet for model download: %s", name)
            _model_loading = False
            return

        try:
            import huggingface_hub
            from faster_whisper.utils import _MODELS

            repo_id = _MODELS[name]
            allow_patterns = [
                "config.json", "preprocessor_config.json",
                "model.bin", "tokenizer.json", "vocabulary.*",
            ]
            model_path = huggingface_hub.snapshot_download(
                repo_id, allow_patterns=allow_patterns,
                tqdm_class=_DownloadProgress,
            )
            _download_progress = 1.0
            log.info("Download complete: %s, loading...", name)

            new_model = WhisperModel(model_path, device="cpu", compute_type="int8")
            model = new_model
            _loaded_model_name = name
            log.info("Model loaded: %s", name)
        except Exception:
            _download_error = "Download failed"
            _download_error_time = time.time()
            log.exception("Failed to download/load model %s", name)
        finally:
            _model_loading = False

    threading.Thread(target=_download_and_load, daemon=True).start()


# ---------------------------------------------------------------------------
# Streaming transcription worker
# ---------------------------------------------------------------------------
def _transcription_worker() -> None:
    """Background thread: pull audio segments from queue, transcribe, type."""
    global _stream_focus_done

    while True:
        item = _stream_queue.get()
        kind, payload = item

        if kind == "stop":
            break

        if kind == "segment":
            segment_chunks = payload
            done_event = None
        elif kind == "flush":
            segment_chunks, done_event = payload
        else:
            continue

        try:
            audio = np.concatenate(segment_chunks)
            duration = len(audio) / SAMPLE_RATE

            t0 = time.perf_counter()
            segments, _ = model.transcribe(
                audio,
                beam_size=1,
                language="en",
                vad_filter=True,
                vad_parameters=dict(
                    min_speech_duration_ms=250,
                    min_silence_duration_ms=500,
                ),
                no_speech_threshold=0.6,
                condition_on_previous_text=False,
                suppress_blank=True,
            )
            filtered = []
            for seg in segments:
                t = seg.text.strip()
                if not t:
                    continue
                if seg.no_speech_prob > 0.6 and seg.avg_logprob < -1.0:
                    log.info("STREAM SKIP (no_speech=%.2f logprob=%.2f): %s",
                             seg.no_speech_prob, seg.avg_logprob, t)
                    continue
                if t.lower().rstrip(".!?,") in _HALLUCINATION_PATTERNS:
                    log.info("STREAM SKIP (hallucination): %s", t)
                    continue
                filtered.append(t)
            text = " ".join(filtered).strip()
            elapsed = time.perf_counter() - t0
            log.info("STREAM TRANSCRIBE %.3fs -> %s", elapsed, text)

            if text:
                _stream_texts.append(text)

                if not _stream_focus_done and _target_hwnd:
                    try:
                        focus_window(_target_hwnd)
                        time.sleep(0.15)
                    except Exception:
                        log.exception("STREAM: focus_window failed")
                    _stream_focus_done = True

                try:
                    type_text(text + " ")
                except Exception:
                    log.exception("STREAM: type_text failed")

        except Exception:
            log.exception("STREAM: transcription error")
        finally:
            if done_event:
                done_event.set()


def _is_cursor_over_hwnd(hwnd: int) -> bool:
    """Check if the mouse cursor is over a window."""
    if not hwnd:
        return False
    user32 = ctypes.windll.user32
    pt = ctypes.wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    rect = ctypes.wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return rect.left <= pt.x <= rect.right and rect.top <= pt.y <= rect.bottom


def _update_copy_hover() -> None:
    """Update _copy_hover_row based on cursor position over copy buttons."""
    global _copy_hover_row
    if _active_panel != "info" or not _log_panel_hwnd:
        _copy_hover_row = None
        return
    if not _is_cursor_over_hwnd(_log_panel_hwnd):
        _copy_hover_row = None
        return

    user32 = ctypes.windll.user32
    pt = ctypes.wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    rect = ctypes.wintypes.RECT()
    user32.GetWindowRect(_log_panel_hwnd, ctypes.byref(rect))
    rx = pt.x - rect.left
    ry = pt.y - rect.top

    # Check if cursor is in the copy button column
    panel_w, _ = _log_panel_dims()
    copy_x = panel_w - LOG_COPY_BTN_W - 8
    if rx < copy_x or rx > copy_x + LOG_COPY_BTN_W:
        _copy_hover_row = None
        return

    # Walk variable-height rows
    y_acc = LOG_HEADER_H + LOG_PANEL_PADDING
    entries_count = min(len(_transcription_log), LOG_PANEL_MAX_VISIBLE)
    for idx, entry_h in enumerate(_log_entry_heights):
        if idx >= entries_count:
            break
        if y_acc <= ry < y_acc + entry_h:
            _copy_hover_row = idx
            return
        y_acc += entry_h
    _copy_hover_row = None


def _handle_copy_click() -> None:
    """Check if user clicked a copy button in the log panel."""
    global _copy_debounce, _copied_row, _copied_time
    user32 = ctypes.windll.user32

    # VK_LBUTTON
    if not (user32.GetAsyncKeyState(0x01) & 0x8000):
        _copy_debounce = False
        return

    if _copy_debounce or _active_panel != "info" or not _log_panel_hwnd:
        return

    # Get cursor position relative to log panel
    pt = ctypes.wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    rect = ctypes.wintypes.RECT()
    user32.GetWindowRect(_log_panel_hwnd, ctypes.byref(rect))

    rx = pt.x - rect.left
    ry = pt.y - rect.top

    # Check if in copy button column (right edge of panel)
    panel_w, _ = _log_panel_dims()
    copy_x = panel_w - LOG_COPY_BTN_W - 8
    if rx < copy_x or rx > copy_x + LOG_COPY_BTN_W:
        return

    # Walk variable-height rows to find which entry was clicked (scroll-aware)
    total = len(_transcription_log)
    end = total - _log_scroll_offset
    start = max(0, end - LOG_PANEL_MAX_VISIBLE)
    entries = list(reversed(_transcription_log[start:end]))
    y_acc = LOG_HEADER_H + LOG_PANEL_PADDING
    for idx, entry_h in enumerate(_log_entry_heights):
        if idx >= len(entries):
            break
        if y_acc <= ry < y_acc + entry_h:
            text = entries[idx].get("text", "")
            if text and text != "No transcriptions yet":
                try:
                    pyperclip.copy(text)
                    log.info("COPIED: %s", text[:50])
                    _copied_row = idx
                    _copied_time = time.time()
                except Exception:
                    log.exception("Failed to copy text")
            _copy_debounce = True
            return
        y_acc += entry_h


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------
def start_recording() -> None:
    global is_recording, audio_chunks, mic_stream, _target_hwnd
    global _current_level, _display_level
    global _stream_queue, _stream_worker, _silence_count, _transcribed_idx
    global _stream_focus_done, _stream_texts
    if is_recording:
        return

    _target_hwnd = ctypes.windll.user32.GetForegroundWindow()
    _current_level = 0.0
    _display_level = 0.0
    audio_chunks = []

    # Compute silence threshold in callback count from SILENCE_DURATION.
    # sounddevice default blocksize at 16 kHz ≈ 512 frames (~32ms per callback).
    _cb_duration = 512 / SAMPLE_RATE  # seconds per callback
    silence_needed = int(SILENCE_DURATION / _cb_duration)

    streaming = STREAM_MODE
    if streaming:
        _stream_queue = queue.Queue()
        _silence_count = 0
        _transcribed_idx = 0
        _stream_focus_done = False
        _stream_texts = []
        _stream_worker = threading.Thread(target=_transcription_worker, daemon=True)
        _stream_worker.start()

    def on_audio(indata, frames, time_info, status):
        global _current_level, _silence_count, _transcribed_idx
        if not is_recording:
            return

        chunk = indata[:, 0].copy()
        audio_chunks.append(chunk)

        rms = float(np.sqrt(np.mean(chunk ** 2)))
        _current_level = _current_level * 0.6 + min(rms * 15, 1.0) * 0.4

        if not streaming:
            return

        # Silence detection for streaming dispatch
        if rms < SILENCE_RMS_THRESHOLD:
            _silence_count += 1
        else:
            _silence_count = 0

        if _silence_count == silence_needed:
            # Silence threshold just hit — dispatch accumulated speech audio
            end_idx = len(audio_chunks) - silence_needed  # exclude trailing silence
            start_idx = _transcribed_idx
            if end_idx > start_idx:
                segment = audio_chunks[start_idx:end_idx]
                _transcribed_idx = end_idx
                _stream_queue.put(("segment", segment))
            _silence_count = 0  # reset so it doesn't re-trigger each tick

    try:
        mic_stream = sd.InputStream(
            samplerate=SAMPLE_RATE, channels=1, dtype="float32",
            blocksize=512, callback=on_audio,
        )
        mic_stream.start()
    except Exception:
        log.exception("Failed to open microphone")
        mic_stream = None
        set_state("idle")
        if streaming and _stream_queue:
            _stream_queue.put(("stop", None))
        return

    is_recording = True
    set_state("recording")
    log.info("REC START (stream=%s)", streaming)


def stop_and_transcribe() -> None:
    global is_recording, mic_stream
    if not is_recording:
        return
    is_recording = False

    try:
        if mic_stream:
            mic_stream.stop()
            mic_stream.close()
            mic_stream = None
    except Exception:
        log.exception("Error closing microphone")
        mic_stream = None

    if STREAM_MODE and _stream_queue:
        _stop_and_transcribe_streaming()
    else:
        _stop_and_transcribe_batch()


def _stop_and_transcribe_batch() -> None:
    """Original batch transcription path."""
    set_state("transcribing")

    try:
        if not audio_chunks:
            log.info("No audio")
            return

        audio = np.concatenate(audio_chunks)
        duration = len(audio) / SAMPLE_RATE
        log.info("REC STOP — %.1fs captured", duration)

        if duration < 0.3:
            log.info("Too short, skip")
            return

        t0 = time.perf_counter()
        segments, _ = model.transcribe(
            audio, beam_size=1, language="en",
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=500),
            no_speech_threshold=0.6,
        )
        text = " ".join(seg.text.strip() for seg in segments).strip()
        elapsed = time.perf_counter() - t0
        log.info("TRANSCRIBE %.3fs -> %s", elapsed, text)

        if text:
            _transcription_log.append({
                "text": text,
                "timestamp": time.strftime("%H:%M:%S"),
                "time_epoch": time.time(),
            })
            if len(_transcription_log) > 20:
                _transcription_log[:] = _transcription_log[-20:]

            if _target_hwnd:
                try:
                    focus_window(_target_hwnd)
                    time.sleep(0.15)
                except Exception:
                    log.exception("Failed to restore foreground window")

            try:
                type_text(text)
            except Exception:
                log.exception("Failed to type text")
            log.info("TYPED: %s", text)
    except Exception:
        log.exception("Transcription failed")
    finally:
        set_state("idle")


def _stop_and_transcribe_streaming() -> None:
    """Flush remaining audio through worker, then tear down."""
    global _stream_queue, _stream_worker

    try:
        remaining = audio_chunks[_transcribed_idx:]
        if remaining:
            audio = np.concatenate(remaining)
            duration = len(audio) / SAMPLE_RATE
            log.info("STREAM FLUSH — %.1fs remaining", duration)

            if duration >= MIN_CHUNK_DURATION:
                set_state("transcribing")
                done_event = threading.Event()
                _stream_queue.put(("flush", (remaining, done_event)))
                done_event.wait(timeout=30.0)
            else:
                log.info("STREAM FLUSH: too short, skip")
        else:
            log.info("STREAM FLUSH: nothing remaining")

        _stream_queue.put(("stop", None))
        if _stream_worker:
            _stream_worker.join(timeout=5.0)

        # Log combined text as one entry
        full_text = " ".join(_stream_texts).strip()
        if full_text:
            _transcription_log.append({
                "text": full_text,
                "timestamp": time.strftime("%H:%M:%S"),
                "time_epoch": time.time(),
            })
            if len(_transcription_log) > 20:
                _transcription_log[:] = _transcription_log[-20:]
            log.info("STREAM TYPED: %s", full_text)

    except Exception:
        log.exception("Streaming flush failed")
    finally:
        _stream_queue = None
        _stream_worker = None
        set_state("idle")


def quit_app(tray_icon: Icon) -> None:
    global _should_quit
    _should_quit = True
    tray_icon.stop()


# ---------------------------------------------------------------------------
# Safe hotkey: RegisterHotKey + GetAsyncKeyState polling for release
# ---------------------------------------------------------------------------
def _wait_for_release() -> None:
    """Poll until Space is released, then stop recording and transcribe."""
    global _hotkey_busy
    user32 = ctypes.windll.user32
    while user32.GetAsyncKeyState(VK_SPACE) & 0x8000:
        time.sleep(0.05)
    try:
        stop_and_transcribe()
    finally:
        _hotkey_busy = False


def on_hotkey_down() -> None:
    global _hotkey_busy
    if _hotkey_busy:
        return
    _hotkey_busy = True
    start_recording()
    threading.Thread(target=_wait_for_release, daemon=True).start()


# ---------------------------------------------------------------------------
# Unified message loop: hotkey + overlay animation on main thread
# ---------------------------------------------------------------------------
WM_HOTKEY = 0x0312
WM_TIMER = 0x0113


def message_loop() -> None:
    global _overlay_hwnd, _log_panel_hwnd, _model_panel_hwnd, _settings_panel_hwnd
    global _welcome_hwnd, _mouse_hook
    global _copied_row, _copy_hover_row, _copied_time
    global _download_error, _log_scroll_offset, _wheel_delta
    user32 = ctypes.windll.user32

    if not user32.RegisterHotKey(None, HOTKEY_ID, HOTKEY_MOD, VK_SPACE):
        log.error("Failed to register hotkey Ctrl+Shift+Space (already in use?)")
        return
    log.info("Hotkey: hold Ctrl+Shift+Space to record, release to stop")

    _overlay_hwnd = _create_overlay_window()
    if not _overlay_hwnd:
        log.error("Failed to create overlay window")
        return

    _log_panel_hwnd = _create_panel_window()
    _model_panel_hwnd = _create_panel_window()
    _settings_panel_hwnd = _create_panel_window()
    _welcome_hwnd = _create_panel_window()

    # Install low-level mouse hook for wheel scroll
    _mouse_hook = user32.SetWindowsHookExW(14, _mouse_hook_callback, None, 0)  # WH_MOUSE_LL
    if not _mouse_hook:
        log.warning("Failed to install mouse hook — log panel scroll disabled")

    # Show pill immediately in idle mode
    _update_layered_window(_overlay_hwnd, _build_idle_frame(), IDLE_W, IDLE_H)
    user32.ShowWindow(_overlay_hwnd, 8)  # SW_SHOWNA

    # Show welcome tooltip
    _show_welcome()

    timer_id = user32.SetTimer(None, 0, 33, None)  # ~30fps
    HWND_TOPMOST = -1
    SWP_NOMOVE = 0x0002
    SWP_NOSIZE = 0x0001
    SWP_NOACTIVATE = 0x0010

    phase = 0.0
    current_state = "idle"
    topmost_tick = 0
    _was_model_loading = False

    msg = ctypes.wintypes.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
        if _should_quit:
            if _overlay_hwnd:
                user32.KillTimer(None, timer_id)
                user32.UnregisterHotKey(None, HOTKEY_ID)
                if _mouse_hook:
                    user32.UnhookWindowsHookEx(_mouse_hook)
                    _mouse_hook = None
                _hide_all_panels()
                _hide_welcome()
                for hwnd in (_log_panel_hwnd, _model_panel_hwnd, _settings_panel_hwnd, _welcome_hwnd):
                    if hwnd:
                        user32.DestroyWindow(hwnd)
                _log_panel_hwnd = None
                _model_panel_hwnd = None
                _settings_panel_hwnd = None
                _welcome_hwnd = None
                user32.DestroyWindow(_overlay_hwnd)
                _overlay_hwnd = None
                user32.PostQuitMessage(0)
            break

        if msg.message == WM_HOTKEY:
            on_hotkey_down()

        elif msg.message == WM_TIMER:
            target = _overlay_target_state

            # State transition
            if target != current_state:
                current_state = target
                phase = 0.0

                if current_state == "idle":
                    _set_pill_mode("idle")
                    frame = _build_idle_frame(_hover_zone)
                    _update_layered_window(_overlay_hwnd, frame, IDLE_W, IDLE_H)
                else:
                    # Switch to active pill, hide all panels + welcome
                    _hide_all_panels()
                    _hide_welcome()
                    _set_pill_mode("active")

            # Animate active states
            if current_state != "idle":
                phase += 0.1
                buf = _render_frame(current_state, phase)
                _update_layered_window(_overlay_hwnd, buf, ACTIVE_W, ACTIVE_H)

            # Click-based panel interaction (only in idle state)
            if current_state == "idle":
                # Hover detection (skip during drag to avoid flicker)
                if not _drag_active:
                    prev_hover = _hover_zone
                    if _is_cursor_over_hwnd(_overlay_hwnd):
                        pt = ctypes.wintypes.POINT()
                        user32.GetCursorPos(ctypes.byref(pt))
                        rect = ctypes.wintypes.RECT()
                        user32.GetWindowRect(_overlay_hwnd, ctypes.byref(rect))
                        _set_hover_zone(_get_idle_icon_zone(pt.x, rect.left))
                    else:
                        _set_hover_zone(None)
                    if _hover_zone != prev_hover:
                        frame = _build_idle_frame(_hover_zone)
                        _update_layered_window(_overlay_hwnd, frame, IDLE_W, IDLE_H)

                _handle_idle_pill_click()

                # Handle clicks within active panels
                if _active_panel == "info":
                    prev_copied = _copied_row
                    _handle_copy_click()
                    # Copy hover detection + re-render on state change
                    prev_copy_hover = _copy_hover_row
                    _update_copy_hover()
                    needs_rerender = (
                        _copy_hover_row != prev_copy_hover
                        or _copied_row != prev_copied
                    )
                    # Clear copied checkmark after 1.5s
                    if _copied_row is not None and (time.time() - _copied_time) >= 1.5:
                        _copied_row = None
                        needs_rerender = True
                    if needs_rerender:
                        _show_log_panel()

                elif _active_panel == "model":
                    _handle_model_click()
                elif _active_panel == "settings":
                    _handle_settings_click()

                # Mouse wheel scroll for log panel
                if _wheel_delta != 0:
                    # Capture and clear atomically to avoid lost updates
                    delta_snapshot = _wheel_delta
                    _wheel_delta = 0
                    if _active_panel == "info" and _log_panel_hwnd:
                        if _is_cursor_over_hwnd(_log_panel_hwnd):
                            total = len(_transcription_log)
                            max_offset = max(0, total - LOG_PANEL_MAX_VISIBLE)
                            scroll_lines = delta_snapshot // 120
                            if scroll_lines:
                                _log_scroll_offset = max(0, min(
                                    _log_scroll_offset + scroll_lines, max_offset))
                                _show_log_panel()

                # Animate model panel during download / refresh after load
                if _model_loading:
                    _was_model_loading = True
                    # Re-render during download to animate progress bar
                    if _active_panel == "model" and _model_panel_hwnd:
                        buf, pw, ph = _render_model_panel()
                        _show_panel_window(_model_panel_hwnd, buf, pw, ph)
                elif _was_model_loading:
                    _was_model_loading = False
                    if _active_panel == "model" and _model_panel_hwnd:
                        buf, pw, ph = _render_model_panel()
                        _show_panel_window(_model_panel_hwnd, buf, pw, ph)

                # Auto-clear download error after 5 seconds
                if _download_error and (time.time() - _download_error_time) >= 5.0:
                    _download_error = None
                    if _active_panel == "model" and _model_panel_hwnd:
                        buf, pw, ph = _render_model_panel()
                        _show_panel_window(_model_panel_hwnd, buf, pw, ph)

            # Auto-dismiss welcome tooltip after 5 seconds
            if _welcome_shown and time.time() - _welcome_show_time >= 5.0:
                _hide_welcome()

            # Topmost re-assertion every ~2 seconds (60 ticks at 33ms)
            topmost_tick += 1
            if topmost_tick >= 60:
                topmost_tick = 0
                if _overlay_hwnd:
                    user32.SetWindowPos(
                        _overlay_hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                        SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
                    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> None:
    global icon, model

    log.info("Loading model...")
    t0 = time.perf_counter()
    try:
        model = WhisperModel(MODEL_NAME, device="cpu", compute_type="int8")
    except Exception:
        log.exception("Failed to load Whisper model")
        sys.exit(1)
    log.info("Model ready in %.2fs", time.perf_counter() - t0)

    menu = Menu(MenuItem("Quit", quit_app))
    icon = Icon("SIQspeak", make_icon("gray"), "SIQspeak", menu)

    threading.Thread(target=icon.run, daemon=True).start()
    log.info("READY")

    # Main thread: unified message loop (hotkey + overlay animation)
    try:
        message_loop()
    finally:
        # Always unhook mouse hook on exit to prevent cursor lock
        global _mouse_hook
        if _mouse_hook:
            ctypes.windll.user32.UnhookWindowsHookEx(_mouse_hook)
            _mouse_hook = None


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log.exception("Fatal error")
        sys.exit(1)
