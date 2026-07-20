from __future__ import annotations

import ctypes
import ctypes.wintypes
import logging
import time
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from siqspeak.config import (
    COPY_CONFIRM_SECONDS,
    CYAN,
    GRAY,
    LOG_BADGE_FILL,
    LOG_CARD_BORDER,
    LOG_CARD_FILL,
    LOG_CARD_GAP,
    LOG_CARD_MARGIN_X,
    LOG_CARD_PAD_X,
    LOG_CARD_PAD_Y,
    LOG_CARD_RADIUS,
    LOG_COPIED_GREEN,
    LOG_COPY_BTN_W,
    LOG_COPY_IDLE,
    LOG_HEADER_H,
    LOG_LINE_H,
    LOG_META_GAP,
    LOG_META_H,
    LOG_PANEL_MAX_VISIBLE,
    LOG_PANEL_PADDING,
    PILL_BG,
    WHITE,
    _log_panel_dims,
)
from siqspeak.overlay.panels import _show_panel_window
from siqspeak.overlay.rendering import _draw_centered_text, _rgba_to_premul_bgra
from siqspeak.state import AppState

log = logging.getLogger("siqspeak")

_PLACEHOLDER = {"text": "No transcriptions yet", "timestamp": "", "time_epoch": 0}

# Cached font faces (name, size) — display/body/utility roles.
_FONT_DISPLAY = "seguisb.ttf"
_FONT_BODY = "segoeui.ttf"
_FONT_TEXT = "seguisb.ttf"
_SIZE_TEXT = 16

# ---------------------------------------------------------------------------
# Font cache — load each (name, size) pair once; avoid disk I/O on every frame
# ---------------------------------------------------------------------------
_FONT_CACHE: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}


def _get_font(name: str, size: int) -> ImageFont.FreeTypeFont:
    key = (name, size)
    if key not in _FONT_CACHE:
        try:
            _FONT_CACHE[key] = ImageFont.truetype(name, size)
        except OSError:
            _FONT_CACHE[key] = ImageFont.load_default()
    return _FONT_CACHE[key]


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


def _visible_entries(
    transcription_log: list[dict], scroll_offset: int, max_visible: int,
) -> list[dict]:
    """Newest-first slice of the log for the current scroll offset (pure)."""
    total = len(transcription_log)
    end = total - scroll_offset
    start = max(0, end - max_visible)
    return list(reversed(transcription_log[start:end]))


@dataclass(frozen=True)
class CardLayout:
    """Resolved geometry and metadata for one history card."""

    entry: dict
    lines: tuple[str, ...]
    y: int
    height: int
    show_copy: bool
    show_badge: bool
    is_copied: bool


def _card_height(num_lines: int) -> int:
    return LOG_CARD_PAD_Y * 2 + num_lines * LOG_LINE_H + LOG_META_GAP + LOG_META_H


def _layout_cards(
    state: AppState, panel_w: int, max_h: int, now: float,
) -> tuple[list[CardLayout], bool]:
    """Lay out only the cards that fit the visible height.

    Text wrapping (the expensive step) runs one entry at a time and stops as
    soon as the next card would overflow, so a 50-entry log never wraps all 50.
    """
    entries = _visible_entries(
        state.transcription_log, state.log_scroll_offset, LOG_PANEL_MAX_VISIBLE,
    )
    is_empty = not entries
    if is_empty:
        entries = [_PLACEHOLDER]

    font_text = _get_font(_FONT_TEXT, _SIZE_TEXT)
    text_max_w = panel_w - LOG_CARD_MARGIN_X * 2 - LOG_CARD_PAD_X * 2 - LOG_COPY_BTN_W
    is_copied_fresh = (
        state.copied_row is not None and (now - state.copied_time) < COPY_CONFIRM_SECONDS
    )

    y = LOG_HEADER_H + LOG_PANEL_PADDING
    bottom_limit = max_h - LOG_PANEL_PADDING - 8
    cards: list[CardLayout] = []
    for idx, entry in enumerate(entries):
        text = entry.get("text", "")
        lines = _wrap_text(text, font_text, text_max_w) if text else [""]
        height = _card_height(len(lines))
        if cards and y + height > bottom_limit:
            break
        is_real = not is_empty and bool(entry.get("text")) and entry.get("time_epoch", 0) != 0
        cards.append(CardLayout(
            entry=entry,
            lines=tuple(lines),
            y=y,
            height=height,
            show_copy=is_real,
            show_badge=bool(entry.get("enhanced")),
            is_copied=is_copied_fresh and state.copied_row == idx,
        ))
        y += height + LOG_CARD_GAP

    return cards, is_empty


