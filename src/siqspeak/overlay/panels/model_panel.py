from __future__ import annotations

import ctypes
import ctypes.wintypes
import logging
import time

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from siqspeak.config import (
    AVAILABLE_MODELS,
    CYAN,
    GRAY,
    MODEL_PANEL_HEADER_H,
    MODEL_PANEL_ROW_H,
    MODEL_SIZES_MB,
    PILL_BG,
    WHITE,
    _model_panel_width,
)
from siqspeak.model.manager import _is_model_cached
from siqspeak.overlay.panels import _show_panel_window
from siqspeak.overlay.rendering import _rgba_to_premul_bgra
from siqspeak.state import AppState
from siqspeak.hf_auth import has_token, validate_token

log = logging.getLogger("siqspeak")

# Fully opaque background — no see-through
BG = (PILL_BG[0], PILL_BG[1], PILL_BG[2], 255)
# Solid button fills (no transparency)
BTN_FILL = (30, 50, 80, 255)
BTN_FILL_HOVER = (40, 70, 110, 255)
BTN_OUTLINE = (CYAN[0], CYAN[1], CYAN[2], 255)
BTN_CANCEL_FILL = (40, 40, 50, 255)
BTN_CANCEL_HOVER = (60, 60, 70, 255)
BTN_CANCEL_OUTLINE = (GRAY[0], GRAY[1], GRAY[2], 200)
DIVIDER = (GRAY[0], GRAY[1], GRAY[2], 80)
ROW_HOVER = (30, 38, 58, 255)

# Auth panel button layout (y is calculated dynamically, stored here for click handling)
AUTH_BTN_Y = 0  # set during render
AUTH_BUTTONS = [
    {"label": "Open Browser", "x1": 20, "x2": 145},
    {"label": "Paste & Verify", "x1": 155, "x2": 290},
    {"label": "Cancel", "x1": 300, "x2": 365},
]


