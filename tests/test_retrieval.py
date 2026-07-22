"""Tests for grep-based snippet retrieval used by Code-mode context loading.

The Python ``os.walk`` + ``re`` engine is the primary path (``rg`` is an optional
speedup and is not assumed present). These tests build a small fixture repo under
``tmp_path`` and assert retrieval, security denylisting, pruning, ranking, dedup,
and the hard byte/count bounds.
"""
from __future__ import annotations

import contextlib
from pathlib import Path

import pytest

from siqspeak.enhancement.retrieval import (
    MAX_FILE_BYTES,
    MAX_HITS,
    MAX_LINE_BYTES,
    MAX_TOTAL_CHARS,
    retrieve_snippets,
)


def _paths(findings: tuple) -> list[str]:
    return [finding.source_path for finding in findings]


def test_source_file_hit_returns_line_context_snippet(tmp_path: Path) -> None:
    src = tmp_path / "app.py"
    src.write_text(
        "line one\n"
        "line two\n"
        "def validate_login():\n"
        "    return True\n"
        "line five\n",
        encoding="utf-8",
    )

    findings = retrieve_snippets(("validate_login",), tmp_path)

    assert len(findings) == 1
    finding = findings[0]
    assert finding.source_path == "app.py:3"
    assert finding.category == "implementation_pattern"
    assert "def validate_login()" in finding.text
    # ± context lines are included.
    assert "line two" in finding.text
    assert "return True" in finding.text


def test_partial_term_matches_inside_snake_case_identifier(tmp_path: Path) -> None:
    # A request term ("transcription") must match a snake_case identifier
    # ("transcription_language") — `_` counts as a boundary, not a word char.
    src = tmp_path / "config.py"
    src.write_text("def transcription_language() -> str:\n    return 'en'\n", encoding="utf-8")

    findings = retrieve_snippets(("transcription", "language"), tmp_path)

    assert len(findings) == 1
    assert "transcription_language" in findings[0].text
    # Both distinct terms matched → high confidence.
    assert findings[0].confidence == "high"


def test_term_does_not_match_unrelated_superstring(tmp_path: Path) -> None:
    # "cat" must NOT match "category" (a real word continues past the term).
    src = tmp_path / "m.py"
    src.write_text("category = 1\n", encoding="utf-8")

    assert retrieve_snippets(("cat",), tmp_path) == ()


def test_markdown_hit_returns_enclosing_section(tmp_path: Path) -> None:
    doc = tmp_path / "guide.md"
    doc.write_text(
        "# Title\n"
        "intro text\n"
        "\n"
        "## Caching\n"
        "the cache layer uses an LRU policy\n"
        "more cache detail here\n"
        "\n"
        "## Other\n"
        "unrelated content\n",
        encoding="utf-8",
    )

    findings = retrieve_snippets(("cache",), tmp_path)

    assert len(findings) == 1
    finding = findings[0]
    assert finding.category == "architecture"
    assert "## Caching" in finding.text
    assert "LRU policy" in finding.text
    # The next section must NOT bleed in.
    assert "unrelated content" not in finding.text


def test_env_secret_file_is_never_read_or_returned(tmp_path: Path) -> None:
    # THE key security test: a planted .env holding a query term must be invisible.
    (tmp_path / ".env").write_text("api_secret_token = supersecret\n", encoding="utf-8")
    (tmp_path / "notes.md").write_text("## Token\nusing the token here\n", encoding="utf-8")

    findings = retrieve_snippets(("token",), tmp_path)

    for finding in findings:
        assert ".env" not in finding.source_path
        assert "supersecret" not in finding.text
    # The legitimate doc hit is still returned.
    assert any(f.source_path.startswith("notes.md") for f in findings)


def test_key_and_pem_secret_files_are_never_returned(tmp_path: Path) -> None:
    (tmp_path / "server.key").write_text("secret_password value\n", encoding="utf-8")
    (tmp_path / "cert.pem").write_text("secret_password value\n", encoding="utf-8")
    (tmp_path / "secrets.json").write_text('{"secret_password": "x"}\n', encoding="utf-8")

    findings = retrieve_snippets(("secret_password",), tmp_path)

    assert findings == ()


def test_pruned_directories_are_skipped(tmp_path: Path) -> None:
    for pruned in (".git", "node_modules", ".venv"):
        d = tmp_path / pruned
        d.mkdir()
        (d / "buried.py").write_text("uniqueterm here\n", encoding="utf-8")

    findings = retrieve_snippets(("uniqueterm",), tmp_path)

    assert findings == ()


