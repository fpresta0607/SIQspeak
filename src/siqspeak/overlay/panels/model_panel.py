from __future__ import annotations

import ctypes
import logging
import time

import numpy as np
from PIL import Image, ImageDraw

from siqspeak.config import (
    CYAN,
    GRAY,
    MODEL_PANEL_HEADER_H,
    MODEL_PANEL_ROW_H,
    PILL_BG,
    SPEECH_MODELS,
    WHITE,
    _model_panel_width,
)
from siqspeak.model.manager import _is_model_cached
from siqspeak.overlay.panels import _show_panel_window
from siqspeak.overlay.panels.log_panel import _get_font
from siqspeak.overlay.rendering import _rgba_to_premul_bgra
from siqspeak.state import AppState

log = logging.getLogger("siqspeak")

# Fully opaque background — no see-through
BG = (PILL_BG[0], PILL_BG[1], PILL_BG[2], 255)
DIVIDER = (GRAY[0], GRAY[1], GRAY[2], 80)
ROW_HOVER = (30, 38, 58, 255)
GREEN = (80, 220, 120)


def _size_label(size_mb: int) -> str:
    """Human-readable approximate model size."""
    if size_mb < 1000:
        return f"~{size_mb} MB"
    return f"~{size_mb / 1000:.1f} GB"


def _render_model_panel(state: AppState) -> tuple[np.ndarray, int, int]:
    """Render the curated English speech-model selector with cache/download state."""
    panel_w = _model_panel_width()

    font_title = _get_font("seguisb.ttf", 22)
    font = _get_font("seguisb.ttf", 18)
    font_small = _get_font("segoeui.ttf", 14)
    font_tier = _get_font("segoeui.ttf", 12)
    font_check = _get_font("seguisb.ttf", 20)

    # Clear stale download errors after 3 seconds
    if state.download_error and time.time() - state.download_error_time > 3.0:
        state.download_error = None

    # --- Loading / downloading view ---
    if state.model_loading:
        panel_h = MODEL_PANEL_HEADER_H + MODEL_PANEL_ROW_H + 16
        img = Image.new("RGBA", (panel_w, panel_h), BG)
        draw = ImageDraw.Draw(img)
        draw.rounded_rectangle([0, 0, panel_w - 1, panel_h - 1], radius=14, fill=BG)

        draw.text((20, 12), "Models", fill=(*WHITE, 255), font=font_title)
        draw.line([(20, MODEL_PANEL_HEADER_H - 4), (panel_w - 20, MODEL_PANEL_HEADER_H - 4)],
                  fill=DIVIDER)

        name = state.model_loading_name
        y = MODEL_PANEL_HEADER_H
        text_y = y + (MODEL_PANEL_ROW_H - 18) // 2
        is_downloading = 0.0 < state.download_progress < 1.0

        if state.model_loading_is_download:
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
                draw.text((panel_w - 20, text_y - 2), "Downloading...",
                          fill=(*GRAY, 200), font=font_small, anchor="ra")
        else:
            draw.text((54, text_y), name, fill=(*CYAN, 255), font=font)
            draw.text((panel_w - 20, text_y + 2), "Loading...",
                      fill=(*GRAY, 200), font=font_small, anchor="ra")

        return _rgba_to_premul_bgra(img), panel_w, panel_h

    # --- Normal view: curated model list ---
    row_count = len(SPEECH_MODELS)
    panel_h = MODEL_PANEL_HEADER_H + row_count * MODEL_PANEL_ROW_H + 16

    img = Image.new("RGBA", (panel_w, panel_h), BG)
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([0, 0, panel_w - 1, panel_h - 1], radius=14, fill=BG)

    # Header
    draw.text((20, 12), "Models", fill=(*WHITE, 255), font=font_title)
    header_bottom = MODEL_PANEL_HEADER_H
    draw.line([(20, header_bottom - 4), (panel_w - 20, header_bottom - 4)], fill=DIVIDER)

    for idx, item in enumerate(SPEECH_MODELS):
        name = item["name"]
        tier = item["tier"]
        size_mb = item["size_mb"]
        y = header_bottom + idx * MODEL_PANEL_ROW_H

        is_loaded = name == state.loaded_model_name
        is_confirming = name == state.download_confirm_name and not state.model_loading
        has_error = bool(state.download_error) and name == state.model_loading_name
        is_cached = True if is_loaded else _is_model_cached(name)

        is_hovered = idx == state.model_hover_row and not is_loaded and not is_confirming
        if is_hovered:
            draw.rounded_rectangle(
                [4, y + 2, panel_w - 4, y + MODEL_PANEL_ROW_H - 2],
                radius=8, fill=ROW_HOVER)

        name_y = y + 10
        tier_y = y + 34

        if has_error:
            draw.text((20, name_y), name, fill=(*CYAN, 255), font=font)
            draw.text((20, tier_y), tier, fill=(*GRAY, 200), font=font_tier)
            draw.text((panel_w - 20, y + 20), state.download_error or "",
                      fill=(*CYAN, 255), font=font_small, anchor="ra")
        elif is_confirming:
            draw.rounded_rectangle(
                [4, y + 2, panel_w - 4, y + MODEL_PANEL_ROW_H - 2],
                radius=8, fill=(20, 30, 48, 255))
            draw.text((20, name_y), name, fill=(*CYAN, 255), font=font)
            draw.text((20, tier_y), f"Download {_size_label(size_mb)}?",
                      fill=(*CYAN, 255), font=font_small)
            draw.text((panel_w - 20, y + 20), "click to confirm",
                      fill=(*CYAN, 200), font=font_small, anchor="ra")
        elif is_loaded:
            draw.text((20, name_y - 2), "✓", fill=(*CYAN, 255), font=font_check)
            draw.text((44, name_y), name, fill=(*CYAN, 255), font=font)
            draw.text((44, tier_y), f"{tier} · current",
                      fill=(*CYAN, 200), font=font_tier)
        elif is_cached:
            draw.text((20, name_y), name, fill=(*WHITE, 255), font=font)
            draw.text((20, tier_y), tier, fill=(*GRAY, 200), font=font_tier)
            draw.text((panel_w - 20, y + 20), "Ready",
                      fill=(*GREEN, 200), font=font_small, anchor="ra")
        else:
            draw.text((20, name_y), name, fill=(*WHITE, 220), font=font)
            draw.text((20, tier_y), tier, fill=(*GRAY, 200), font=font_tier)
            draw.text((panel_w - 20, y + 20), _size_label(size_mb),
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
