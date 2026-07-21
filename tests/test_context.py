"""Tests for bounded instruction-file context loading."""
from __future__ import annotations

from pathlib import Path

import pytest

from siqspeak.enhancement.context import (
    MAX_CHARS_PER_FILE,
    MAX_CONTEXT_BYTES,
    MAX_FILES,
    MAX_FINDINGS,
    MAX_TOTAL_CHARS,
    ContextFinding,
    ContextSource,
    _is_within,
    extract_context,
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


# --- extract_context: rich extraction with provenance, ranking, bounds ---


def _paths(findings: tuple[ContextFinding, ...]) -> list[str]:
    return [finding.source_path for finding in findings]


def test_extract_discovers_each_file_type_with_category(tmp_path: Path) -> None:
    (tmp_path / "CLAUDE.md").write_text("claude rules", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("agents rules", encoding="utf-8")
    (tmp_path / "CODEX.md").write_text("codex rules", encoding="utf-8")
    (tmp_path / "ARCHITECTURE.md").write_text("architecture overview", encoding="utf-8")
    (tmp_path / "README.md").write_text("readme overview", encoding="utf-8")
    (tmp_path / "CONTRIBUTING.md").write_text("contributing guide", encoding="utf-8")
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "design.md").write_text("design doc", encoding="utf-8")

    findings = extract_context("overview", workspace=tmp_path, home=None)
    by_path = {f.source_path: (f.category, f.confidence) for f in findings}

    assert by_path["CLAUDE.md"] == ("agent_instruction", "high")
    assert by_path["AGENTS.md"] == ("agent_instruction", "high")
    assert by_path["CODEX.md"] == ("agent_instruction", "high")
    assert by_path["ARCHITECTURE.md"] == ("architecture", "high")
    assert by_path["README.md"] == ("architecture", "medium")
    assert by_path["CONTRIBUTING.md"] == ("constraint", "medium")
    assert by_path["docs/design.md"] == ("architecture", "medium")


def test_extract_includes_global_instruction(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    home = tmp_path / "home"
    _write_global(home, "global rules")

    findings = extract_context("anything at all", workspace=workspace, home=home)
    by_path = {f.source_path: f for f in findings}

    assert "~/.claude/CLAUDE.md" in by_path
    assert by_path["~/.claude/CLAUDE.md"].category == "agent_instruction"
    assert by_path["~/.claude/CLAUDE.md"].confidence == "high"


def test_extract_ranks_relevant_doc_above_unrelated(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    # Named so path-order tiebreak alone would put the UNRELATED doc first;
    # only token-overlap scoring can flip the relevant doc ahead.
    (docs / "zzz_relevant.md").write_text(
        "authentication login session token flow", encoding="utf-8"
    )
    (docs / "aaa_unrelated.md").write_text("banana pancake syrup weather", encoding="utf-8")

    findings = extract_context("add authentication login flow", workspace=tmp_path, home=None)
    paths = _paths(findings)

    assert paths.index("docs/zzz_relevant.md") < paths.index("docs/aaa_unrelated.md")


def test_extract_includes_agent_instruction_with_zero_overlap(tmp_path: Path) -> None:
    (tmp_path / "CLAUDE.md").write_text("xyzzy plugh frobnicate", encoding="utf-8")

    findings = extract_context("completely different words entirely", workspace=tmp_path, home=None)

    assert any(
        f.source_path == "CLAUDE.md" and f.category == "agent_instruction" for f in findings
    )


def test_extract_collapses_near_duplicate_text(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("Shared architecture overview text", encoding="utf-8")
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "copy.md").write_text("shared   architecture overview   TEXT", encoding="utf-8")

    findings = extract_context("architecture", workspace=tmp_path, home=None)
    paths = _paths(findings)

    # README is discovered first, so it survives and the near-duplicate collapses.
    assert ("README.md" in paths) != ("docs/copy.md" in paths)
    assert "README.md" in paths


def test_extract_caps_per_file_chars(tmp_path: Path) -> None:
    (tmp_path / "CLAUDE.md").write_text("a" * (MAX_CHARS_PER_FILE * 3), encoding="utf-8")

    findings = extract_context("a", workspace=tmp_path, home=None)
    claude = next(f for f in findings if f.source_path == "CLAUDE.md")

    assert len(claude.text) <= MAX_CHARS_PER_FILE


def test_extract_enforces_total_char_cap(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    for index in range(6):
        (docs / f"doc{index}.md").write_text("a" * MAX_CHARS_PER_FILE, encoding="utf-8")

    findings = extract_context("unrelated", workspace=tmp_path, home=None)
    total = sum(len(f.text) for f in findings)

    assert total <= MAX_TOTAL_CHARS


def test_extract_enforces_max_findings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("siqspeak.enhancement.context.MAX_FILES", 1000)
    monkeypatch.setattr("siqspeak.enhancement.context.MAX_DOC_FILES", 1000)
    monkeypatch.setattr("siqspeak.enhancement.context.MAX_TOTAL_CHARS", 10**9)
    docs = tmp_path / "docs"
    docs.mkdir()
    for index in range(MAX_FINDINGS + 5):
        (docs / f"doc{index:02d}.md").write_text(f"content number {index}", encoding="utf-8")

    findings = extract_context("content", workspace=tmp_path, home=None)

    assert len(findings) == MAX_FINDINGS


def test_extract_enforces_max_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("siqspeak.enhancement.context.MAX_FINDINGS", 1000)
    monkeypatch.setattr("siqspeak.enhancement.context.MAX_DOC_FILES", 1000)
    monkeypatch.setattr("siqspeak.enhancement.context.MAX_TOTAL_CHARS", 10**9)
    docs = tmp_path / "docs"
    docs.mkdir()
    for index in range(MAX_FILES + 8):
        (docs / f"doc{index:03d}.md").write_text(f"content number {index}", encoding="utf-8")

    findings = extract_context("content", workspace=tmp_path, home=None)

    assert len(findings) == MAX_FILES


def test_extract_missing_optional_docs_degrades(tmp_path: Path) -> None:
    (tmp_path / "CLAUDE.md").write_text("only instruction", encoding="utf-8")

    findings = extract_context("anything", workspace=tmp_path, home=None)

    assert _paths(findings) == ["CLAUDE.md"]


def test_extract_no_sources_returns_empty(tmp_path: Path) -> None:
    assert extract_context("x", workspace=tmp_path, home=None) == ()
    assert extract_context("x", workspace=None, home=None) == ()


def test_extract_mcp_reports_server_names_only(tmp_path: Path) -> None:
    (tmp_path / ".mcp.json").write_text(
        '{"mcpServers": {"supabase": {"url": "http://secret.example", "token": "abc123"},'
        ' "playwright": {}}}',
        encoding="utf-8",
    )

    findings = extract_context("supabase", workspace=tmp_path, home=None)
    mcp = next(f for f in findings if f.source_path == ".mcp.json")

    assert mcp.category == "tooling"
    assert mcp.confidence == "medium"
    assert "supabase" in mcp.text
    assert "playwright" in mcp.text
    assert "secret" not in mcp.text
    assert "abc123" not in mcp.text


def test_extract_malformed_mcp_skipped(tmp_path: Path) -> None:
    (tmp_path / ".mcp.json").write_text("{not valid json", encoding="utf-8")
    (tmp_path / "CLAUDE.md").write_text("rules", encoding="utf-8")

    findings = extract_context("x", workspace=tmp_path, home=None)
    paths = _paths(findings)

    assert ".mcp.json" not in paths
    assert "CLAUDE.md" in paths


def test_extract_skips_symlinked_doc(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    secret = tmp_path / "secret.md"
    secret.write_text("out of root secret payload", encoding="utf-8")
    _symlink_or_skip(docs / "link.md", secret)

    findings = extract_context("secret", workspace=tmp_path, home=None)

    assert "docs/link.md" not in _paths(findings)
    assert all("secret payload" not in f.text for f in findings)
