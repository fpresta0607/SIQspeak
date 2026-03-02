from __future__ import annotations

import ctypes
import ctypes.wintypes
import logging
import time

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from siqspeak.config import (
    CYAN,
    GRAY,
    LOG_COPY_BTN_W,
    LOG_HEADER_H,
    LOG_LINE_H,
    LOG_PANEL_MAX_VISIBLE,
    LOG_PANEL_PADDING,
    LOG_TEXT_LEFT,
    PILL_BG,
    WHITE,
    _log_panel_dims,
)
from siqspeak.overlay.panels import _show_panel_window
from siqspeak.overlay.rendering import _draw_centered_text, _rgba_to_premul_bgra
from siqspeak.state import AppState

log = logging.getLogger("siqspeak")


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


def _render_log_panel(state: AppState) -> tuple[np.ndarray, int, int]:
    """Render the log panel and return (bgra_buffer, width, height)."""
    panel_w, max_h = _log_panel_dims()

    total_entries = len(state.transcription_log)
    max_vis = LOG_PANEL_MAX_VISIBLE
    # Apply scroll offset: offset=0 shows newest, offset>0 shows older
    end = total_entries - state.log_scroll_offset
    start = max(0, end - max_vis)
    entries = list(reversed(state.transcription_log[start:end]))
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

    state.log_entry_heights = [rh for _, rh in entry_layouts]
    content_h = sum(state.log_entry_heights)
    panel_h = min(LOG_HEADER_H + LOG_PANEL_PADDING * 2 + content_h + 8, max_h)

    img = Image.new("RGBA", (panel_w, panel_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    draw.rounded_rectangle(
        [0, 0, panel_w - 1, panel_h - 1],
        radius=14,
        fill=(PILL_BG[0], PILL_BG[1], PILL_BG[2], 255),
    )

    draw.text((20, 14), "Transcription Log", fill=(*WHITE, 230), font=font_header)
    draw.text((20, 42), "Hold Ctrl+Shift+Space to dictate  \u2022  Release to transcribe",
              fill=(*GRAY, 150), font=font_sub)
    draw.line([(20, LOG_HEADER_H - 4), (panel_w - 20, LOG_HEADER_H - 4)], fill=(*GRAY, 50))

    # Scroll indicators
    can_scroll_up = state.log_scroll_offset > 0
    can_scroll_down = total_entries > state.log_scroll_offset + max_vis
    if can_scroll_up:
        draw.text((panel_w - 34, 16), "\u25b2", fill=(*CYAN, 150), font=font_scroll)
    if can_scroll_down:
        draw.text((panel_w - 34, panel_h - 22), "\u25bc", fill=(*CYAN, 150), font=font_scroll)

    is_copied_fresh = state.copied_row is not None and (time.time() - state.copied_time) < 1.5

    y = LOG_HEADER_H + LOG_PANEL_PADDING
    for idx, (entry, (wrapped_lines, row_h)) in enumerate(zip(entries, entry_layouts, strict=False)):
        if y + row_h > panel_h:
            break

        ts = entry.get("timestamp", "")
        if ts:
            draw.text((20, y + 12), ts, fill=(*GRAY, 150), font=font_ts)

        for li, line in enumerate(wrapped_lines):
            draw.text((LOG_TEXT_LEFT, y + 10 + li * LOG_LINE_H), line,
                       fill=(*WHITE, 245), font=font_text)

        # Copy button: only for real transcriptions, visible on hover/copied
        has_text = bool(entry.get("text")) and entry.get("time_epoch", 0) != 0
        if has_text:
            copy_x = panel_w - LOG_COPY_BTN_W - 8
            btn_cy = y + row_h // 2
            is_hover = (state.copy_hover_row == idx)
            is_just_copied = (is_copied_fresh and state.copied_row == idx)

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

        if idx < len(entries) - 1:
            div_y = y + row_h - 1
            draw.line([(20, div_y), (panel_w - 20, div_y)], fill=(*GRAY, 30))

        y += row_h

    return _rgba_to_premul_bgra(img), panel_w, panel_h


def _show_log_panel(state: AppState) -> None:
    """Render and display the log panel above the pill."""
    if not state.log_panel_hwnd or not state.overlay_hwnd:
        return
    # Reset scroll to newest on fresh open (not on re-render from scroll)
    if state.active_panel != "info":
        state.log_scroll_offset = 0
    buf, pw, ph = _render_log_panel(state)
    _show_panel_window(state, state.log_panel_hwnd, buf, pw, ph)
    state.active_panel = "info"


def _hide_log_panel(state: AppState) -> None:
    if state.log_panel_hwnd and state.active_panel == "info":
        ctypes.windll.user32.ShowWindow(state.log_panel_hwnd, 0)  # SW_HIDE
        state.active_panel = None
