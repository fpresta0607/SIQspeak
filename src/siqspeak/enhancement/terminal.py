"""Best-effort detection of a focused terminal's shell working directory.

Only reads the current working directory of a process the user is actively
dictating into (their own shell). Never raises, never blocks, never logs the
path content — psutil calls are fast and no subprocess is spawned.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes
from pathlib import Path

import psutil

# Shells whose own CWD is the workspace signal.
SHELL_NAMES = frozenset({"cmd", "powershell", "pwsh", "bash", "wsl", "nu", "fish", "zsh"})
# Terminal hosts that own a shell as a descendant process.
TERMINAL_HOST_NAMES = frozenset({"windowsterminal", "wt", "conhost", "alacritty", "wezterm"})


def _process_name(proc: psutil.Process) -> str:
    """Lower-cased executable name without a trailing ``.exe``."""
    name = proc.name().lower()
    return name[:-4] if name.endswith(".exe") else name


def _pid_for_hwnd(hwnd: int) -> int | None:
    """Resolve a window handle to its owning process id, or None."""
    pid = ctypes.wintypes.DWORD(0)
    ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value or None


def _find_shell(proc: psutil.Process) -> psutil.Process | None:
    """Return the shell process for ``proc`` — itself, or its newest shell child."""
    name = _process_name(proc)
    if name in SHELL_NAMES:
        return proc
    if name in TERMINAL_HOST_NAMES:
        shells = [c for c in proc.children(recursive=True) if _process_name(c) in SHELL_NAMES]
        if not shells:
            return None
        shells.sort(key=lambda c: c.create_time(), reverse=True)
        return shells[0]
    return None


def terminal_cwd(hwnd: int | None) -> Path | None:
    """Return the focused terminal's shell working directory, or None.

    Best-effort: identifies whether ``hwnd`` belongs to a shell (or a terminal
    host owning one) and returns that shell's resolved CWD when it exists.
    Windows Terminal multi-pane is approximated by the most-recently-created
    shell descendant. Any failure yields None — this must never raise.
    """
    if not hwnd:
        return None
    try:
        pid = _pid_for_hwnd(hwnd)
        if pid is None:
            return None
        shell = _find_shell(psutil.Process(pid))
        if shell is None:
            return None
        resolved = Path(shell.cwd()).resolve()
        return resolved if resolved.exists() else None
    except (psutil.Error, OSError, ValueError, ctypes.ArgumentError):
        return None
