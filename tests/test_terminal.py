"""Tests for best-effort terminal working-directory detection."""
from __future__ import annotations

from pathlib import Path

import psutil

from siqspeak.enhancement import terminal


class _FakeProc:
    """Stand-in for a psutil.Process — no real process is touched."""

    def __init__(
        self,
        name: str,
        cwd: str = "",
        create_time: float = 0.0,
        children: tuple[_FakeProc, ...] = (),
    ) -> None:
        self._name = name
        self._cwd = cwd
        self._create_time = create_time
        self._children = children

    def name(self) -> str:
        return self._name

    def cwd(self) -> str:
        return self._cwd

    def create_time(self) -> float:
        return self._create_time

    def children(self, recursive: bool = False) -> list[_FakeProc]:
        return list(self._children)


def _patch(monkeypatch, pid: int | None, proc: _FakeProc | Exception) -> None:
    """Wire _pid_for_hwnd and psutil.Process to deterministic fakes."""
    monkeypatch.setattr(terminal, "_pid_for_hwnd", lambda _hwnd: pid)

    def _process(_pid: int) -> _FakeProc:
        if isinstance(proc, Exception):
            raise proc
        return proc

    monkeypatch.setattr(terminal.psutil, "Process", _process)


def test_window_process_is_shell_returns_its_cwd(monkeypatch, tmp_path: Path) -> None:
    _patch(monkeypatch, 100, _FakeProc("powershell.exe", cwd=str(tmp_path)))
    assert terminal.terminal_cwd(123) == tmp_path.resolve()


def test_terminal_host_returns_most_recent_shell_descendant(monkeypatch, tmp_path: Path) -> None:
    older = tmp_path / "older"
    newer = tmp_path / "newer"
    older.mkdir()
    newer.mkdir()
    host = _FakeProc(
        "WindowsTerminal.exe",
        children=(
            _FakeProc("pwsh.exe", cwd=str(older), create_time=1.0),
            _FakeProc("cmd.exe", cwd=str(newer), create_time=2.0),
            _FakeProc("some-tool.exe", cwd=str(tmp_path), create_time=3.0),
        ),
    )
    _patch(monkeypatch, 200, host)
    assert terminal.terminal_cwd(1) == newer.resolve()


def test_no_shell_found_returns_none(monkeypatch, tmp_path: Path) -> None:
    _patch(monkeypatch, 300, _FakeProc("explorer.exe", cwd=str(tmp_path)))
    assert terminal.terminal_cwd(1) is None


def test_terminal_host_without_shell_children_returns_none(monkeypatch) -> None:
    host = _FakeProc("conhost.exe", children=(_FakeProc("notepad.exe"),))
    _patch(monkeypatch, 400, host)
    assert terminal.terminal_cwd(1) is None


def test_access_denied_returns_none(monkeypatch) -> None:
    _patch(monkeypatch, 500, psutil.AccessDenied(500))
    assert terminal.terminal_cwd(1) is None


def test_no_such_process_returns_none(monkeypatch) -> None:
    _patch(monkeypatch, 600, psutil.NoSuchProcess(600))
    assert terminal.terminal_cwd(1) is None


def test_falsey_hwnd_returns_none() -> None:
    assert terminal.terminal_cwd(None) is None
    assert terminal.terminal_cwd(0) is None


def test_no_pid_returns_none(monkeypatch, tmp_path: Path) -> None:
    _patch(monkeypatch, None, _FakeProc("powershell.exe", cwd=str(tmp_path)))
    assert terminal.terminal_cwd(1) is None


def test_nonexistent_cwd_returns_none(monkeypatch, tmp_path: Path) -> None:
    missing = tmp_path / "gone"
    _patch(monkeypatch, 700, _FakeProc("bash", cwd=str(missing)))
    assert terminal.terminal_cwd(1) is None
