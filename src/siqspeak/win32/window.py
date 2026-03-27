from __future__ import annotations

import ctypes
import ctypes.wintypes

import numpy as np

from siqspeak.config import ACTIVE_H, ACTIVE_W, IDLE_H, IDLE_W
from siqspeak.state import AppState
from siqspeak.win32.structs import BITMAPINFOHEADER, BLENDFUNCTION, SIZEL


def _update_layered_window(hwnd: int, buf: np.ndarray, w: int, h: int) -> None:
    """Blit BGRA buffer to a layered window via UpdateLayeredWindow."""
    if not hwnd:
        return
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32

    hdc_screen = user32.GetDC(0)
    hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)

    bmi = BITMAPINFOHEADER()
    bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.biWidth = w
    bmi.biHeight = -h  # top-down
    bmi.biPlanes = 1
    bmi.biBitCount = 32

    bits = ctypes.c_void_p()
    hbm = gdi32.CreateDIBSection(
        hdc_mem, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0,
    )
    old_bm = gdi32.SelectObject(hdc_mem, hbm)
    ctypes.memmove(bits, buf.ctypes.data, buf.nbytes)

    pt_src = ctypes.wintypes.POINT(0, 0)
    size = SIZEL(w, h)
    blend = BLENDFUNCTION(0, 0, 255, 1)

    user32.UpdateLayeredWindow(
        hwnd, hdc_screen, None, ctypes.byref(size),
        hdc_mem, ctypes.byref(pt_src), 0, ctypes.byref(blend), 2,
    )

    gdi32.SelectObject(hdc_mem, old_bm)
    gdi32.DeleteObject(hbm)
    gdi32.DeleteDC(hdc_mem)
    user32.ReleaseDC(0, hdc_screen)


def _create_idle_overlay(state: AppState) -> int:
    """Create the idle pill window — clickable, NO WS_EX_TRANSPARENT."""
    user32 = ctypes.windll.user32
    WS_EX = (
        0x00080000  # WS_EX_LAYERED
        | 0x00000008  # WS_EX_TOPMOST
        | 0x08000000  # WS_EX_NOACTIVATE
        | 0x00000080  # WS_EX_TOOLWINDOW
    )
    if state.pill_user_x is not None and state.pill_user_y is not None:
        x = state.pill_user_x
        y = state.pill_user_y
    else:
        sw = user32.GetSystemMetrics(0)
        sh = user32.GetSystemMetrics(1)
        x = (sw - IDLE_W) // 2
        y = sh - IDLE_H - 80
    return user32.CreateWindowExW(
        WS_EX, "STATIC", "", 0x80000000,  # WS_POPUP
        x, y, IDLE_W, IDLE_H,
        None, None, None, None,
    )


def _create_active_overlay(state: AppState) -> int:
    """Create the active pill window — click-through, WITH WS_EX_TRANSPARENT baked in."""
    user32 = ctypes.windll.user32
    WS_EX = (
        0x00080000  # WS_EX_LAYERED
        | 0x00000008  # WS_EX_TOPMOST
        | 0x08000000  # WS_EX_NOACTIVATE
        | 0x00000080  # WS_EX_TOOLWINDOW
        | 0x00000020  # WS_EX_TRANSPARENT — click-through, immutable
    )
    if state.pill_user_x is not None and state.pill_user_y is not None:
        x = state.pill_user_x
        y = state.pill_user_y
    else:
        sw = user32.GetSystemMetrics(0)
        sh = user32.GetSystemMetrics(1)
        x = (sw - ACTIVE_W) // 2
        y = sh - ACTIVE_H - 80
    return user32.CreateWindowExW(
        WS_EX, "STATIC", "", 0x80000000,  # WS_POPUP
        x, y, ACTIVE_W, ACTIVE_H,
        None, None, None, None,
    )


def _create_panel_window() -> int:
    """Create a generic layered panel window (NOT click-through)."""
    user32 = ctypes.windll.user32
    WS_EX = (
        0x00080000  # WS_EX_LAYERED
        | 0x00000008  # WS_EX_TOPMOST
        | 0x08000000  # WS_EX_NOACTIVATE
        | 0x00000080  # WS_EX_TOOLWINDOW
    )
    return user32.CreateWindowExW(
        WS_EX, "STATIC", "", 0x80000000,
        0, 0, 10, 10,
        None, None, None, None,
    )
