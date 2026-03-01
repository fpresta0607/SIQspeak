"""
SIQspeak — hold Ctrl+Shift+Space to record, release to transcribe and paste.

Runs silently in the system tray. Gray = idle, Cyan = recording, Blue = transcribing.
Floating pill with 3-icon toolbar (info, model selector, settings); click to toggle panels.
"""

import ctypes
import ctypes.wintypes
import logging
import math
import os
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
_pill_current_mode = "idle"  # tracks which pill size is displayed
_idle_click_debounce = False
_model_click_debounce = False
_settings_click_debounce = False
_model_loading = False
_model_loading_name = ""
_loaded_model_name = MODEL_NAME

# ---------------------------------------------------------------------------
# Tray icon
# ---------------------------------------------------------------------------


_tray_icon_img: Image.Image | None = None


def _load_tray_icon() -> Image.Image:
    global _tray_icon_img
    if _tray_icon_img is None:
        ico_path = os.path.join(SCRIPT_DIR, "dictate.ico")
        _tray_icon_img = Image.open(ico_path).resize((64, 64), Image.LANCZOS).convert("RGBA")
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
def type_text(text: str) -> None:
    """Type text into the focused window using Unicode keyboard events."""
    user32 = ctypes.windll.user32

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
IDLE_W = 110
IDLE_H = 36
IDLE_ICON_ZONE_W = 36  # each icon zone width

# Active: compact pill with 6 dots
ACTIVE_W = 120
ACTIVE_H = 32
NUM_DOTS = 6
DOT_R = 2.5
DOT_SPACING = 14.0
DOT_START_X = (ACTIVE_W - (NUM_DOTS - 1) * DOT_SPACING) / 2
DOT_Y = ACTIVE_H / 2.0

# Log panel
LOG_PANEL_W = 320
LOG_PANEL_ROW_H = 32
LOG_PANEL_MAX_VISIBLE = 8
LOG_PANEL_PADDING = 8
LOG_PANEL_BG_ALPHA = 0.92

# Model selector panel
MODEL_PANEL_W = 220
MODEL_PANEL_ROW_H = 36
AVAILABLE_MODELS = ["tiny", "base", "small", "medium", "large-v2", "large-v3"]

# Settings panel
SETTINGS_PANEL_W = 160
SETTINGS_PANEL_H = 60

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


