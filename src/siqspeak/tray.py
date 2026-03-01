import logging
import os

from PIL import Image, ImageFilter

from siqspeak.config import SCRIPT_DIR
from siqspeak.state import AppState

log = logging.getLogger("siqspeak")

_tray_icon_img: Image.Image | None = None


def load_tray_icon() -> Image.Image:
    global _tray_icon_img
    if _tray_icon_img is None:
        ico_path = os.path.join(SCRIPT_DIR, "dictate.ico")
        src = Image.open(ico_path).convert("RGBA")
        _tray_icon_img = (
            src.resize((128, 128), Image.LANCZOS)
               .resize((64, 64), Image.LANCZOS)
               .filter(ImageFilter.UnsharpMask(radius=1.0, percent=60, threshold=2))
        )
    return _tray_icon_img


def make_icon(_color: str = "") -> Image.Image:
    return load_tray_icon()


def set_state(state: AppState, new_state: str) -> None:
    state.overlay_target_state = new_state