def _draw_copy_icon(
    draw: ImageDraw.ImageDraw, cx: int, cy: int, is_copied: bool,
    font_check: ImageFont.FreeTypeFont,
) -> None:
    """Always-visible, low-contrast clipboard glyph (green check when copied)."""
    if is_copied:
        draw.rounded_rectangle(
            [cx - 15, cy - 15, cx + 15, cy + 15], radius=7, fill=(25, 50, 35, 255),
        )
        _draw_centered_text(draw, "✓", cx, cy, font_check, (*LOG_COPIED_GREEN, 255))
        return
    # Two offset rounded rectangles suggest a clipboard, drawn in quiet gray.
    draw.rounded_rectangle(
        [cx - 8, cy - 4, cx + 4, cy + 10], radius=3, outline=(*LOG_COPY_IDLE, 255), width=2,
    )
    draw.rounded_rectangle(
        [cx - 4, cy - 10, cx + 8, cy + 4], radius=3, outline=(*LOG_COPY_IDLE, 255), width=2,
    )


def _render_log_panel(state: AppState) -> tuple[np.ndarray, int, int]:
    """Render the log panel and return (bgra_buffer, width, height)."""
    panel_w, max_h = _log_panel_dims()

    cards, is_empty = _layout_cards(state, panel_w, max_h, time.time())
    state.log_entry_heights = [card.height + LOG_CARD_GAP for card in cards]

    content_h = sum(card.height for card in cards) + LOG_CARD_GAP * max(0, len(cards) - 1)
    panel_h = min(LOG_HEADER_H + LOG_PANEL_PADDING * 2 + content_h + 8, max_h)

    font_header = _get_font(_FONT_DISPLAY, 22)
    font_sub = _get_font(_FONT_BODY, 15)
    font_text = _get_font(_FONT_TEXT, _SIZE_TEXT)
    font_meta = _get_font(_FONT_BODY, 13)
    font_badge = _get_font(_FONT_DISPLAY, 12)
    font_check = _get_font(_FONT_DISPLAY, 18)
    font_scroll = _get_font(_FONT_BODY, 14)

    img = Image.new("RGBA", (panel_w, panel_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    draw.rounded_rectangle(
        [0, 0, panel_w - 1, panel_h - 1],
        radius=14,
        fill=(PILL_BG[0], PILL_BG[1], PILL_BG[2], 255),
    )

    draw.text((20, 14), "Transcription Log", fill=(*WHITE, 255), font=font_header)
    draw.text((20, 42), "Hold Ctrl+Shift+Space to dictate  •  Release to transcribe",
              fill=(*GRAY, 200), font=font_sub)
    draw.line([(20, LOG_HEADER_H - 4), (panel_w - 20, LOG_HEADER_H - 4)], fill=(*GRAY, 100))

    # Scroll indicators
    total_entries = len(state.transcription_log)
    can_scroll_up = state.log_scroll_offset > 0
    can_scroll_down = total_entries > state.log_scroll_offset + LOG_PANEL_MAX_VISIBLE
    if can_scroll_up:
        draw.text((panel_w - 34, 16), "▲", fill=(*CYAN, 255), font=font_scroll)
    if can_scroll_down:
        draw.text((panel_w - 34, panel_h - 22), "▼", fill=(*CYAN, 255), font=font_scroll)

    card_left = LOG_CARD_MARGIN_X
    card_right = panel_w - LOG_CARD_MARGIN_X
    text_left = card_left + LOG_CARD_PAD_X

    for card in cards:
        top = card.y
        bottom = card.y + card.height
        if bottom > panel_h:
            break

        if not is_empty:
            draw.rounded_rectangle(
                [card_left, top, card_right, bottom],
                radius=LOG_CARD_RADIUS,
                fill=(*LOG_CARD_FILL, 255),
                outline=(*LOG_CARD_BORDER, 255),
                width=1,
            )

        # Primary content: the final (typed) text.
        text_y = top + LOG_CARD_PAD_Y
        for li, line in enumerate(card.lines):
            draw.text((text_left, text_y + li * LOG_LINE_H), line,
                      fill=(*WHITE, 255), font=font_text)

        # Metadata row: timestamp + optional Enhanced badge.
        meta_y = text_y + len(card.lines) * LOG_LINE_H + LOG_META_GAP
        ts = card.entry.get("timestamp", "")
        meta_x = text_left
        if ts:
            draw.text((meta_x, meta_y + 2), ts, fill=(*GRAY, 200), font=font_meta)
            meta_x += int(font_meta.getlength(ts)) + 12
        if card.show_badge:
            label = "Enhanced"
            label_w = int(font_badge.getlength(label))
            draw.rounded_rectangle(
                [meta_x, meta_y, meta_x + label_w + 16, meta_y + LOG_META_H - 2],
                radius=8, fill=(*LOG_BADGE_FILL, 255),
            )
            draw.text((meta_x + 8, meta_y + 2), label, fill=(*CYAN, 255), font=font_badge)

        # Always-visible copy control at the card's top-right.
        if card.show_copy:
            icon_cx = card_right - LOG_CARD_PAD_X - 8
            icon_cy = top + LOG_CARD_PAD_Y + 6
            _draw_copy_icon(draw, icon_cx, icon_cy, card.is_copied, font_check)

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
