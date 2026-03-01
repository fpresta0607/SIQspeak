from __future__ import annotations

import queue
import threading
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AppState:
    """All mutable application state. One instance, passed by reference."""

    # Recording
    is_recording: bool = False
    audio_chunks: list = field(default_factory=list)
    mic_stream: Any = None  # sd.InputStream
    target_hwnd: int | None = None
    current_level: float = 0.0
    display_level: float = 0.0

    # Model
    model: Any = None  # WhisperModel
    loaded_model_name: str = "tiny"
    model_loading: bool = False
    model_loading_name: str = ""
    download_progress: float = 0.0
    download_confirm_name: str | None = None
    download_error: str | None = None
    download_error_time: float = 0.0
    device: str = "cpu"
    compute_type: str = "int8"
    has_cuda: bool = False

    # Microphone
    mic_device: int | None = None
    mic_devices: list[dict] = field(default_factory=list)
    mic_expanded: bool = False

    # Overlay
    overlay_hwnd: int | None = None
    overlay_target_state: str = "idle"
    pill_current_mode: str = "idle"
    hover_zone: int | None = None

    # Drag
    drag_active: bool = False
    drag_pending: bool = False
    drag_start_x: int = 0
    drag_start_y: int = 0
    drag_pill_x: int = 0
    drag_pill_y: int = 0
    pill_user_x: int | None = None
    pill_user_y: int | None = None

    # Panels
    log_panel_hwnd: int | None = None
    model_panel_hwnd: int | None = None
    settings_panel_hwnd: int | None = None
    active_panel: str | None = None  # "info" | "model" | "settings" | None
    transcription_log: list[dict] = field(default_factory=list)
    copy_debounce: bool = False
    copy_hover_row: int | None = None
    copied_row: int | None = None
    copied_time: float = 0.0
    log_entry_heights: list[int] = field(default_factory=list)
    log_scroll_offset: int = 0
    wheel_delta: int = 0
    log_append_count: int = 0

    # Welcome
    welcome_hwnd: int | None = None
    welcome_shown: bool = False
    welcome_show_time: float = 0.0

    # Hotkey / control
    should_quit: bool = False
    hotkey_busy: bool = False

    # Debounce
    idle_click_debounce: bool = False
    model_click_debounce: bool = False
    settings_click_debounce: bool = False

    # Streaming
    stream_mode: bool = False
    stream_queue: queue.Queue | None = None
    stream_worker: threading.Thread | None = None
    silence_count: int = 0
    transcribed_idx: int = 0
    stream_focus_done: bool = False
    stream_texts: list[str] = field(default_factory=list)
    prev_chunk_tail: list[str] = field(default_factory=list)

    # Tray
    icon: Any = None  # pystray.Icon

    # Mouse hook
    mouse_hook: int | None = None
