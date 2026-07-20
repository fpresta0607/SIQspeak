"""Tests for trusted workspace-root resolution."""
from __future__ import annotations

from pathlib import Path

from siqspeak.enhancement import workspace as workspace_mod
from siqspeak.enhancement.workspace import find_repository_root, resolve_workspace


def test_manual_workspace_override_wins(tmp_path: Path) -> None:
    manual = tmp_path / "manual"
    manual.mkdir()
    assert resolve_workspace(str(manual), r"C:\other - Visual Studio Code") == manual.resolve()


def test_detected_path_ascends_to_git_root(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    nested = root / "src" / "feature"
    nested.mkdir(parents=True)
    (root / ".git").mkdir()
    assert find_repository_root(nested) == root.resolve()


def test_ambiguous_title_does_not_guess() -> None:
    assert resolve_workspace(None, "main.py - project - Visual Studio Code") is None


def test_manual_override_ignored_when_not_a_directory(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"
    assert resolve_workspace(str(missing), "no path in this title") is None


def test_manual_override_ignored_when_pointing_at_file(tmp_path: Path) -> None:
    file_path = tmp_path / "note.txt"
    file_path.write_text("hi", encoding="utf-8")
    assert resolve_workspace(str(file_path), "no path in this title") is None


def test_find_repository_root_on_file_uses_parent(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    file_path = root / "main.py"
    file_path.write_text("print('hi')", encoding="utf-8")
    assert find_repository_root(file_path) == root.resolve()


def test_find_repository_root_returns_none_without_git(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    assert find_repository_root(plain) is None


def test_detected_path_in_title_resolves_to_git_root(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    nested = root / "src"
    nested.mkdir(parents=True)
    (root / ".git").mkdir()
    title = f"main.py - {nested}"
    assert resolve_workspace(None, title) == root.resolve()


def test_detected_nonexistent_path_returns_none() -> None:
    title = r"main.py - C:\nope\does\not\exist - Visual Studio Code"
    assert resolve_workspace(None, title) is None


def test_detected_existing_path_without_git_returns_none(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    title = f"file - {plain}"
    assert resolve_workspace(None, title) is None


def test_empty_manual_override_falls_through_to_title(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".git").mkdir()
    title = f"README.md - {root}"
    assert resolve_workspace(None, title) == root.resolve()
    assert resolve_workspace("", title) == root.resolve()


def _make_repo(base: Path, *, nested: str = "src") -> tuple[Path, Path]:
    """Create a git repo under ``base`` and return (root, nested-dir)."""
    root = base / "repo"
    inner = root / nested
    inner.mkdir(parents=True)
    (root / ".git").mkdir()
    return root, inner


def test_manual_override_beats_terminal_cwd(monkeypatch, tmp_path: Path) -> None:
    terminal_root, _ = _make_repo(tmp_path / "terminal")
    monkeypatch.setattr(workspace_mod, "terminal_cwd", lambda _hwnd: terminal_root)
    manual = tmp_path / "manual"
    manual.mkdir()
    assert resolve_workspace(str(manual), "no path", window_hwnd=123) == manual.resolve()


def test_terminal_cwd_beats_title(monkeypatch, tmp_path: Path) -> None:
    terminal_root, terminal_nested = _make_repo(tmp_path / "terminal")
    title_root, _ = _make_repo(tmp_path / "titled")
    monkeypatch.setattr(workspace_mod, "terminal_cwd", lambda _hwnd: terminal_nested)
    title = f"main.py - {title_root}"
    assert resolve_workspace(None, title, window_hwnd=123) == terminal_root.resolve()


def test_terminal_cwd_ascends_to_git_root(monkeypatch, tmp_path: Path) -> None:
    terminal_root, terminal_nested = _make_repo(tmp_path, nested="src/feature")
    monkeypatch.setattr(workspace_mod, "terminal_cwd", lambda _hwnd: terminal_nested)
    assert resolve_workspace(None, "no path", window_hwnd=123) == terminal_root.resolve()


def test_title_parsing_used_when_terminal_yields_nothing(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(workspace_mod, "terminal_cwd", lambda _hwnd: None)
    title_root, title_nested = _make_repo(tmp_path)
    title = f"main.py - {title_nested}"
    assert resolve_workspace(None, title, window_hwnd=123) == title_root.resolve()


def test_terminal_cwd_without_git_falls_through_to_title(monkeypatch, tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    monkeypatch.setattr(workspace_mod, "terminal_cwd", lambda _hwnd: plain)
    title_root, title_nested = _make_repo(tmp_path)
    title = f"main.py - {title_nested}"
    assert resolve_workspace(None, title, window_hwnd=123) == title_root.resolve()