def test_non_allowlisted_and_binary_extensions_skipped(tmp_path: Path) -> None:
    (tmp_path / "blob.bin").write_bytes(b"needle\x00\x01\x02")
    (tmp_path / "image.png").write_bytes(b"needle image data")
    (tmp_path / "archive.zip").write_text("needle inside\n", encoding="utf-8")

    findings = retrieve_snippets(("needle",), tmp_path)

    assert findings == ()


def test_more_distinct_terms_outranks_fewer(tmp_path: Path) -> None:
    two = tmp_path / "rich.py"
    two.write_text("alpha config and beta config together\n", encoding="utf-8")
    one = tmp_path / "poor.py"
    one.write_text("only alpha appears here\n", encoding="utf-8")

    findings = retrieve_snippets(("alpha", "beta"), tmp_path)

    assert len(findings) == 2
    # The file matching two distinct terms ranks first and is high confidence.
    assert findings[0].source_path.startswith("rich.py")
    assert findings[0].confidence == "high"
    assert findings[1].source_path.startswith("poor.py")
    assert findings[1].confidence == "medium"


def test_overlapping_hits_in_same_file_are_deduped(tmp_path: Path) -> None:
    src = tmp_path / "dense.py"
    # Two hits one line apart -> their ±context ranges overlap -> one snippet.
    src.write_text(
        "prefix\n"
        "needle first hit\n"
        "middle\n"
        "needle second hit\n"
        "suffix\n",
        encoding="utf-8",
    )

    findings = retrieve_snippets(("needle",), tmp_path)

    assert len(findings) == 1
    assert "first hit" in findings[0].text
    assert "second hit" in findings[0].text


def test_max_hits_bound_enforced(tmp_path: Path) -> None:
    for i in range(MAX_HITS + 5):
        (tmp_path / f"f{i:02d}.py").write_text("needle content\n", encoding="utf-8")

    findings = retrieve_snippets(("needle",), tmp_path)

    assert len(findings) <= MAX_HITS


def test_total_chars_bound_enforced(tmp_path: Path) -> None:
    filler = "needle " + ("x " * 400) + "\n"
    for i in range(MAX_HITS):
        (tmp_path / f"big{i:02d}.py").write_text(filler, encoding="utf-8")

    findings = retrieve_snippets(("needle",), tmp_path)

    total = sum(len(f.text) for f in findings)
    assert total <= MAX_TOTAL_CHARS


def test_oversized_file_is_skipped(tmp_path: Path) -> None:
    big = tmp_path / "huge.py"
    big.write_text("needle\n" + ("a" * (MAX_FILE_BYTES + 1000)), encoding="utf-8")

    findings = retrieve_snippets(("needle",), tmp_path)

    assert findings == ()


def test_long_minified_lines_are_skipped(tmp_path: Path) -> None:
    src = tmp_path / "min.js"
    src.write_text("needle" + ("z" * (MAX_LINE_BYTES + 10)) + "\n", encoding="utf-8")

    findings = retrieve_snippets(("needle",), tmp_path)

    assert findings == ()


def test_config_file_categorized_as_tooling(tmp_path: Path) -> None:
    cfg = tmp_path / "settings.toml"
    cfg.write_text("[section]\ntimeout = 30\n", encoding="utf-8")

    findings = retrieve_snippets(("timeout",), tmp_path)

    assert len(findings) == 1
    assert findings[0].category == "tooling"


def test_out_of_root_symlink_dir_is_not_followed(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "a.py").write_text("needle inside repo\n", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "leak.py").write_text("needle leaked secret\n", encoding="utf-8")
    # Windows without privilege: the in-root hit alone still validates the guard.
    with contextlib.suppress(OSError, NotImplementedError):
        (root / "link").symlink_to(outside, target_is_directory=True)

    findings = retrieve_snippets(("needle",), root)

    assert any(f.source_path == "a.py:1" for f in findings)
    for finding in findings:
        assert "leaked" not in finding.text


@pytest.mark.parametrize("terms", [(), None])
def test_empty_terms_returns_empty(tmp_path: Path, terms: object) -> None:
    (tmp_path / "app.py").write_text("anything\n", encoding="utf-8")
    assert retrieve_snippets(terms, tmp_path) == ()  # type: ignore[arg-type]


def test_missing_root_returns_empty() -> None:
    assert retrieve_snippets(("term",), Path("C:/nonexistent/does/not/exist")) == ()
    assert retrieve_snippets(("term",), None) == ()  # type: ignore[arg-type]


def test_never_raises_on_unreadable_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "app.py").write_text("needle\n", encoding="utf-8")

    def _boom(*args: object, **kwargs: object):
        raise OSError("walk exploded")

    monkeypatch.setattr("siqspeak.enhancement.retrieval.os.walk", _boom)

    # Must swallow the failure and return a value, never propagate.
    assert retrieve_snippets(("needle",), tmp_path) == ()
