"""Best-effort local hardware probe used to gate model downloads.

Two independent signals: total physical RAM (ctypes ``GlobalMemoryStatusEx``)
and NVIDIA VRAM (``nvidia-smi``, absent on most machines). A model may run on
either, so :func:`can_run_model` compares its requirement against the larger of
the two. The two probes fail differently: a missing NVIDIA driver or a hung
``nvidia-smi`` returns ``None`` (unknown), while a failed RAM probe leaves the
struct zeroed and returns ``0.0`` — fail-closed, so the download is blocked
rather than allowed on unknown hardware.
"""
from __future__ import annotations

import ctypes
import subprocess

CREATE_NO_WINDOW = 0x08000000  # keeps nvidia-smi from flashing a console window


class _MemoryStatusEx(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def _total_phys_bytes() -> int:
    """Return total physical RAM in bytes (OS boundary; mocked in tests)."""
    status = _MemoryStatusEx()
    status.dwLength = ctypes.sizeof(_MemoryStatusEx)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
    return int(status.ullTotalPhys)


def system_ram_gb() -> float:
    """Total physical RAM in GiB."""
    return _total_phys_bytes() / 1024**3


def nvidia_vram_gb() -> float | None:
    """Total NVIDIA VRAM in GiB, or None when no NVIDIA GPU is detectable."""
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=3,
            creationflags=CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    lines = result.stdout.strip().splitlines()
    if not lines:
        return None
    try:
        mib = float(lines[0].strip())
    except ValueError:
        return None
    return mib / 1024


def can_run_model(min_gb: float) -> tuple[bool, str]:
    """Whether the machine can run a model needing ``min_gb`` of RAM or VRAM.

    Returns ``(ok, readout)`` where ``readout`` describes the detected hardware,
    e.g. ``"31.7 GB RAM, 8.0 GB GPU"`` or ``"2.0 GB RAM"``.
    """
    ram = system_ram_gb()
    vram = nvidia_vram_gb()
    ok = max(ram, vram or 0.0) >= min_gb
    readout = f"{ram:.1f} GB RAM"
    if vram is not None:
        readout += f", {vram:.1f} GB GPU"
    return ok, readout
