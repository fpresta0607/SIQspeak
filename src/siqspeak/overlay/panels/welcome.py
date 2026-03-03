from __future__ import annotations

import ctypes
import ctypes.wintypes
import logging
import time

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from siqspeak.config import CYAN, GRAY, PILL_BG, WELCOME_H, WELCOME_W, WHITE
from siqspeak.overlay.panels import _show_panel_window
from siqspeak.overlay.rendering import _rgba_to_premul_bgra
from siqspeak.state import AppState

log = logging.getLogger("siqspeak")


def _render_welcome() -> np.ndarray:
    """Render the welcome tooltip."""
    img = Image.new("RGBA", (WELCOME_W, WELCOME_H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle(
        [0, 0, WELCOME_W - 1, WELCOME_H - 1], radius=12,
        fill=(PILL_BG[0], PILL_BG[1], PILL_BG[2], 255),
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


def _show_welcome(state: AppState) -> None:
    """Show the welcome tooltip above the pill."""
    if not state.welcome_hwnd or not state.overlay_hwnd:
        return
    buf = _render_welcome()
    _show_panel_window(state, state.welcome_hwnd, buf, WELCOME_W, WELCOME_H)
    state.welcome_shown = True
    state.welcome_show_time = time.time()


def _hide_welcome(state: AppState) -> None:
    """Hide the welcome tooltip."""
    if state.welcome_hwnd:
        ctypes.windll.user32.ShowWindow(state.welcome_hwnd, 0)
