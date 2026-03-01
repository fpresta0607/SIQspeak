"""Tests for overlay rendering utilities."""
from __future__ import annotations

import numpy as np

from siqspeak.config import ACTIVE_H, ACTIVE_W, IDLE_H, IDLE_W
from siqspeak.overlay.rendering import (
    _make_pill_bg,
    _make_pill_mask,
    _rgba_to_premul_bgra,
)


def test_pill_mask_shape():
    mask = _make_pill_mask(IDLE_W, IDLE_H)
    assert mask.shape == (IDLE_H, IDLE_W)


def test_pill_mask_dtype():
    mask = _make_pill_mask(IDLE_W, IDLE_H)
    assert mask.dtype == np.float64 or mask.dtype == np.float32


def test_pill_mask_range():
    mask = _make_pill_mask(IDLE_W, IDLE_H)
    assert mask.min() >= 0.0
    assert mask.max() <= 1.0


def test_pill_bg_shape():
    mask = _make_pill_mask(ACTIVE_W, ACTIVE_H)
    bg = _make_pill_bg(ACTIVE_W, ACTIVE_H, mask)
    assert bg.shape == (ACTIVE_H, ACTIVE_W, 4)


def test_pill_bg_premultiplied_alpha():
    mask = _make_pill_mask(ACTIVE_W, ACTIVE_H)
    bg = _make_pill_bg(ACTIVE_W, ACTIVE_H, mask)
    # Premultiplied alpha: RGB channels should never exceed alpha channel
    for row in bg:
        for pixel in row:
            r, g, b, a = pixel
            assert r <= a + 1  # +1 for rounding tolerance
            assert g <= a + 1
            assert b <= a + 1


def test_rgba_to_premul_bgra_channel_swap():
    rgba = np.zeros((2, 2, 4), dtype=np.uint8)
    rgba[0, 0] = [255, 0, 0, 255]  # red
    rgba[0, 1] = [0, 255, 0, 255]  # green
    bgra = _rgba_to_premul_bgra(rgba)
    # Red pixel: RGBA(255,0,0,255) -> BGRA(0,0,255,255)
    assert bgra[0, 0, 0] == 0    # B
    assert bgra[0, 0, 1] == 0    # G
    assert bgra[0, 0, 2] == 255  # R
    assert bgra[0, 0, 3] == 255  # A
    # Green pixel: RGBA(0,255,0,255) -> BGRA(0,255,0,255)
    assert bgra[0, 1, 0] == 0    # B
    assert bgra[0, 1, 1] == 255  # G
    assert bgra[0, 1, 2] == 0    # R