def _build_idle_frame() -> np.ndarray:
    """Pre-render idle toolbar: 3-icon pill (info | model | settings)."""
    buf = _idle_bg.copy()
    img = Image.new("RGBA", (IDLE_W, IDLE_H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("segoeui.ttf", 18)
    except OSError:
        font = ImageFont.load_default()

    # Zone centers: 3 zones of IDLE_ICON_ZONE_W each, plus 2px gap between
    zone_w = IDLE_ICON_ZONE_W
    zone_centers = [zone_w // 2, IDLE_W // 2, IDLE_W - zone_w // 2]

    # Separator lines between zones
    for sep_x in [zone_w, IDLE_W - zone_w]:
        draw.line([(sep_x, 8), (sep_x, IDLE_H - 8)], fill=(*GRAY, 60))

    # --- Left icon: info "i" (cyan) ---
    _draw_centered_text(draw, "i", zone_centers[0], IDLE_H // 2, font, (*CYAN, 220))

    # --- Center icon: model hexagon (white) ---
    cx, cy = zone_centers[1], IDLE_H // 2
    r = 9
    hexagon = []
    for k in range(6):
        angle = math.radians(60 * k - 90)
        hexagon.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))
    draw.polygon(hexagon, outline=(*WHITE, 200), fill=None)

    # --- Right icon: gear (gray) ---
    _draw_gear_icon(draw, zone_centers[2], IDLE_H // 2, 9, GRAY)

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


def _draw_gear_icon(
    draw: ImageDraw.ImageDraw, cx: int, cy: int, r: int, color: tuple,
) -> None:
    """Draw a simple gear icon using circles and notches."""
    # Outer circle
    draw.ellipse(
        [cx - r, cy - r, cx + r, cy + r],
        outline=(*color, 200), fill=None, width=1,
    )
    # Inner circle
    ir = r * 0.45
    draw.ellipse(
        [cx - ir, cy - ir, cx + ir, cy + ir],
        fill=(*color, 180),
    )
    # Teeth (8 small rectangles radiating outward)
    for k in range(8):
        angle = math.radians(45 * k)
        tooth_inner = r - 2
        tooth_outer = r + 2
        dx = math.cos(angle)
        dy = math.sin(angle)
        x1 = cx + dx * tooth_inner
        y1 = cy + dy * tooth_inner
        x2 = cx + dx * tooth_outer
        y2 = cy + dy * tooth_outer
        draw.line([(x1, y1), (x2, y2)], fill=(*color, 200), width=2)


_idle_frame = _build_idle_frame()

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

    x = (sw - w) // 2
    y = sh - h - 80
    # SWP_NOACTIVATE | SWP_NOZORDER
    user32.SetWindowPos(_overlay_hwnd, None, x, y, w, h, 0x0010 | 0x0004)


def _render_log_panel() -> tuple[np.ndarray, int, int]:
    """Render the log panel and return (bgra_buffer, width, height)."""
    entries = list(reversed(_transcription_log[-LOG_PANEL_MAX_VISIBLE:]))
    if not entries:
        entries = [{"text": "No transcriptions yet", "timestamp": "", "time_epoch": 0}]

    # Help text header height
    help_h = 44
    row_count = len(entries)
    panel_h = help_h + LOG_PANEL_PADDING * 2 + row_count * LOG_PANEL_ROW_H
    panel_w = LOG_PANEL_W

    img = Image.new("RGBA", (panel_w, panel_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Background rounded rect
    draw.rounded_rectangle(
        [0, 0, panel_w - 1, panel_h - 1],
        radius=10,
        fill=(PILL_BG[0], PILL_BG[1], PILL_BG[2], int(LOG_PANEL_BG_ALPHA * 255)),
    )

    try:
        font = ImageFont.truetype("segoeui.ttf", 13)
        font_small = ImageFont.truetype("segoeui.ttf", 11)
    except OSError:
        font = ImageFont.load_default()
        font_small = font

    # Help instructions at the top
    draw.text((10, 6), "Hold Ctrl+Shift+Space to dictate", fill=(*GRAY, 180), font=font_small)
    draw.text((10, 22), "Release to transcribe and paste", fill=(*GRAY, 180), font=font_small)
    # Divider below help text
    draw.line([(8, help_h - 4), (panel_w - 8, help_h - 4)], fill=(GRAY[0], GRAY[1], GRAY[2], 50))

    for idx, entry in enumerate(entries):
        y = help_h + LOG_PANEL_PADDING + idx * LOG_PANEL_ROW_H

        # Timestamp
        ts = entry.get("timestamp", "")
        if ts:
            draw.text((8, y + 6), ts, fill=(*GRAY, 200), font=font_small)

        # Text (truncate if too long)
        text = entry.get("text", "")
        max_text_w = panel_w - 100
        if font.getlength(text) > max_text_w:
            while font.getlength(text + "...") > max_text_w and len(text) > 5:
                text = text[:-1]
            text += "..."
        draw.text((58, y + 4), text, fill=(*WHITE, 240), font=font)

        # Copy icon (small rectangle with "copy" indicator)
        copy_x = panel_w - 32
        draw.rounded_rectangle(
            [copy_x, y + 4, copy_x + 24, y + 24],
            radius=4,
            fill=(CYAN[0], CYAN[1], CYAN[2], 60),
        )
        # Two overlapping squares as copy icon
        draw.rectangle([copy_x + 6, y + 7, copy_x + 15, y + 18], outline=(*CYAN, 180), width=1)
        draw.rectangle([copy_x + 10, y + 10, copy_x + 19, y + 21], outline=(*CYAN, 180), width=1)

        # Divider line (except last)
        if idx < row_count - 1:
            div_y = y + LOG_PANEL_ROW_H - 1
            draw.line([(8, div_y), (panel_w - 8, div_y)], fill=(GRAY[0], GRAY[1], GRAY[2], 40))

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
    user32.SetWindowPos(hwnd, None, panel_x, panel_y, pw, ph, 0x0010 | 0x0004)
    _update_layered_window(hwnd, buf, pw, ph)
    user32.ShowWindow(hwnd, 8)  # SW_SHOWNA


def _show_log_panel() -> None:
    """Render and display the log panel above the pill."""
    global _active_panel
    if not _log_panel_hwnd or not _overlay_hwnd:
        return
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


def _render_model_panel() -> tuple[np.ndarray, int, int]:
    """Render the model selector panel."""
    row_count = len(AVAILABLE_MODELS)
    panel_h = 8 + row_count * MODEL_PANEL_ROW_H + 8
    panel_w = MODEL_PANEL_W

    img = Image.new("RGBA", (panel_w, panel_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle(
        [0, 0, panel_w - 1, panel_h - 1], radius=10,
        fill=(PILL_BG[0], PILL_BG[1], PILL_BG[2], int(0.92 * 255)),
    )

    try:
        font = ImageFont.truetype("segoeui.ttf", 14)
        font_small = ImageFont.truetype("segoeui.ttf", 11)
    except OSError:
        font = ImageFont.load_default()
        font_small = font

    for idx, name in enumerate(AVAILABLE_MODELS):
        y = 8 + idx * MODEL_PANEL_ROW_H
        is_loaded = (name == _loaded_model_name)
        is_loading = (_model_loading and name == _model_loading_name)

        # Checkmark or loading indicator
        if is_loading:
            draw.text((10, y + 8), "...", fill=(*CYAN, 200), font=font_small)
        elif is_loaded:
            draw.text((10, y + 7), "\u2713", fill=(*CYAN, 255), font=font)

        # Model name
        text_color = (*CYAN, 255) if is_loaded else (*WHITE, 220)
        draw.text((32, y + 8), name, fill=text_color, font=font)

        # Divider
        if idx < row_count - 1:
            div_y = y + MODEL_PANEL_ROW_H - 1
            draw.line([(8, div_y), (panel_w - 8, div_y)], fill=(*GRAY, 40))

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
    """Render settings panel with Quit button."""
    panel_w, panel_h = SETTINGS_PANEL_W, SETTINGS_PANEL_H

    img = Image.new("RGBA", (panel_w, panel_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle(
        [0, 0, panel_w - 1, panel_h - 1], radius=10,
        fill=(PILL_BG[0], PILL_BG[1], PILL_BG[2], int(0.92 * 255)),
    )

    try:
        font = ImageFont.truetype("segoeui.ttf", 14)
    except OSError:
        font = ImageFont.load_default()

    # Quit button — red rounded rect
    btn_x, btn_y = 20, 14
    btn_w, btn_h = panel_w - 40, 32
    draw.rounded_rectangle(
        [btn_x, btn_y, btn_x + btn_w, btn_y + btn_h],
        radius=6, fill=(180, 40, 40, 220),
    )
    _draw_centered_text(draw, "Quit", panel_w // 2, btn_y + btn_h // 2, font, (255, 255, 255, 240))

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


def _handle_idle_pill_click() -> None:
    """Detect click on idle pill and toggle the appropriate panel."""
    global _idle_click_debounce
    user32 = ctypes.windll.user32

    if not (user32.GetAsyncKeyState(0x01) & 0x8000):
        _idle_click_debounce = False
        return

    if _idle_click_debounce:
        return

    if not _is_cursor_over_hwnd(_overlay_hwnd):
        # Click outside pill — if also outside active panel, hide all
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

    # Click is on the pill — determine zone
    pt = ctypes.wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    rect = ctypes.wintypes.RECT()
    user32.GetWindowRect(_overlay_hwnd, ctypes.byref(rect))

    zone = _get_idle_icon_zone(pt.x, rect.left)
    if zone is not None:
        panel_name = _ZONE_PANEL[zone]
        _toggle_panel(panel_name)
    _idle_click_debounce = True


def _handle_model_click() -> None:
    """Detect click on a model row in the model panel."""
    global _model_click_debounce
    user32 = ctypes.windll.user32

    if not (user32.GetAsyncKeyState(0x01) & 0x8000):
        _model_click_debounce = False
        return
    if _model_click_debounce:
        return
    if _model_loading or not _model_panel_hwnd or _active_panel != "model":
        return
    if not _is_cursor_over_hwnd(_model_panel_hwnd):
        return

    _model_click_debounce = True
    pt = ctypes.wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    rect = ctypes.wintypes.RECT()
    user32.GetWindowRect(_model_panel_hwnd, ctypes.byref(rect))

    ry = pt.y - rect.top - 8
    row = ry // MODEL_PANEL_ROW_H
    if 0 <= row < len(AVAILABLE_MODELS):
        name = AVAILABLE_MODELS[row]
        if name != _loaded_model_name:
            _start_model_load(name)



def _handle_settings_click() -> None:
    """Detect click on the Quit button in the settings panel."""
    global _should_quit, _settings_click_debounce
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


def _handle_copy_click() -> None:
    """Check if user clicked a copy button in the log panel."""
    global _copy_debounce
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

    # Check if in copy button column
    copy_x = LOG_PANEL_W - 32
    if rx < copy_x or rx > copy_x + 24:
        return

    # Determine which row (44px help header + padding)
    row = (ry - 44 - LOG_PANEL_PADDING) // LOG_PANEL_ROW_H
    entries = list(reversed(_transcription_log[-LOG_PANEL_MAX_VISIBLE:]))
    if 0 <= row < len(entries):
        text = entries[row].get("text", "")
        if text and text != "No transcriptions yet":
            try:
                pyperclip.copy(text)
                log.info("COPIED: %s", text[:50])
            except Exception:
                log.exception("Failed to copy text")
            _copy_debounce = True


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------
def start_recording() -> None:
    global is_recording, audio_chunks, mic_stream, _target_hwnd
    global _current_level, _display_level
    if is_recording:
        return

    _target_hwnd = ctypes.windll.user32.GetForegroundWindow()
    _current_level = 0.0
    _display_level = 0.0
    audio_chunks = []

    def on_audio(indata, frames, time_info, status):
        global _current_level
        if is_recording:
            chunk = indata[:, 0].copy()
            audio_chunks.append(chunk)
            # Update audio level for dot visualization
            rms = float(np.sqrt(np.mean(chunk ** 2)))
            _current_level = _current_level * 0.6 + min(rms * 15, 1.0) * 0.4

    try:
        mic_stream = sd.InputStream(
            samplerate=SAMPLE_RATE, channels=1, dtype="float32", callback=on_audio,
        )
        mic_stream.start()
    except Exception:
        log.exception("Failed to open microphone")
        mic_stream = None
        set_state("idle")
        return

    is_recording = True
    set_state("recording")
    log.info("REC START")


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
            audio, beam_size=1, language="en", vad_filter=False,
        )
        text = " ".join(seg.text.strip() for seg in segments).strip()
        elapsed = time.perf_counter() - t0
        log.info("TRANSCRIBE %.3fs -> %s", elapsed, text)

        if text:
            # Add to transcription history
            _transcription_log.append({
                "text": text,
                "timestamp": time.strftime("%H:%M:%S"),
                "time_epoch": time.time(),
            })
            if len(_transcription_log) > 20:
                _transcription_log[:] = _transcription_log[-20:]

            # Restore focus to the window that was active when recording started
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

    # Show pill immediately in idle mode
    _update_layered_window(_overlay_hwnd, _idle_frame, IDLE_W, IDLE_H)
    user32.ShowWindow(_overlay_hwnd, 8)  # SW_SHOWNA

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
                _hide_all_panels()
                for hwnd in (_log_panel_hwnd, _model_panel_hwnd, _settings_panel_hwnd):
                    if hwnd:
                        user32.DestroyWindow(hwnd)
                _log_panel_hwnd = None
                _model_panel_hwnd = None
                _settings_panel_hwnd = None
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
                    _update_layered_window(_overlay_hwnd, _idle_frame, IDLE_W, IDLE_H)
                else:
                    # Switch to active pill, hide all panels
                    _hide_all_panels()
                    _set_pill_mode("active")

            # Animate active states
            if current_state != "idle":
                phase += 0.1
                buf = _render_frame(current_state, phase)
                _update_layered_window(_overlay_hwnd, buf, ACTIVE_W, ACTIVE_H)

            # Click-based panel interaction (only in idle state)
            if current_state == "idle":
                _handle_idle_pill_click()

                # Handle clicks within active panels
                if _active_panel == "info":
                    _handle_copy_click()
                elif _active_panel == "model":
                    _handle_model_click()
                elif _active_panel == "settings":
                    _handle_settings_click()

                # Re-render model panel once after loading finishes
                if _model_loading:
                    _was_model_loading = True
                elif _was_model_loading:
                    _was_model_loading = False
                    if _active_panel == "model" and _model_panel_hwnd:
                        buf, pw, ph = _render_model_panel()
                        _show_panel_window(_model_panel_hwnd, buf, pw, ph)

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
    message_loop()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log.exception("Fatal error")
        sys.exit(1)
