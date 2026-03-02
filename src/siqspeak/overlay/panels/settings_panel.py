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

MIC_ROW_H = 32


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


def _render_settings_panel(state: AppState) -> tuple[np.ndarray, int, int]:
    """Render settings panel with stream toggle, GPU toggle, mic dropdown, and Quit."""
    panel_w = _settings_panel_width()
    row_h = 44
    quit_btn_h = 44

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

    # Resolve current mic name
    if state.mic_devices:
        if state.mic_device is not None:
            mic_name = next((d["name"] for d in state.mic_devices if d["index"] == state.mic_device), "Default")
        else:
            mic_name = "Default"
    else:
        mic_name = "No devices"

    # Calculate mic section height
    if state.mic_expanded and state.mic_devices:
        mic_section_h = row_h + len(state.mic_devices) * MIC_ROW_H + 8
    else:
        mic_section_h = row_h

    # Calculate panel height
    toggle_rows = 1 if state.has_cuda else 0  # gpu only
    panel_h = SETTINGS_HEADER_H + 8 + row_h * toggle_rows + mic_section_h + 12 + quit_btn_h + 20

    img = Image.new("RGBA", (panel_w, panel_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle(
        [0, 0, panel_w - 1, panel_h - 1], radius=14,
        fill=(PILL_BG[0], PILL_BG[1], PILL_BG[2], 255),
    )

    # Header
    draw.text((20, 12), "Settings", fill=(*WHITE, 230), font=font_title)
    draw.line([(20, SETTINGS_HEADER_H - 4), (panel_w - 20, SETTINGS_HEADER_H - 4)],
              fill=(*GRAY, 50))

    cur_y = SETTINGS_HEADER_H + 8
    pill_w, pill_h = 56, 28

    # --- GPU toggle row (only if CUDA detected) ---
    if state.has_cuda:
        draw.text((20, cur_y + 10), "Use GPU", font=font, fill=(230, 240, 255, 220))
        _draw_toggle_pill(draw, panel_w - pill_w - 20, cur_y + 8, pill_w, pill_h,
                          state.device == "cuda", font_toggle)
        cur_y += row_h

    # --- Mic selector row ---
    chevron = "\u25BC" if state.mic_expanded else "\u25B6"
    draw.text((20, cur_y + 10), "Microphone", font=font, fill=(230, 240, 255, 220))
    # Show current device name + chevron on the right
    label = f"{mic_name}  {chevron}"
    bbox = draw.textbbox((0, 0), label, font=font_mic)
    tw = bbox[2] - bbox[0]
    draw.text((panel_w - tw - 20, cur_y + 13), label, font=font_mic, fill=(*CYAN, 200))
    cur_y += row_h

    # --- Expanded mic device list ---
    if state.mic_expanded and state.mic_devices:
        for dev in state.mic_devices:
            is_selected = dev["index"] == state.mic_device
            # Highlight selected row
            if is_selected:
                draw.rounded_rectangle(
                    [16, cur_y, panel_w - 16, cur_y + MIC_ROW_H],
                    radius=6, fill=(20, 35, 50, 255),
                )
            name = dev["name"]
            color = (*CYAN, 255) if is_selected else (*WHITE, 180)
            draw.text((28, cur_y + 7), name, font=font_mic, fill=color)
            cur_y += MIC_ROW_H
        cur_y += 8

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
        state.mic_expanded = False
