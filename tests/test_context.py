"""Tests for bounded instruction-file context loading."""
from __future__ import annotations

import os
from pathlib import Path

from siqspeak.enhancement.context import (
    MAX_CONTEXT_BYTES,
    ContextSource,
    load_instruction_context,
    load_workspace_context,
)


def _labels(sources: tuple[ContextSource, ...]) -> list[str]:
    return [source.label for source in sources]


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


def _write_plan(workspace: Path, name: str, text: str, mtime: float) -> None:
    plans_dir = workspace / "docs" / "plans"
    plans_dir.mkdir(parents=True, exist_ok=True)
    plan = plans_dir / name
    plan.write_text(text, encoding="utf-8")
    os.utime(plan, (mtime, mtime))


def test_workspace_context_instruction_files_first_then_plans(tmp_path: Path) -> None:
    (tmp_path / "CLAUDE.md").write_text("claude", encoding="utf-8")
    _write_plan(tmp_path, "a.md", "plan a", mtime=1000)
    _write_plan(tmp_path, "b.md", "plan b", mtime=2000)

    sources = load_workspace_context(workspace=tmp_path, home=None)

    assert _labels(sources) == ["CLAUDE.md", "docs/plans/b.md", "docs/plans/a.md"]
    assert sources[0].text == "claude"


def test_workspace_context_limits_to_three_newest_plans(tmp_path: Path) -> None:
    _write_plan(tmp_path, "oldest.md", "oldest", mtime=1000)
    _write_plan(tmp_path, "old.md", "old", mtime=2000)
    _write_plan(tmp_path, "newer.md", "newer", mtime=3000)
    _write_plan(tmp_path, "newest.md", "newest", mtime=4000)

    sources = load_workspace_context(workspace=tmp_path, home=None)

    assert _labels(sources) == [
        "docs/plans/newest.md",
        "docs/plans/newer.md",
        "docs/plans/old.md",
    ]


def test_workspace_context_orders_ties_by_name(tmp_path: Path) -> None:
    _write_plan(tmp_path, "zebra.md", "z", mtime=5000)
    _write_plan(tmp_path, "alpha.md", "a", mtime=5000)

    sources = load_workspace_context(workspace=tmp_path, home=None)

    assert _labels(sources) == ["docs/plans/alpha.md", "docs/plans/zebra.md"]


def test_workspace_context_none_workspace_returns_only_global(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write_global(home, "global only")

    sources = load_workspace_context(workspace=None, home=home)

    assert _labels(sources) == ["~/.claude/CLAUDE.md"]


def test_workspace_context_no_plans_returns_only_instructions(tmp_path: Path) -> None:
    (tmp_path / "CLAUDE.md").write_text("claude", encoding="utf-8")

    sources = load_workspace_context(workspace=tmp_path, home=None)

    assert _labels(sources) == ["CLAUDE.md"]


def test_workspace_context_plans_are_byte_capped(tmp_path: Path) -> None:
    _write_plan(tmp_path, "big.md", "a" * (MAX_CONTEXT_BYTES * 2), mtime=1000)

    sources = load_workspace_context(workspace=tmp_path, home=None)

    assert len(sources) == 1
    assert len(sources[0].text) == MAX_CONTEXT_BYTES
