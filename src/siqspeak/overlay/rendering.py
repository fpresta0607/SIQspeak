from __future__ import annotations

import math

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from siqspeak.config import (
    _ICON_GEAR_B64,
    _ICON_HEXAGON_B64,
    _ICON_INFO_B64,
    ACTIVE_H,
    ACTIVE_W,
    CYAN,
    DOT_R,
    DOT_SPACING,
    DOT_START_X,
    DOT_Y,
    GRAY,
    IDLE_H,
    IDLE_ICON_ZONE_W,
    IDLE_W,
    NUM_DOTS,
    PILL_BG,
    PILL_BG_ALPHA,
    WHITE,
    _load_icon,
)
from siqspeak.state import AppState

# ---------------------------------------------------------------------------
# Pill shape helpers (pure functions)
# ---------------------------------------------------------------------------

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

# Pre-compute idle pill mask + background
_idle_mask = _make_pill_mask(IDLE_W, IDLE_H)
_idle_bg = _make_pill_bg(IDLE_W, IDLE_H, _idle_mask)


# ---------------------------------------------------------------------------
# Frame builders
# ---------------------------------------------------------------------------

DOT_COLOR = {"recording": CYAN, "transcribing": WHITE}


def _build_idle_frame(hover_zone: int | None = None) -> np.ndarray:
    """Pre-render idle toolbar: 3-icon pill (info | model | settings).
    hover_zone: 0 (info), 1 (model), 2 (settings), or None for no hover.
    """
    buf = _idle_bg.copy()
    img = Image.new("RGBA", (IDLE_W, IDLE_H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Zone centers: 3 zones of IDLE_ICON_ZONE_W each
    zone_w = IDLE_ICON_ZONE_W
    zone_centers = [zone_w // 2, IDLE_W // 2, IDLE_W - zone_w // 2]

    # Zone boundaries for hover highlight
    zone_lefts = [0, zone_w, IDLE_W - zone_w]
    zone_rights = [zone_w, IDLE_W - zone_w, IDLE_W]

    # Draw hover highlight behind the hovered zone
    if hover_zone is not None and 0 <= hover_zone <= 2:
        zl = zone_lefts[hover_zone] + 2
        zr = zone_rights[hover_zone] - 2
        draw.rounded_rectangle(
            [zl, 3, zr, IDLE_H - 3],
            radius=8,
            fill=(255, 255, 255, 25),
        )

    # Separator lines between zones
    for sep_x in [zone_w, IDLE_W - zone_w]:
        draw.line([(sep_x, 10), (sep_x, IDLE_H - 10)], fill=(*GRAY, 60))

    # Icon colors: brighten on hover
    default_colors = [CYAN, WHITE, GRAY]
    hover_colors = [(100, 240, 255), (255, 255, 255), (200, 200, 210)]
    colors = [
        hover_colors[i] if hover_zone == i else default_colors[i]
        for i in range(3)
    ]

    # Load and paste Lucide icons (26x26, centered in each zone)
    icon_size = (26, 26)
    icon_imgs = [
        _load_icon(_ICON_INFO_B64, icon_size, colors[0]),
        _load_icon(_ICON_HEXAGON_B64, icon_size, colors[1]),
        _load_icon(_ICON_GEAR_B64, icon_size, colors[2]),
    ]

    for icon_img, cx in zip(icon_imgs, zone_centers, strict=True):
        ix = cx - icon_img.width // 2
        iy = IDLE_H // 2 - icon_img.height // 2
        img.paste(icon_img, (ix, iy), icon_img)

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


def _render_frame(state: AppState, current_state: str, phase: float) -> np.ndarray:
    """Render one frame of the active pill (recording/transcribing dots)."""
    buf = _active_bg.copy()

    # Smooth audio level for display
    state.display_level += 0.3 * (state.current_level - state.display_level)
    level = state.display_level

    color = DOT_COLOR.get(current_state, CYAN)

    for i in range(NUM_DOTS):
        cx = DOT_START_X + i * DOT_SPACING
        cy = DOT_Y

        if current_state == "recording":
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


def _rgba_to_premul_bgra(img: Image.Image) -> np.ndarray:
    """Convert RGBA PIL image to pre-multiplied BGRA numpy buffer."""
    pixels = np.array(img, dtype=np.float32) / 255.0
    bgra = np.zeros_like(pixels)
    bgra[:, :, 0] = pixels[:, :, 2] * pixels[:, :, 3]  # B
    bgra[:, :, 1] = pixels[:, :, 1] * pixels[:, :, 3]  # G
    bgra[:, :, 2] = pixels[:, :, 0] * pixels[:, :, 3]  # R
    bgra[:, :, 3] = pixels[:, :, 3]
    return (bgra * 255).clip(0, 255).astype(np.uint8)
