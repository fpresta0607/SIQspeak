import contextlib
import ctypes


def enable_dpi_awareness() -> None:
    with contextlib.suppress(Exception):
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
