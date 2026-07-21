"""Tests for bounded instruction-file context loading."""
from __future__ import annotations

from pathlib import Path

import pytest

from siqspeak.enhancement.context import (
    MAX_CONTEXT_BYTES,
    ContextSource,
    _is_within,
    load_instruction_context,
    load_workspace_context,
)


def _labels(sources: tuple[ContextSource, ...]) -> list[str]:
    return [source.label for source in sources]


def _symlink_or_skip(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not permitted in this environment")


def _write_global(home: Path, text: str) -> None:
    global_dir = home / ".claude"
    global_dir.mkdir(parents=True, exist_ok=True)
    (global_dir / "CLAUDE.md").write_text(text, encoding="utf-8")


def test_workspace_files_discovered_in_priority_order(tmp_path: Path) -> None:
    (tmp_path / "CLAUDE.md").write_text("claude", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("agents", encoding="utf-8")
    (tmp_path / "CODEX.md").write_text("codex", encoding="utf-8")

    sources = load_instruction_context(workspace=tmp_path, home=None)

    assert _labels(sources) == ["CLAUDE.md", "AGENTS.md", "CODEX.md"]
    assert [source.text for source in sources] == ["claude", "agents", "codex"]


def test_global_file_included_after_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    home = tmp_path / "home"
    (workspace / "CLAUDE.md").write_text("ws", encoding="utf-8")
    _write_global(home, "global")

    sources = load_instruction_context(workspace=workspace, home=home)

    assert _labels(sources) == ["CLAUDE.md", "~/.claude/CLAUDE.md"]
    assert sources[-1].text == "global"


def test_missing_files_are_skipped(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("only agents", encoding="utf-8")

    sources = load_instruction_context(workspace=tmp_path, home=None)

    assert _labels(sources) == ["AGENTS.md"]


def test_workspace_none_returns_only_global(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write_global(home, "global only")

    sources = load_instruction_context(workspace=None, home=home)

    assert _labels(sources) == ["~/.claude/CLAUDE.md"]
    assert sources[0].text == "global only"


def test_workspace_none_and_no_global_returns_empty(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()

    sources = load_instruction_context(workspace=None, home=home)

    assert sources == ()


def test_byte_cap_truncates_large_file(tmp_path: Path) -> None:
    (tmp_path / "CLAUDE.md").write_text("a" * (MAX_CONTEXT_BYTES * 2), encoding="utf-8")

    sources = load_instruction_context(workspace=tmp_path, home=None)

    assert len(sources) == 1
    assert len(sources[0].text) <= MAX_CONTEXT_BYTES
    assert len(sources[0].text) == MAX_CONTEXT_BYTES


def test_nul_bytes_are_stripped(tmp_path: Path) -> None:
    (tmp_path / "CLAUDE.md").write_bytes(b"clean\x00text\x00here")

    sources = load_instruction_context(workspace=tmp_path, home=None)

    assert sources[0].text == "cleantexthere"


def test_newlines_and_markdown_preserved(tmp_path: Path) -> None:
    content = "# Heading\n\n- item one\n- item two\n"
    (tmp_path / "CLAUDE.md").write_bytes(content.encode("utf-8"))

    sources = load_instruction_context(workspace=tmp_path, home=None)

    assert sources[0].text == content


def test_empty_result_when_nothing_exists(tmp_path: Path) -> None:
    sources = load_instruction_context(workspace=tmp_path, home=None)

    assert sources == ()


def test_workspace_context_returns_instruction_files_only(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    home = tmp_path / "home"
    (workspace / "CLAUDE.md").write_text("claude", encoding="utf-8")
    _write_global(home, "global")

    sources = load_workspace_context(workspace=workspace, home=home)

    assert _labels(sources) == ["CLAUDE.md", "~/.claude/CLAUDE.md"]
    assert sources[0].text == "claude"


def test_workspace_context_excludes_plan_docs(tmp_path: Path) -> None:
    (tmp_path / "CLAUDE.md").write_text("claude", encoding="utf-8")
    plans_dir = tmp_path / "docs" / "plans"
    plans_dir.mkdir(parents=True)
    (plans_dir / "big-plan.md").write_text("a" * (MAX_CONTEXT_BYTES * 2), encoding="utf-8")

    sources = load_workspace_context(workspace=tmp_path, home=None)

    # Only the instruction file — plan-doc bloat is no longer injected.
    assert _labels(sources) == ["CLAUDE.md"]


def test_workspace_context_none_workspace_returns_only_global(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write_global(home, "global only")

    sources = load_workspace_context(workspace=None, home=home)

    assert _labels(sources) == ["~/.claude/CLAUDE.md"]


def test_is_within_rejects_out_of_root_paths(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    assert _is_within(workspace / "CLAUDE.md", workspace) is True
    # A path resolving outside the workspace root is rejected (containment).
    assert _is_within(tmp_path / "outside.md", workspace) is False
    # Global files (root=None) skip containment but must be non-symlinks.
    assert _is_within(tmp_path / "any.md", None) is True


def test_symlinked_instruction_file_is_skipped(tmp_path: Path) -> None:
    # A symlinked CLAUDE.md pointing outside the workspace must not be read —
    # a malicious repo could otherwise redirect it to arbitrary files.
    workspace = tmp_path / "ws"
    workspace.mkdir()
    secret = tmp_path / "secret.md"
    secret.write_text("out of root", encoding="utf-8")
    _symlink_or_skip(workspace / "CLAUDE.md", secret)

    sources = load_instruction_context(workspace=workspace, home=None)

    assert sources == ()