def _render_hf_auth_panel(state: AppState) -> tuple[np.ndarray, int, int]:
    """Render the HuggingFace authentication dialog panel."""
    global AUTH_BTN_Y
    panel_w = _model_panel_width()
    panel_h = 290

    try:
        font_title = ImageFont.truetype("seguisb.ttf", 20)
        font = ImageFont.truetype("seguisb.ttf", 16)
        font_small = ImageFont.truetype("seguisb.ttf", 13)
        font_icon = ImageFont.truetype("seguisb.ttf", 28)
    except OSError:
        font_title = ImageFont.load_default()
        font = font_title
        font_small = font
        font_icon = font

    ORANGE = (255, 160, 50)
    GREEN = (80, 220, 120)

    img = Image.new("RGBA", (panel_w, panel_h), BG)
    draw = ImageDraw.Draw(img)
    # Rounded corners by drawing over a filled rect
    draw.rounded_rectangle([0, 0, panel_w - 1, panel_h - 1], radius=14, fill=BG)

    # --- Success state ---
    if state.hf_auth_success:
        draw.text((panel_w // 2, 60), "\u2713", fill=(*GREEN, 255),
                  font=font_icon, anchor="mm")
        draw.text((panel_w // 2, 100), "Signed in!",
                  fill=(*GREEN, 255), font=font_title, anchor="mm")
        username = state.hf_username or "authenticated"
        draw.text((panel_w // 2, 130), f"Welcome, {username}",
                  fill=(*WHITE, 255), font=font, anchor="mm")
        draw.text((panel_w // 2, 160), "Starting download...",
                  fill=(*CYAN, 255), font=font_small, anchor="mm")
        return _rgba_to_premul_bgra(img), panel_w, panel_h

    # --- Verifying state ---
    if state.hf_auth_verifying:
        draw.text((panel_w // 2, 80), "...", fill=(*CYAN, 255),
                  font=font_icon, anchor="mm")
        draw.text((panel_w // 2, 120), "Verifying token...",
                  fill=(*CYAN, 255), font=font, anchor="mm")
        return _rgba_to_premul_bgra(img), panel_w, panel_h

    # --- Header ---
    y = 14
    draw.text((20, y), "\U0001F511  Sign In Required", fill=(*WHITE, 255), font=font_title)
    y += 34

    draw.line([(20, y), (panel_w - 20, y)], fill=DIVIDER)
    y += 14

    # Explanation
    draw.text((20, y), "SIQspeak needs a free HuggingFace",
              fill=(*WHITE, 220), font=font_small)
    y += 18
    draw.text((20, y), "account to download AI models.",
              fill=(*WHITE, 220), font=font_small)
    y += 28

    # Steps
    steps = [
        "Click Open Browser below",
        "Create account or log in",
        "Create a Read token, copy it",
        "Click Paste & Verify here",
    ]
    for i, step in enumerate(steps):
        draw.text((20, y), f"{i+1}.", fill=(*CYAN, 255), font=font)
        draw.text((44, y + 1), step, fill=(*WHITE, 255), font=font_small)
        y += 22

    y += 12
    AUTH_BTN_Y = y

    # --- Buttons with hover detection ---
    hover_btn = state.hf_token_input  # reuse field for hover tracking: "btn0", "btn1", "btn2" or ""

    for i, btn in enumerate(AUTH_BUTTONS):
        is_hover = (hover_btn == f"btn{i}")
        if i < 2:
            fill = BTN_FILL_HOVER if is_hover else BTN_FILL
            outline = BTN_OUTLINE
            text_color = (*CYAN, 255)
        else:
            fill = BTN_CANCEL_HOVER if is_hover else BTN_CANCEL_FILL
            outline = BTN_CANCEL_OUTLINE
            text_color = (*WHITE, 200)

        draw.rounded_rectangle(
            [btn["x1"], y, btn["x2"], y + 32], radius=6,
            fill=fill, outline=outline)
        cx = (btn["x1"] + btn["x2"]) // 2
        draw.text((cx, y + 16), btn["label"],
                  fill=text_color, font=font_small, anchor="mm")

    # Error message
    if state.hf_auth_error and time.time() - state.hf_auth_error_time < 5.0:
        draw.text((20, y + 40), state.hf_auth_error,
                  fill=(*ORANGE, 255), font=font_small)

    return _rgba_to_premul_bgra(img), panel_w, panel_h


def _render_model_panel(state: AppState) -> tuple[np.ndarray, int, int]:
    """Render the model selector panel with cache/download status."""
    panel_w = _model_panel_width()

    # Show auth dialog if needed
    if state.needs_hf_auth:
        return _render_hf_auth_panel(state)

    try:
        font_title = ImageFont.truetype("seguisb.ttf", 22)
        font = ImageFont.truetype("seguisb.ttf", 18)
        font_small = ImageFont.truetype("seguisb.ttf", 14)
        font_check = ImageFont.truetype("seguisb.ttf", 20)
        font_tiny = ImageFont.truetype("seguisb.ttf", 11)
    except OSError:
        font_title = ImageFont.load_default()
        font = font_title
        font_small = font
        font_check = font
        font_tiny = font

    ORANGE = (255, 160, 50)
    GREEN = (80, 220, 120)

    # Clear stale download errors after 8 seconds
    if state.download_error and time.time() - state.download_error_time > 8.0:
        state.download_error = None

    # Check HF auth status for header badge
    hf_signed_in = has_token()

    # --- Loading view ---
    if state.model_loading:
        header_h = MODEL_PANEL_HEADER_H + (16 if hf_signed_in else 0)
        panel_h = header_h + MODEL_PANEL_ROW_H + 16
        img = Image.new("RGBA", (panel_w, panel_h), BG)
        draw = ImageDraw.Draw(img)
        draw.rounded_rectangle([0, 0, panel_w - 1, panel_h - 1], radius=14, fill=BG)

        draw.text((20, 12), "Models", fill=(*WHITE, 255), font=font_title)
        if hf_signed_in:
            draw.text((panel_w - 20, 16), "\u2713 HuggingFace",
                      fill=(*GREEN, 255), font=font_tiny, anchor="ra")
        draw.line([(20, header_h - 4), (panel_w - 20, header_h - 4)], fill=DIVIDER)

        name = state.model_loading_name
        y = header_h
        text_y = y + (MODEL_PANEL_ROW_H - 18) // 2
        is_downloading = (state.download_progress < 1.0 and state.download_progress > 0.0)
        is_download_starting = (state.download_progress == 0.0
                                and state.model_loading_is_download)

        if is_downloading or is_download_starting:
            draw.text((54, text_y - 4), name, fill=(*CYAN, 255), font=font)
            if is_downloading:
                pct_text = f"{int(state.download_progress * 100)}%"
                draw.text((panel_w - 20, text_y - 2), pct_text,
                          fill=(*CYAN, 255), font=font_small, anchor="ra")
                bar_x = 54
                bar_y = y + MODEL_PANEL_ROW_H - 16
                bar_w = panel_w - 54 - 20
                bar_h = 4
                draw.rounded_rectangle(
                    [bar_x, bar_y, bar_x + bar_w, bar_y + bar_h],
                    radius=2, fill=(GRAY[0], GRAY[1], GRAY[2], 80))
                fill_w = int(bar_w * state.download_progress)
                if fill_w > 0:
                    draw.rounded_rectangle(
                        [bar_x, bar_y, bar_x + fill_w, bar_y + bar_h],
                        radius=2, fill=(*CYAN, 255))
            else:
                draw.text((panel_w - 20, text_y - 2), "Connecting...",
                          fill=(*GRAY, 200), font=font_small, anchor="ra")
        else:
            draw.text((20, text_y), "...", fill=(*CYAN, 255), font=font_small)
            draw.text((54, text_y), name, fill=(*CYAN, 255), font=font)
            draw.text((panel_w - 20, text_y + 2), "Loading...",
                      fill=(*GRAY, 200), font=font_small, anchor="ra")

        return _rgba_to_premul_bgra(img), panel_w, panel_h

    # --- Normal view: full model list ---
    row_count = len(AVAILABLE_MODELS)
    header_extra = 16 if hf_signed_in else 0
    panel_h = MODEL_PANEL_HEADER_H + header_extra + row_count * MODEL_PANEL_ROW_H + 16

    img = Image.new("RGBA", (panel_w, panel_h), BG)
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([0, 0, panel_w - 1, panel_h - 1], radius=14, fill=BG)

    # Header
    draw.text((20, 12), "Models", fill=(*WHITE, 255), font=font_title)
    if hf_signed_in:
        draw.text((panel_w - 20, 16), "\u2713 HuggingFace",
                  fill=(*GREEN, 255), font=font_tiny, anchor="ra")
    header_bottom = MODEL_PANEL_HEADER_H + header_extra
    draw.line([(20, header_bottom - 4), (panel_w - 20, header_bottom - 4)], fill=DIVIDER)

    for idx, name in enumerate(AVAILABLE_MODELS):
        y = header_bottom + idx * MODEL_PANEL_ROW_H
        is_loaded = (name == state.loaded_model_name)
        is_confirming = (name == state.download_confirm_name and not state.model_loading)
        has_error = (state.download_error and name == state.model_loading_name
                     and not state.model_loading)
        is_cached = _is_model_cached(name) if not is_loaded else True
        size_mb = MODEL_SIZES_MB.get(name, 0)

        is_hovered = (idx == state.model_hover_row
                      and not is_loaded and not is_confirming)
        if is_hovered:
            draw.rounded_rectangle(
                [4, y + 2, panel_w - 4, y + MODEL_PANEL_ROW_H - 2],
                radius=8, fill=ROW_HOVER)

        text_y = y + (MODEL_PANEL_ROW_H - 18) // 2

        if has_error:
            draw.text((54, text_y), name, fill=(*ORANGE, 255), font=font)
            draw.text((panel_w - 20, text_y + 2), state.download_error,
                      fill=(*ORANGE, 255), font=font_small, anchor="ra")
        elif is_confirming:
            draw.rounded_rectangle(
                [4, y + 2, panel_w - 4, y + MODEL_PANEL_ROW_H - 2],
                radius=8, fill=(20, 30, 48, 255))
            draw.text((54, y + 10), name, fill=(*CYAN, 255), font=font)
            confirm_text = f"Download ~{size_mb} MB?"
            draw.text((54, y + 32), confirm_text,
                      fill=(*CYAN, 255), font=font_small)
            draw.text((panel_w - 20, y + 20), "click to confirm",
                      fill=(*CYAN, 200), font=font_small, anchor="ra")
        elif is_loaded:
            draw.text((20, text_y - 2), "\u2713", fill=(*CYAN, 255), font=font_check)
            draw.text((54, text_y), name, fill=(*CYAN, 255), font=font)
        elif is_cached:
            draw.text((54, text_y), name, fill=(*WHITE, 255), font=font)
            draw.text((panel_w - 20, text_y + 2), "Ready",
                      fill=(*GRAY, 150), font=font_small, anchor="ra")
        else:
            draw.text((54, text_y), name, fill=(*WHITE, 220), font=font)
            size_label = f"~{size_mb} MB" if size_mb < 1000 else f"~{size_mb / 1000:.1f} GB"
            draw.text((panel_w - 20, text_y + 2), size_label,
                      fill=(*GRAY, 150), font=font_small, anchor="ra")

        if idx < row_count - 1:
            div_y = y + MODEL_PANEL_ROW_H - 1
            draw.line([(20, div_y), (panel_w - 20, div_y)], fill=DIVIDER)

    return _rgba_to_premul_bgra(img), panel_w, panel_h


def _show_model_panel(state: AppState) -> None:
    if not state.model_panel_hwnd or not state.overlay_hwnd:
        return
    buf, pw, ph = _render_model_panel(state)
    _show_panel_window(state, state.model_panel_hwnd, buf, pw, ph)
    state.active_panel = "model"


def _hide_model_panel(state: AppState) -> None:
    if state.model_panel_hwnd and state.active_panel == "model":
        ctypes.windll.user32.ShowWindow(state.model_panel_hwnd, 0)
        state.active_panel = None
