"""Tests for the hardware capability probe (RAM / VRAM / can-run gate).

The OS boundaries are mocked: ``_total_phys_bytes`` stands in for the ctypes
``GlobalMemoryStatusEx`` call and ``subprocess.run`` for ``nvidia-smi``. No real
subprocess is spawned and no console window flashes.
"""
from __future__ import annotations

import subprocess

import pytest

from siqspeak.enhancement import hardware


def test_system_ram_gb_converts_bytes_to_gib(monkeypatch) -> None:
    monkeypatch.setattr(hardware, "_total_phys_bytes", lambda: 34_359_738_368)  # 32 GiB
    assert hardware.system_ram_gb() == pytest.approx(32.0, abs=0.01)


class _Result:
    def __init__(self, stdout: str) -> None:
        self.stdout = stdout


def test_nvidia_vram_gb_parses_first_line_mib(monkeypatch) -> None:
    monkeypatch.setattr(hardware.subprocess, "run", lambda *a, **k: _Result("8192\n8192\n"))
    assert hardware.nvidia_vram_gb() == pytest.approx(8.0, abs=0.01)


def test_nvidia_vram_gb_absent_returns_none(monkeypatch) -> None:
    def _missing(*a, **k):
        raise FileNotFoundError("nvidia-smi not installed")

    monkeypatch.setattr(hardware.subprocess, "run", _missing)
    assert hardware.nvidia_vram_gb() is None


def test_nvidia_vram_gb_timeout_returns_none(monkeypatch) -> None:
    def _timeout(*a, **k):
        raise subprocess.TimeoutExpired(cmd="nvidia-smi", timeout=3)

    monkeypatch.setattr(hardware.subprocess, "run", _timeout)
    assert hardware.nvidia_vram_gb() is None


def test_nvidia_vram_gb_malformed_returns_none(monkeypatch) -> None:
    monkeypatch.setattr(hardware.subprocess, "run", lambda *a, **k: _Result("N/A\n"))
    assert hardware.nvidia_vram_gb() is None


def test_can_run_model_true_when_hardware_sufficient(monkeypatch) -> None:
    monkeypatch.setattr(hardware, "system_ram_gb", lambda: 31.7)
    monkeypatch.setattr(hardware, "nvidia_vram_gb", lambda: 8.0)

    ok, message = hardware.can_run_model(4.0)

    assert ok is True
    assert "31.7 GB RAM" in message
    assert "8.0 GB GPU" in message


def test_can_run_model_uses_gpu_when_ram_insufficient(monkeypatch) -> None:
    monkeypatch.setattr(hardware, "system_ram_gb", lambda: 2.0)
    monkeypatch.setattr(hardware, "nvidia_vram_gb", lambda: 8.0)

    ok, _message = hardware.can_run_model(4.0)

    assert ok is True


def test_can_run_model_false_when_under_spec(monkeypatch) -> None:
    monkeypatch.setattr(hardware, "system_ram_gb", lambda: 2.0)
    monkeypatch.setattr(hardware, "nvidia_vram_gb", lambda: None)

    ok, message = hardware.can_run_model(4.0)

    assert ok is False
    assert message == "2.0 GB RAM"
