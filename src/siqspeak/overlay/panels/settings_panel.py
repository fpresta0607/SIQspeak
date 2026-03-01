from __future__ import annotations

import ctypes
import ctypes.wintypes
import logging

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from siqspeak.audio.devices import _get_input_devices
from siqspeak.config import (
    CYAN,
    GRAY,
    PILL_BG,
    SETTINGS_HEADER_H,
    WHITE,
    _settings_panel_width,
)
from siqspeak.overlay.panels import _show_panel_window
from siqspeak.overlay.rendering import _draw_centered_text, _rgba_to_premul_bgra
from siqspeak.state import AppState

log = logging.getLogger("siqspeak")


def _draw_toggle_pill(draw: ImageDraw.Draw, x: int, y: int, w: int, h: int,
                      is_on: bool, font_toggle) -> None:
    """Draw an ON/OFF toggle pill at the given position."""
    if is_on:
        draw.rounded_rectangle([x, y, x + w, y + h], radius=h // 2, fill=(*CYAN, 180))
        knob_x = x + w - h + 4
        draw.ellipse([knob_x, y + 4, knob_x + h - 8, y + h - 4],
                     fill=(255, 255, 255, 240))
        draw.text((x + 8, y + 6), "ON", font=font_toggle, fill=(15, 20, 35, 220))
    else:
        draw.rounded_rectangle([x, y, x + w, y + h], radius=h // 2, fill=(*GRAY, 80))
        knob_x = x + 4
        draw.ellipse([knob_x, y + 4, knob_x + h - 8, y + h - 4], fill=(*GRAY, 200))
        draw.text((x + w - 30, y + 6), "OFF", font=font_toggle, fill=(*GRAY, 200))


def _wrap_mic_name(mic_name: str, suffix: str, font, max_w: int) -> list[str]:
    """Word-wrap mic device name, appending suffix to the last line."""
    words = mic_name.split()
    if not words:
        return [mic_name + suffix]
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        test = current + " " + word
        if font.getlength(test + suffix) <= max_w:
            current = test
        else:
            lines.append(current)
            current = word
    lines.append(current + suffix)
    return lines


def _render_settings_panel(state: AppState) -> tuple[np.ndarray, int, int]:
    """Render settings panel with stream toggle, GPU toggle, mic selector, and Quit."""
    panel_w = _settings_panel_width()
    row_h = 44
    quit_btn_h = 44
    mic_line_h = 18

    try:
        font_title = ImageFont.truetype("seguisb.ttf", 22)
        font = ImageFont.truetype("seguisb.ttf", 17)
        font_toggle = ImageFont.truetype("seguisb.ttf", 14)
        font_btn = ImageFont.truetype("seguisb.ttf", 18)
        font_mic = ImageFont.truetype("seguisb.ttf", 14)
    except OSError:
        font_title = ImageFont.load_default()
        font = font_title
        font_toggle = font
        font_btn = font
        font_mic = font

    # Resolve mic name and wrap lines before sizing the panel
    if state.mic_devices:
        if state.mic_device is not None:
            mic_name = next((d["name"] for d in state.mic_devices if d["index"] == state.mic_device), "Default")
        else:
            mic_name = state.mic_devices[0]["name"] + " *"
    else:
        mic_name = "No devices"
    mic_lines = _wrap_mic_name(mic_name, "  >", font_mic, panel_w - 40)
    mic_row_h = max(row_h, 34 + len(mic_lines) * mic_line_h + 8)

    # Calculate panel height with variable mic row
    toggle_rows = 1 + (1 if state.has_cuda else 0)  # stream + gpu
    panel_h = SETTINGS_HEADER_H + 8 + row_h * toggle_rows + mic_row_h + 12 + quit_btn_h + 20

    img = Image.new("RGBA", (panel_w, panel_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle(
        [0, 0, panel_w - 1, panel_h - 1], radius=14,
        fill=(PILL_BG[0], PILL_BG[1], PILL_BG[2], int(0.94 * 255)),
    )

    # Header
    draw.text((20, 12), "Settings", fill=(*WHITE, 230), font=font_title)
    draw.line([(20, SETTINGS_HEADER_H - 4), (panel_w - 20, SETTINGS_HEADER_H - 4)],
              fill=(*GRAY, 50))

    cur_y = SETTINGS_HEADER_H + 8
    pill_w, pill_h = 56, 28

    # --- Stream toggle row ---
    draw.text((20, cur_y + 10), "Stream mode", font=font, fill=(230, 240, 255, 220))
    _draw_toggle_pill(draw, panel_w - pill_w - 20, cur_y + 8, pill_w, pill_h,
                      state.stream_mode, font_toggle)
    cur_y += row_h

    # --- GPU toggle row (only if CUDA detected) ---
    if state.has_cuda:
        draw.text((20, cur_y + 10), "Use GPU", font=font, fill=(230, 240, 255, 220))
        _draw_toggle_pill(draw, panel_w - pill_w - 20, cur_y + 8, pill_w, pill_h,
                          state.device == "cuda", font_toggle)
        cur_y += row_h

    # --- Mic selector row (wraps long names) ---
    draw.text((20, cur_y + 10), "Microphone", font=font, fill=(230, 240, 255, 220))
    mic_text_y = cur_y + 34
    for ml in mic_lines:
        bbox = draw.textbbox((0, 0), ml, font=font_mic)
        tw = bbox[2] - bbox[0]
        draw.text((panel_w - tw - 20, mic_text_y), ml, font=font_mic, fill=(*CYAN, 200))
        mic_text_y += mic_line_h
    cur_y += mic_row_h

    # Quit button -- red rounded rect
    btn_y = cur_y + 12
    btn_x = 20
    btn_w = panel_w - 40
    draw.rounded_rectangle(
        [btn_x, btn_y, btn_x + btn_w, btn_y + quit_btn_h],
        radius=8, fill=(180, 40, 40, 220),
    )
    _draw_centered_text(draw, "Quit", panel_w // 2, btn_y + quit_btn_h // 2,
                        font_btn, (255, 255, 255, 240))

    return _rgba_to_premul_bgra(img), panel_w, panel_h


def _show_settings_panel(state: AppState) -> None:
    if not state.settings_panel_hwnd or not state.overlay_hwnd:
        return
    state.mic_devices = _get_input_devices()
    buf, pw, ph = _render_settings_panel(state)
    _show_panel_window(state, state.settings_panel_hwnd, buf, pw, ph)
    state.active_panel = "settings"


def _hide_settings_panel(state: AppState) -> None:
    if state.settings_panel_hwnd and state.active_panel == "settings":
        ctypes.windll.user32.ShowWindow(state.settings_panel_hwnd, 0)
        state.active_panel = None
