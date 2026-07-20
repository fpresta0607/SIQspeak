"""Native Windows shell folder picker via ctypes.

Uses ``SHBrowseForFolderW`` to obtain a filesystem directory. The returned item
id (PIDL) is always released with ``CoTaskMemFree``. The process working
directory is never changed.

The three ctypes-backed steps are module-level functions so they can be
substituted in tests, keeping the public :func:`select_folder` fully unit
testable without opening a real dialog.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes

_MAX_PATH = 260
_BIF_RETURNONLYFSDIRS = 0x0001
_BIF_NEWDIALOGSTYLE = 0x0040


class _BROWSEINFOW(ctypes.Structure):
    _fields_ = (
        ("hwndOwner", ctypes.wintypes.HWND),
        ("pidlRoot", ctypes.c_void_p),
        ("pszDisplayName", ctypes.wintypes.LPWSTR),
        ("lpszTitle", ctypes.wintypes.LPCWSTR),
        ("ulFlags", ctypes.wintypes.UINT),
        ("lpfn", ctypes.c_void_p),
        ("lParam", ctypes.wintypes.LPARAM),
        ("iImage", ctypes.c_int),
    )


def _browse_for_folder(title: str, hwnd: int) -> int:
    """Show the shell folder dialog; return the selected item id, or 0 if cancelled."""
    shell32 = ctypes.windll.shell32
    ole32 = ctypes.windll.ole32

    ole32.CoInitialize(None)
    try:
        display_name = ctypes.create_unicode_buffer(_MAX_PATH)
        info = _BROWSEINFOW()
        info.hwndOwner = hwnd
        info.pszDisplayName = ctypes.cast(display_name, ctypes.wintypes.LPWSTR)
        info.lpszTitle = title
        info.ulFlags = _BIF_RETURNONLYFSDIRS | _BIF_NEWDIALOGSTYLE

        shell32.SHBrowseForFolderW.restype = ctypes.c_void_p
        pidl = shell32.SHBrowseForFolderW(ctypes.byref(info))
        return int(pidl) if pidl else 0
    finally:
        ole32.CoUninitialize()


def _path_from_pidl(pidl: int) -> str | None:
    """Resolve an item id to a filesystem path, or None if it has none."""
    buffer = ctypes.create_unicode_buffer(_MAX_PATH)
    if ctypes.windll.shell32.SHGetPathFromIDListW(ctypes.c_void_p(pidl), buffer):
        return buffer.value or None
    return None


def _co_task_mem_free(pidl: int) -> None:
    """Release an item id allocated by the shell."""
    ctypes.windll.ole32.CoTaskMemFree(ctypes.c_void_p(pidl))


def select_folder(title: str = "Select workspace folder", hwnd: int = 0) -> str | None:
    """Open the native folder picker and return the chosen path, or None.

    Returns None when the user cancels or the selection has no filesystem path.
    The item id is always freed.
    """
    pidl = _browse_for_folder(title, hwnd)
    if not pidl:
        return None
    try:
        return _path_from_pidl(pidl)
    finally:
        _co_task_mem_free(pidl)
