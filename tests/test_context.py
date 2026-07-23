"""Tests for Code-mode context assembly: instruction floor + grep snippets."""
from __future__ import annotations

from pathlib import Path

import pytest

from siqspeak.enhancement.context import (
    MAX_CHARS_PER_FILE,
    MAX_FINDINGS,
    MAX_INSTRUCTION_CHARS_PER_FILE,
    MAX_TOTAL_CHARS,
    ContextFinding,
    _is_within,
    extract_context,
)


def _symlink_or_skip(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not permitted in this environment")


def _write_global(home: Path, text: str) -> None:
    global_dir = home / ".claude"
    global_dir.mkdir(parents=True, exist_ok=True)
    (global_dir / "CLAUDE.md").write_text(text, encoding="utf-8")


def _paths(findings: tuple[ContextFinding, ...]) -> list[str]:
    return [finding.source_path for finding in findings]


# --- containment / symlink guards (unchanged) ---


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

    findings = extract_context("anything", workspace=workspace, home=None)

    assert findings == ()


# --- instruction floor: always present ---


def test_extract_includes_workspace_and_global_instruction(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "CLAUDE.md").write_text("claude rules", encoding="utf-8")
    (workspace / "AGENTS.md").write_text("agents rules", encoding="utf-8")
    (workspace / "CODEX.md").write_text("codex rules", encoding="utf-8")
    home = tmp_path / "home"
    _write_global(home, "global rules")

    findings = extract_context("anything at all", workspace=workspace, home=home)
    by_path = {f.source_path: (f.category, f.confidence) for f in findings}

    assert by_path["CLAUDE.md"] == ("agent_instruction", "high")
    assert by_path["AGENTS.md"] == ("agent_instruction", "high")
    assert by_path["CODEX.md"] == ("agent_instruction", "high")
    assert by_path["~/.claude/CLAUDE.md"] == ("agent_instruction", "high")


def test_extract_includes_agent_instruction_with_zero_overlap(tmp_path: Path) -> None:
    (tmp_path / "CLAUDE.md").write_text("xyzzy plugh frobnicate", encoding="utf-8")

    findings = extract_context("completely different words entirely", workspace=tmp_path, home=None)

    assert any(
        f.source_path == "CLAUDE.md" and f.category == "agent_instruction" for f in findings
    )


def test_extract_caps_per_file_chars(tmp_path: Path) -> None:
    # A huge header-less instruction file is truncated to the chunk cap, well
    # below the raw read cap.
    (tmp_path / "CLAUDE.md").write_text("a" * (MAX_CHARS_PER_FILE * 3), encoding="utf-8")

    findings = extract_context("a", workspace=tmp_path, home=None)
    claude = next(f for f in findings if f.source_path == "CLAUDE.md")

    assert len(claude.text) <= MAX_INSTRUCTION_CHARS_PER_FILE


def test_extract_keeps_all_instruction_findings_chunked(tmp_path: Path) -> None:
    # Four authoritative instruction files, each far larger than the per-file
    # chunk cap. The floor is never dropped for budget AND each file is reduced
    # to at most MAX_INSTRUCTION_CHARS_PER_FILE (latency: no whole-file dumps).
    workspace = tmp_path / "ws"
    workspace.mkdir()
    home = tmp_path / "home"
    for filename in ("CLAUDE.md", "AGENTS.md", "CODEX.md"):
        (workspace / filename).write_text(
            f"{filename} rules " * 4000, encoding="utf-8"
        )
    _write_global(home, "global rules " * 4000)

    findings = extract_context("anything", workspace=workspace, home=home)
    paths = _paths(findings)

    for expected in ("CLAUDE.md", "AGENTS.md", "CODEX.md", "~/.claude/CLAUDE.md"):
        assert expected in paths, expected
    for finding in findings:
        assert len(finding.text) <= MAX_INSTRUCTION_CHARS_PER_FILE


def test_chunk_keeps_overview_and_relevant_section_drops_irrelevant(tmp_path: Path) -> None:
    # A large sectioned CLAUDE.md: the overview is always kept, the section that
    # matches the request survives, and a far unrelated section is dropped.
    body = (
        "# Project\n\nThis is the overview paragraph.\n\n"
        "## Authentication\n\n" + ("token session login refresh. " * 40) + "\n\n"
        "## Deployment Weather Trivia\n\n" + ("banana pancake syrup forecast. " * 400) + "\n"
    )
    (tmp_path / "CLAUDE.md").write_text(body, encoding="utf-8")

    findings = extract_context("how does authentication login work", workspace=tmp_path, home=None)
    claude = next(f for f in findings if f.source_path == "CLAUDE.md")

    assert "overview paragraph" in claude.text          # overview always kept
    assert "Authentication" in claude.text              # relevant section kept
    assert "banana pancake" not in claude.text          # irrelevant section dropped
    assert len(claude.text) <= MAX_INSTRUCTION_CHARS_PER_FILE


def test_chunk_no_term_match_keeps_overview_only(tmp_path: Path) -> None:
    # No query term matches any section: only the file's overview survives.
    body = (
        "# Project\n\nThe canonical overview.\n\n"
        "## Build\n\n" + ("compile bundle artifact. " * 40) + "\n"
    )
    (tmp_path / "CLAUDE.md").write_text(body, encoding="utf-8")

    findings = extract_context("xylophone zephyr quokka", workspace=tmp_path, home=None)
    claude = next(f for f in findings if f.source_path == "CLAUDE.md")

    assert "canonical overview" in claude.text
    assert "compile bundle artifact" not in claude.text


def test_chunk_ignores_headers_inside_code_fences(tmp_path: Path) -> None:
    # A ``# comment`` inside a fenced code block must not be treated as a section
    # header (it would otherwise split the overview mid-example).
    body = (
        "# Project\n\nOverview line.\n\n"
        "## Running\n\n```bash\n# Preferred entry point\nrun --now\n```\n\n"
        "the running section body mentions authentication flow.\n"
    )
    (tmp_path / "CLAUDE.md").write_text(body, encoding="utf-8")

    findings = extract_context("authentication flow", workspace=tmp_path, home=None)
    claude = next(f for f in findings if f.source_path == "CLAUDE.md")

    # The Running section (with its fenced comment) survives intact as one block.
    assert "# Preferred entry point" in claude.text
    assert "run --now" in claude.text


# --- query-driven grep snippets ---


def test_extract_source_term_yields_snippet_finding(tmp_path: Path) -> None:
    # A request term appearing in a workspace SOURCE file surfaces as a bounded
    # path:line snippet — the grep retrieval path, end-to-end through extract_context.
    (tmp_path / "CLAUDE.md").write_text("project rules", encoding="utf-8")
    src = tmp_path / "src"
    src.mkdir()
    (src / "auth.py").write_text(
        "def authenticate_user(token):\n    return verify(token)\n", encoding="utf-8"
    )

    findings = extract_context("how does authenticate_user work", workspace=tmp_path, home=None)

    snippet = next((f for f in findings if f.source_path.startswith("src/auth.py")), None)
    assert snippet is not None
    assert snippet.category == "implementation_pattern"
    assert ":" in snippet.source_path  # path:line provenance
    assert "authenticate_user" in snippet.text
    # instruction floor still present alongside the snippet
    assert any(f.source_path == "CLAUDE.md" for f in findings)


def test_extract_big_plan_snippet_not_whole_and_unrelated_excluded(tmp_path: Path) -> None:
    # A term appearing only in a big docs/plans file no longer dumps the whole file;
    # it appears (if at all) as a bounded snippet. An UNRELATED plan is not included
    # (the old always-include-all-plans behavior is gone).
    plans = tmp_path / "docs" / "plans"
    plans.mkdir(parents=True)
    big_body = "# Auth Plan\n\n" + ("authentication login session token flow. " * 2000)
    (plans / "relevant.md").write_text(big_body, encoding="utf-8")
    (plans / "unrelated.md").write_text(
        "# Weather\n\nbanana pancake syrup weather forecast\n", encoding="utf-8"
    )

    findings = extract_context("add authentication login flow", workspace=tmp_path, home=None)
    paths = _paths(findings)

    assert not any(p.startswith("docs/plans/unrelated.md") for p in paths)
    relevant = [f for f in findings if f.source_path.startswith("docs/plans/relevant.md")]
    for finding in relevant:
        assert ":" in finding.source_path  # path:line provenance
        assert len(finding.text) < len(big_body)  # a bounded snippet, not the 80 KB file
        assert len(finding.text) <= 5000


def test_extract_env_with_matching_term_never_included(tmp_path: Path) -> None:
    # Defense-in-depth: a planted .env whose contents match a query term is never
    # read or injected (retrieval denylists it; assert at the extract_context level).
    (tmp_path / ".env").write_text("SECRET_TOKEN=authentication-hunter2\n", encoding="utf-8")
    (tmp_path / "app.py").write_text(
        "# authentication handler\nvalue = 1\n", encoding="utf-8"
    )

    findings = extract_context("authentication", workspace=tmp_path, home=None)
    paths = _paths(findings)

    assert not any(".env" in p for p in paths)
    assert all("hunter2" not in f.text for f in findings)


def test_extract_no_match_returns_instruction_floor_only(tmp_path: Path) -> None:
    # No term matches any source: fall back to the instruction floor (still grounded).
    (tmp_path / "CLAUDE.md").write_text("project conventions", encoding="utf-8")
    src = tmp_path / "src"
    src.mkdir()
    (src / "widget.py").write_text("def render_widget():\n    return None\n", encoding="utf-8")

    findings = extract_context("xylophone zephyr quokka", workspace=tmp_path, home=None)

    assert _paths(findings) == ["CLAUDE.md"]


# --- dedup / bounds / never-raises ---


def test_extract_dedups_identical_snippet_text(tmp_path: Path) -> None:
    # Two source files with byte-identical content yield one deduped snippet.
    src = tmp_path / "src"
    src.mkdir()
    body = "def handle_login():\n    return authenticate()\n"
    (src / "a.py").write_text(body, encoding="utf-8")
    (src / "b.py").write_text(body, encoding="utf-8")

    findings = extract_context("login", workspace=tmp_path, home=None)

    assert len([f for f in findings if "handle_login" in f.text]) == 1


def test_extract_enforces_bounds_with_floor_kept(tmp_path: Path) -> None:
    for filename in ("CLAUDE.md", "AGENTS.md", "CODEX.md"):
        (tmp_path / filename).write_text(f"{filename} project rules", encoding="utf-8")
    src = tmp_path / "src"
    src.mkdir()
    for index in range(12):
        (src / f"module{index:02d}.py").write_text(
            f"# marker widget {index}\nvalue_{index} = {index}\n", encoding="utf-8"
        )

    findings = extract_context("widget", workspace=tmp_path, home=None)
    paths = _paths(findings)

    assert len(findings) <= MAX_FINDINGS
    for filename in ("CLAUDE.md", "AGENTS.md", "CODEX.md"):
        assert filename in paths  # instruction floor never dropped for budget
    assert sum(len(f.text) for f in findings) <= MAX_TOTAL_CHARS


def test_extract_no_sources_returns_empty(tmp_path: Path) -> None:
    assert extract_context("x", workspace=tmp_path, home=None) == ()
    assert extract_context("x", workspace=None, home=None) == ()


def test_extract_never_raises_on_non_str_request(tmp_path: Path) -> None:
    # A non-str request must be handled gracefully: no terms/snippets, but the
    # instruction floor still stands (best-effort, never raised).
    (tmp_path / "CLAUDE.md").write_text("rules", encoding="utf-8")

    findings = extract_context(None, workspace=tmp_path, home=None)  # type: ignore[arg-type]

    assert _paths(findings) == ["CLAUDE.md"]


# --- .mcp.json tooling finding (name-only) ---


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


def test_extract_mcp_without_server_map_is_skipped(tmp_path: Path) -> None:
    # No ``mcpServers`` map: never fall back to leaking top-level JSON keys.
    (tmp_path / ".mcp.json").write_text(
        '{"someSecretKey": "value", "another": {"nested": true}}',
        encoding="utf-8",
    )
    (tmp_path / "CLAUDE.md").write_text("rules", encoding="utf-8")

    findings = extract_context("secret", workspace=tmp_path, home=None)
    paths = _paths(findings)

    assert ".mcp.json" not in paths
    assert all("someSecretKey" not in f.text for f in findings)
