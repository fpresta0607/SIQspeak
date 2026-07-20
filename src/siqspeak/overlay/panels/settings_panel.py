"""Settings panel: microphone, prompt enhancement, workspace, and Quit.

Layout geometry lives in one pure place (:func:`_settings_layout`) so the
renderer and the click hit-tester (:func:`settings_action_at_y`) never drift.
Enhancer status is read from ``AppState`` — the render never touches the
network; background refresh/pull helpers update state and let the message loop
re-render on change.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes
import logging
import threading
import webbrowser
from dataclasses import dataclass
from enum import Enum

import numpy as np
from PIL import Image, ImageDraw

from siqspeak.audio.devices import _get_input_devices
from siqspeak.config import (
    CYAN,
    ENHANCEMENT_MODEL,
    ENHANCEMENT_MODEL_DOWNLOAD_GB,
    ENHANCEMENT_MODEL_MIN_GB,
    GRAY,
    LOG_CARD_BORDER,
    LOG_CARD_FILL,
    PILL_BG,
    SETTINGS_HEADER_H,
    WHITE,
    _settings_panel_width,
)
from siqspeak.enhancement.hardware import can_run_model
from siqspeak.enhancement.ollama import OllamaClient, OllamaError, OllamaUnavailable
from siqspeak.overlay.panels import _show_panel_window
from siqspeak.overlay.panels.log_panel import _get_font
from siqspeak.overlay.rendering import _draw_centered_text, _rgba_to_premul_bgra
from siqspeak.state import AppState

log = logging.getLogger("siqspeak")

OLLAMA_DOWNLOAD_URL = "https://ollama.com/download/windows"

# Layout constants (kept local to this panel; SETTINGS_HEADER_H is shared).
SETTINGS_PAD = 12
SETTINGS_GAP = 10
SETTINGS_ROW_H = 48
SETTINGS_STATUS_H = 84  # model requirement + machine readout + status/action
QUIT_BTN_H = 44
SETTINGS_CARD_MARGIN_X = 16
SETTINGS_CARD_PAD_X = 14
SETTINGS_CARD_RADIUS = 10
MIC_ROW_H = 32

_ACCENT_SOFT = (16, 46, 54)  # cyan-tinted fill for selected chips / badges


class SettingsAction(str, Enum):
    """Stable identifiers for each clickable settings region."""

    MICROPHONE = "microphone"
    ENHANCEMENT_TOGGLE = "enhancement_toggle"
    WORKSPACE = "workspace"
    INSTALL_MODEL = "install_model"
    QUIT = "quit"


@dataclass(frozen=True)
class SettingsRow:
    """Resolved vertical band for one settings action."""

    action: SettingsAction
    y: int
    height: int


def _mic_section_height(state: AppState) -> int:
    if state.mic_expanded and state.mic_devices:
        return SETTINGS_ROW_H + len(state.mic_devices) * MIC_ROW_H + 8
    return SETTINGS_ROW_H


def _settings_layout(state: AppState) -> list[SettingsRow]:
    """Ordered, stacked rows for the whole panel (pure geometry)."""
    y = SETTINGS_HEADER_H + SETTINGS_PAD
    plan: list[tuple[SettingsAction, int]] = [
        (SettingsAction.MICROPHONE, _mic_section_height(state)),
        (SettingsAction.ENHANCEMENT_TOGGLE, SETTINGS_ROW_H),
        (SettingsAction.WORKSPACE, SETTINGS_ROW_H),
        (SettingsAction.INSTALL_MODEL, SETTINGS_STATUS_H),
        (SettingsAction.QUIT, QUIT_BTN_H),
    ]
    rows: list[SettingsRow] = []
    for action, height in plan:
        rows.append(SettingsRow(action, y, height))
        y += height + SETTINGS_GAP
    return rows


def settings_action_at_y(state: AppState, y: int) -> SettingsAction | None:
    """Map a panel-relative y to its action, or None (Win32-free)."""
    if y < SETTINGS_HEADER_H:
        return None
    for row in _settings_layout(state):
        if row.y <= y < row.y + row.height:
            return row.action
    return None


def _settings_panel_height(state: AppState) -> int:
    last = _settings_layout(state)[-1]
    return last.y + last.height + SETTINGS_PAD


# ---------------------------------------------------------------------------
# Display helpers (pure)
# ---------------------------------------------------------------------------
def _model_requirement_label() -> str:
    """Fixed-model line, e.g. ``qwen3.5:2b · ~2.7 GB · needs ~4 GB``."""
    return (
        f"{ENHANCEMENT_MODEL} · ~{ENHANCEMENT_MODEL_DOWNLOAD_GB:.1f} GB"
        f" · needs ~{ENHANCEMENT_MODEL_MIN_GB:.0f} GB"
    )


def _workspace_display(state: AppState) -> tuple[str, str]:
    """Return (chip, path) for the workspace row.

    Manual override wins ("Manual"); else the last auto-detected root ("Auto");
    else a "Not detected yet" hint noting detection runs at dictation time.
    """
    if state.workspace_override:
        return ("Manual", state.workspace_override)
    if state.workspace_detected_root:
        return ("Auto", state.workspace_detected_root)
    return ("Auto", "Not detected yet · resolves from focused window")


def _status_display(state: AppState) -> tuple[str, str | None]:
    """Return (message, action_label) for the enhancer status row."""
    status = state.enhancement_status
    if status == "pulling":
        percent = round(state.enhancement_pull_progress * 100)
        return (f"Downloading {state.enhancement_model}  {percent}%", None)
    if status == "ollama_missing":
        return ("Ollama isn't running", "Get Ollama")
    if status == "model_missing":
        return (f"{state.enhancement_model} not downloaded", "Download")
    if status == "ready":
        return ("Enhancer ready", None)
    if status == "error":
        return (state.enhancement_error or "Enhancement error", "Retry")
    return ("Checking Ollama…", None)


def _settings_render_signature(state: AppState) -> tuple:
    """State fields that affect the rendered panel — re-render only on change."""
    return (
        state.mic_expanded,
        state.mic_device,
        len(state.mic_devices),
        state.enhancement_enabled,
        state.enhancement_status,
        int(state.enhancement_pull_progress * 100),
        state.workspace_override,
        state.workspace_detected_root,
        state.enhancement_error,
        state.enhancement_hardware,
    )


def _truncate_to_width(
    draw: ImageDraw.ImageDraw, text: str, font, max_width: int,
) -> str:
    """Left-truncate a path with an ellipsis so its tail stays visible."""
    if draw.textlength(text, font=font) <= max_width:
        return text
    ellipsis = "…"
    while text and draw.textlength(ellipsis + text, font=font) > max_width:
        text = text[1:]
    return ellipsis + text if text else ellipsis


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
def _render_settings_panel(state: AppState) -> tuple[np.ndarray, int, int]:
    """Render the settings panel and return (bgra_buffer, width, height)."""
    panel_w = _settings_panel_width()
    panel_h = _settings_panel_height(state)
    rows = {row.action: row for row in _settings_layout(state)}

    font_title = _get_font("seguisb.ttf", 22)
    font_label = _get_font("seguisb.ttf", 16)
    font_value = _get_font("segoeui.ttf", 14)
    font_meta = _get_font("segoeui.ttf", 13)
    font_chip = _get_font("seguisb.ttf", 13)
    font_btn = _get_font("seguisb.ttf", 18)

    img = Image.new("RGBA", (panel_w, panel_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle(
        [0, 0, panel_w - 1, panel_h - 1], radius=14, fill=(*PILL_BG, 255),
    )

    draw.text((20, 12), "Settings", fill=(*WHITE, 255), font=font_title)
    draw.line(
        [(20, SETTINGS_HEADER_H - 4), (panel_w - 20, SETTINGS_HEADER_H - 4)],
        fill=(*GRAY, 100),
    )

    card_left = SETTINGS_CARD_MARGIN_X
    card_right = panel_w - SETTINGS_CARD_MARGIN_X
    text_left = card_left + SETTINGS_CARD_PAD_X
    value_right = card_right - SETTINGS_CARD_PAD_X

    _draw_card(draw, card_left, rows[SettingsAction.MICROPHONE], card_right)
    _draw_microphone(draw, state, rows[SettingsAction.MICROPHONE],
                     text_left, value_right, card_left, card_right, font_label, font_value)

    _draw_card(draw, card_left, rows[SettingsAction.ENHANCEMENT_TOGGLE], card_right)
    _draw_toggle(draw, state, rows[SettingsAction.ENHANCEMENT_TOGGLE],
                 text_left, value_right, font_label)

    _draw_card(draw, card_left, rows[SettingsAction.WORKSPACE], card_right)
    _draw_workspace(draw, state, rows[SettingsAction.WORKSPACE],
                    text_left, value_right, font_label, font_meta, font_chip)

    _draw_card(draw, card_left, rows[SettingsAction.INSTALL_MODEL], card_right)
    _draw_status(draw, state, rows[SettingsAction.INSTALL_MODEL],
                 text_left, value_right, card_left, card_right, font_label, font_meta, font_chip)

    _draw_quit(draw, rows[SettingsAction.QUIT], card_left, card_right, panel_w, font_btn)

    return _rgba_to_premul_bgra(img), panel_w, panel_h


def _draw_card(draw: ImageDraw.ImageDraw, left: int, row: SettingsRow, right: int) -> None:
    draw.rounded_rectangle(
        [left, row.y, right, row.y + row.height],
        radius=SETTINGS_CARD_RADIUS,
        fill=(*LOG_CARD_FILL, 255),
        outline=(*LOG_CARD_BORDER, 255),
        width=1,
    )


def _draw_microphone(
    draw, state, row, text_left, value_right, card_left, card_right, font_label, font_value,
) -> None:
    header_cy = row.y + SETTINGS_ROW_H // 2
    draw.text((text_left, header_cy - 9), "Microphone", font=font_label, fill=(*WHITE, 255))

    if state.mic_devices:
        if state.mic_device is not None:
            mic_name = next(
                (d["name"] for d in state.mic_devices if d["index"] == state.mic_device),
                "Default",
            )
        else:
            mic_name = "Default"
    else:
        mic_name = "No devices"
    chevron = "▼" if state.mic_expanded else "▶"
    label = f"{mic_name}  {chevron}"
    label = _truncate_to_width(draw, label, font_value, value_right - text_left - 90)
    lw = draw.textlength(label, font=font_value)
    draw.text((value_right - lw, header_cy - 8), label, font=font_value, fill=(*CYAN, 255))

    if not (state.mic_expanded and state.mic_devices):
        return
    dev_y = row.y + SETTINGS_ROW_H
    for dev in state.mic_devices:
        is_selected = dev["index"] == state.mic_device
        if is_selected:
            draw.rounded_rectangle(
                [card_left + 6, dev_y, card_right - 6, dev_y + MIC_ROW_H],
                radius=6, fill=(20, 35, 50, 255),
            )
        color = (*CYAN, 255) if is_selected else (*WHITE, 180)
        name = _truncate_to_width(draw, dev["name"], font_value, card_right - text_left - 12)
        draw.text((text_left, dev_y + 7), name, font=font_value, fill=color)
        dev_y += MIC_ROW_H


def _draw_toggle(draw, state, row, text_left, value_right, font_label) -> None:
    cy = row.y + row.height // 2
    draw.text((text_left, cy - 9), "Enhance prompts", font=font_label, fill=(*WHITE, 255))

    track_w, track_h = 46, 22
    tx1 = value_right
    tx0 = tx1 - track_w
    ty0 = cy - track_h // 2
    on = state.enhancement_enabled
    track = CYAN if on else GRAY
    draw.rounded_rectangle([tx0, ty0, tx1, ty0 + track_h], radius=track_h // 2, fill=(*track, 255))
    knob_r = track_h // 2 - 3
    knob_cx = (tx1 - knob_r - 3) if on else (tx0 + knob_r + 3)
    draw.ellipse(
        [knob_cx - knob_r, cy - knob_r, knob_cx + knob_r, cy + knob_r], fill=(255, 255, 255, 255),
    )


def _draw_workspace(draw, state, row, text_left, value_right, font_label, font_meta, font_chip) -> None:
    draw.text((text_left, row.y + 7), "Workspace", font=font_label, fill=(*WHITE, 255))

    status, path = _workspace_display(state)
    chip_w = int(draw.textlength(status, font=font_chip)) + 16
    chip_x1 = value_right
    chip_x0 = chip_x1 - chip_w
    chip_y = row.y + 8
    draw.rounded_rectangle(
        [chip_x0, chip_y, chip_x1, chip_y + 18], radius=9, fill=(*_ACCENT_SOFT, 255),
    )
    draw.text((chip_x0 + 8, chip_y + 2), status, font=font_chip, fill=(*CYAN, 255))

    path = _truncate_to_width(draw, path, font_meta, value_right - text_left)
    draw.text((text_left, row.y + 27), path, font=font_meta, fill=(*GRAY, 210))


def _draw_status(
    draw, state, row, text_left, value_right, card_left, card_right, font_label, font_meta, font_chip,
) -> None:
    # Fixed model + its requirement, then the detected-hardware readout.
    draw.text((text_left, row.y + 8), _model_requirement_label(), font=font_label, fill=(*WHITE, 255))
    if state.enhancement_hardware:
        readout = _truncate_to_width(draw, state.enhancement_hardware, font_meta, value_right - text_left)
        draw.text((text_left, row.y + 30), readout, font=font_meta, fill=(*GRAY, 210))

    message, action = _status_display(state)

    if state.enhancement_status == "pulling":
        draw.text((text_left, row.y + 50), message, font=font_meta, fill=(*CYAN, 230))
        bar_y = row.y + row.height - 12
        bar_left = text_left
        bar_right = value_right
        draw.rounded_rectangle(
            [bar_left, bar_y, bar_right, bar_y + 6], radius=3, fill=(40, 50, 70, 255),
        )
        frac = max(0.0, min(1.0, state.enhancement_pull_progress))
        fill_right = bar_left + int((bar_right - bar_left) * frac)
        if fill_right > bar_left:
            draw.rounded_rectangle(
                [bar_left, bar_y, fill_right, bar_y + 6], radius=3, fill=(*CYAN, 255),
            )
        return

    msg_color = (*GRAY, 210)
    if state.enhancement_status == "ready":
        msg_color = (*CYAN, 220)
    elif state.enhancement_status == "error":
        msg_color = (220, 90, 90, 230)
    message = _truncate_to_width(draw, message, font_meta, value_right - text_left - 110)
    draw.text((text_left, row.y + 52), message, font=font_meta, fill=msg_color)

    if action:
        btn_w = int(draw.textlength(action, font=font_chip)) + 24
        btn_h = 26
        bx1 = value_right
        bx0 = bx1 - btn_w
        by0 = row.y + 48
        draw.rounded_rectangle(
            [bx0, by0, bx1, by0 + btn_h], radius=8, fill=(*_ACCENT_SOFT, 255),
            outline=(*CYAN, 200), width=1,
        )
        _draw_centered_text(draw, action, (bx0 + bx1) // 2, by0 + btn_h // 2,
                            font_chip, (*CYAN, 255))


def _draw_quit(draw, row, card_left, card_right, panel_w, font_btn) -> None:
    draw.rounded_rectangle(
        [card_left, row.y, card_right, row.y + row.height], radius=8, fill=(180, 40, 40, 255),
    )
    _draw_centered_text(draw, "Quit", panel_w // 2, row.y + row.height // 2,
                        font_btn, (255, 255, 255, 240))


# ---------------------------------------------------------------------------
# Background enhancer helpers (state mutation + threads; no rendering)
# ---------------------------------------------------------------------------
def _open_ollama_download() -> None:
    """Open the official Ollama Windows download page in the default browser."""
    webbrowser.open(OLLAMA_DOWNLOAD_URL)


def _refresh_enhancer_status(state: AppState) -> None:
    """Probe Ollama in the background and store a status string on state."""
    def worker() -> None:
        # Probe hardware off the render thread (nvidia-smi may take a moment).
        state.enhancement_hardware = can_run_model(ENHANCEMENT_MODEL_MIN_GB)[1]
        client = OllamaClient()
        try:
            if not client.is_available():
                state.enhancement_status = "ollama_missing"
            elif not client.has_model(state.enhancement_model):
                state.enhancement_status = "model_missing"
            else:
                state.enhancement_status = "ready"
            state.enhancement_error = None
        except OllamaError:
            state.enhancement_status = "ollama_missing"

    threading.Thread(target=worker, daemon=True).start()


def _start_model_pull(state: AppState) -> None:
    """Pull the configured enhancer model on a background thread with progress."""
    def worker() -> None:
        client = OllamaClient()
        state.enhancement_status = "pulling"
        state.enhancement_pull_progress = 0.0
        state.enhancement_error = None
        try:
            client.pull_model(
                state.enhancement_model,
                lambda fraction: setattr(state, "enhancement_pull_progress", fraction),
            )
            state.enhancement_status = "ready"
        except OllamaUnavailable:
            state.enhancement_status = "ollama_missing"
            state.enhancement_error = "Ollama isn't running"
        except OllamaError:
            state.enhancement_status = "error"
            state.enhancement_error = "Download failed"

    threading.Thread(target=worker, daemon=True).start()


# ---------------------------------------------------------------------------
# Show / hide
# ---------------------------------------------------------------------------
def _show_settings_panel(state: AppState) -> None:
    if not state.settings_panel_hwnd or not state.overlay_hwnd:
        return
    state.mic_devices = _get_input_devices()
    buf, pw, ph = _render_settings_panel(state)
    _show_panel_window(state, state.settings_panel_hwnd, buf, pw, ph)
    state.active_panel = "settings"
    _refresh_enhancer_status(state)


def _hide_settings_panel(state: AppState) -> None:
    if state.settings_panel_hwnd and state.active_panel == "settings":
        ctypes.windll.user32.ShowWindow(state.settings_panel_hwnd, 0)
        state.active_panel = None
        state.mic_expanded = False
