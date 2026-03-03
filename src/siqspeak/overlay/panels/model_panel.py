from __future__ import annotations

import ctypes
import ctypes.wintypes
import logging

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
from siqspeak.hf_auth import has_token

log = logging.getLogger("siqspeak")


def _render_hf_auth_panel(state: AppState) -> tuple[np.ndarray, int, int]:
    """Render the HuggingFace authentication dialog panel."""
    panel_w = _model_panel_width()
    panel_h = 280

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

    img = Image.new("RGBA", (panel_w, panel_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle(
        [0, 0, panel_w - 1, panel_h - 1], radius=14,
        fill=(PILL_BG[0], PILL_BG[1], PILL_BG[2], 255),
    )

    # Success state — auto-dismiss after showing confirmation
    if state.hf_auth_success:
        import time
        draw.text((panel_w // 2, 60), "\u2713", fill=(*GREEN, 255),
                  font=font_icon, anchor="mm")
        draw.text((panel_w // 2, 100), "Signed in!",
                  fill=(*GREEN, 255), font=font_title, anchor="mm")
        username = state.hf_username or "authenticated"
        draw.text((panel_w // 2, 130), f"Welcome, {username}",
                  fill=(*WHITE, 180), font=font, anchor="mm")
        draw.text((panel_w // 2, 160), "Starting download...",
                  fill=(*CYAN, 180), font=font_small, anchor="mm")
        return _rgba_to_premul_bgra(img), panel_w, panel_h

    # Verifying state
    if state.hf_auth_verifying:
        draw.text((panel_w // 2, 80), "...", fill=(*CYAN, 255),
                  font=font_icon, anchor="mm")
        draw.text((panel_w // 2, 120), "Verifying token...",
                  fill=(*CYAN, 200), font=font, anchor="mm")
        return _rgba_to_premul_bgra(img), panel_w, panel_h

    # Header
    y = 14
    draw.text((20, y), "\U0001F511  Sign In Required", fill=(*WHITE, 240), font=font_title)
    y += 32

    draw.line([(20, y), (panel_w - 20, y)], fill=(*GRAY, 50))
    y += 12

    # Explanation
    draw.text((20, y), "SIQspeak needs a free HuggingFace",
              fill=(*WHITE, 180), font=font_small)
    y += 18
    draw.text((20, y), "account to download AI models.",
              fill=(*WHITE, 180), font=font_small)
    y += 28

    # Steps
    draw.text((20, y), "1.", fill=(*CYAN, 220), font=font)
    draw.text((44, y), "Click below to open your browser",
              fill=(*WHITE, 200), font=font_small)
    y += 22
    draw.text((20, y), "2.", fill=(*CYAN, 220), font=font)
    draw.text((44, y), "Sign up or log in (free)",
              fill=(*WHITE, 200), font=font_small)
    y += 22
    draw.text((20, y), "3.", fill=(*CYAN, 220), font=font)
    draw.text((44, y), "Copy your access token",
              fill=(*WHITE, 200), font=font_small)
    y += 22
    draw.text((20, y), "4.", fill=(*CYAN, 220), font=font)
    draw.text((44, y), "Paste it here (click Paste & Verify)",
              fill=(*WHITE, 200), font=font_small)
    y += 30

    # Buttons: [Open Browser]  [Paste & Verify]  [Cancel]
    btn_y = y
    # "Open Browser" button
    draw.rounded_rectangle(
        [20, btn_y, 140, btn_y + 30], radius=6,
        fill=(*CYAN, 40), outline=(*CYAN, 120))
    draw.text((80, btn_y + 15), "Open Browser",
              fill=(*CYAN, 240), font=font_small, anchor="mm")

    # "Paste & Verify" button
    draw.rounded_rectangle(
        [150, btn_y, 280, btn_y + 30], radius=6,
        fill=(*CYAN, 40), outline=(*CYAN, 120))
    draw.text((215, btn_y + 15), "Paste & Verify",
              fill=(*CYAN, 240), font=font_small, anchor="mm")

    # "Cancel" button
    draw.rounded_rectangle(
        [290, btn_y, 350, btn_y + 30], radius=6,
        fill=(*GRAY, 20), outline=(*GRAY, 60))
    draw.text((320, btn_y + 15), "Cancel",
              fill=(*GRAY, 180), font=font_small, anchor="mm")

    # Error message
    if state.hf_auth_error:
        import time
        if time.time() - state.hf_auth_error_time < 5.0:
            draw.text((20, btn_y + 38), state.hf_auth_error,
                      fill=(*ORANGE, 220), font=font_small)

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
    except OSError:
        font_title = ImageFont.load_default()
        font = font_title
        font_small = font
        font_check = font

    ORANGE = (255, 160, 50)

    # --- Loading view: compact panel with just the loading model ---
    if state.model_loading:
        panel_h = MODEL_PANEL_HEADER_H + MODEL_PANEL_ROW_H + 16
        img = Image.new("RGBA", (panel_w, panel_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.rounded_rectangle(
            [0, 0, panel_w - 1, panel_h - 1], radius=14,
            fill=(PILL_BG[0], PILL_BG[1], PILL_BG[2], 255),
        )
        draw.text((20, 12), "Models", fill=(*WHITE, 230), font=font_title)
        draw.line([(20, MODEL_PANEL_HEADER_H - 4), (panel_w - 20, MODEL_PANEL_HEADER_H - 4)],
                  fill=(*GRAY, 50))

        name = state.model_loading_name
        y = MODEL_PANEL_HEADER_H
        text_y = y + (MODEL_PANEL_ROW_H - 18) // 2
        is_downloading = (state.download_progress < 1.0 and state.download_progress > 0.0)
        is_download_starting = (state.download_progress == 0.0
                                and state.model_loading_is_download)

        if is_downloading or is_download_starting:
            draw.text((54, text_y - 4), name, fill=(*CYAN, 220), font=font)
            if is_downloading:
                pct_text = f"{int(state.download_progress * 100)}%"
                draw.text((panel_w - 20, text_y - 2), pct_text,
                          fill=(*CYAN, 200), font=font_small, anchor="ra")
                bar_x = 54
                bar_y = y + MODEL_PANEL_ROW_H - 16
                bar_w = panel_w - 54 - 20
                bar_h = 4
                draw.rounded_rectangle(
                    [bar_x, bar_y, bar_x + bar_w, bar_y + bar_h],
                    radius=2, fill=(*GRAY, 40))
                fill_w = int(bar_w * state.download_progress)
                if fill_w > 0:
                    draw.rounded_rectangle(
                        [bar_x, bar_y, bar_x + fill_w, bar_y + bar_h],
                        radius=2, fill=(*CYAN, 200))
            else:
                draw.text((panel_w - 20, text_y - 2), "Connecting...",
                          fill=(*GRAY, 150), font=font_small, anchor="ra")
        else:
            draw.text((20, text_y), "...", fill=(*CYAN, 200), font=font_small)
            draw.text((54, text_y), name, fill=(*CYAN, 220), font=font)
            draw.text((panel_w - 20, text_y + 2), "Loading...",
                      fill=(*GRAY, 150), font=font_small, anchor="ra")

        return _rgba_to_premul_bgra(img), panel_w, panel_h

    # --- Normal view: full model list ---
    row_count = len(AVAILABLE_MODELS)
    panel_h = MODEL_PANEL_HEADER_H + row_count * MODEL_PANEL_ROW_H + 16

    img = Image.new("RGBA", (panel_w, panel_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle(
        [0, 0, panel_w - 1, panel_h - 1], radius=14,
        fill=(PILL_BG[0], PILL_BG[1], PILL_BG[2], 255),
    )

    # Header
    draw.text((20, 12), "Models", fill=(*WHITE, 230), font=font_title)
    draw.line([(20, MODEL_PANEL_HEADER_H - 4), (panel_w - 20, MODEL_PANEL_HEADER_H - 4)],
              fill=(*GRAY, 50))

    for idx, name in enumerate(AVAILABLE_MODELS):
        y = MODEL_PANEL_HEADER_H + idx * MODEL_PANEL_ROW_H
        is_loaded = (name == state.loaded_model_name)
        is_confirming = (name == state.download_confirm_name and not state.model_loading)
        has_error = (state.download_error and name == state.model_loading_name
                     and not state.model_loading)
        is_cached = _is_model_cached(name) if not is_loaded else True
        size_mb = MODEL_SIZES_MB.get(name, 0)

        # Hover highlight (skip for loaded/confirming rows)
        is_hovered = (idx == state.model_hover_row
                      and not is_loaded and not is_confirming)
        if is_hovered:
            draw.rounded_rectangle(
                [4, y + 2, panel_w - 4, y + MODEL_PANEL_ROW_H - 2],
                radius=8, fill=(30, 38, 58, 255))

        # Vertically center text in row
        text_y = y + (MODEL_PANEL_ROW_H - 18) // 2

        if has_error:
            draw.text((54, text_y), name, fill=(*ORANGE, 240), font=font)
            draw.text((panel_w - 20, text_y + 2), state.download_error,
                      fill=(*ORANGE, 200), font=font_small, anchor="ra")
        elif is_confirming:
            draw.rounded_rectangle(
                [4, y + 2, panel_w - 4, y + MODEL_PANEL_ROW_H - 2],
                radius=8, fill=(20, 30, 48, 255))
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
            draw.text((panel_w - 20, text_y + 2), "Ready",
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
