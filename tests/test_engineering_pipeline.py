"""End-to-end verification of the Engineering-Task pipeline on spec inputs.

Each case builds a real fixture repo in ``tmp_path`` (instruction file, README,
ARCHITECTURE, and docs), runs :func:`extract_context` against it, then feeds the
findings plus a schema-valid ``FakeClient`` reply through :func:`enhance_request`
and asserts on the rendered ``final_text``. No real model or network is touched.
"""
from __future__ import annotations

from pathlib import Path

from siqspeak.enhancement.context import extract_context
from siqspeak.enhancement.prompt import EnhancementResult
from siqspeak.enhancement.service import enhance_request

# The `##` section headers the Engineering-Task contract must carry when the
# brief is fully populated (sources included because context is non-empty).
REQUIRED_SECTIONS = (
    "## Requested Outcome",
    "## Current-State Evidence",
    "## System Architecture Findings",
    "## Implementation Requirements",
    "## Non-Goals",
    "## Sources of Truth",
    "## Suggested Investigation Path",
    "## Acceptance Criteria",
    "## Verification",
    "## Required Final Report",
)


def _reply() -> dict[str, object]:
    """A schema-valid 10-field Engineering-Task reply.

    ``sources_of_truth`` carries a hallucinated URL on purpose: the service must
    override it with the real provided finding paths and drop the invention.
    """
    return {
        "requested_outcome": "The requested change is delivered and verified",
        "current_state_evidence": "The current implementation is only partially covered",
        "system_architecture_findings": ["The app runs a Win32 message loop on the main thread"],
        "implementation_requirements": ["Change the code", "Add regression tests"],
        "non_goals": ["No unrelated refactoring", "No behavior changes outside scope"],
        "sources_of_truth": ["https://github.com/6beak/hallucinated"],
        "investigation_path": ["Read the instruction file", "Inspect the module under change"],
        "acceptance_criteria": ["The suite passes", "The behavior matches the request"],
        "verification": ["Run pytest", "Run ruff check"],
        "final_report_requirements": ["List every file changed", "Summarize the outcome"],
        "selected_skills": [],
    }


class FakeClient:
    """Available loopback client returning a fixed schema-valid reply."""

    def __init__(self, *, available: bool = True, reply: dict[str, object] | None = None) -> None:
        self.available = available
        self.reply = reply if reply is not None else _reply()

    def is_available(self) -> bool:
        return self.available

    def has_model(self, model: str) -> bool:
        return True

    def chat_structured(
        self,
        model: str,
        messages: list[dict[str, str]],
        schema: dict[str, object],
    ) -> dict[str, object]:
        return self.reply


def _fake_home(tmp_path: Path) -> Path:
    """An empty home dir so the real user's global CLAUDE.md never leaks in."""
    home = tmp_path / "home"
    home.mkdir()
    return home


def _enhance(raw: str, tmp_path: Path, *, available: bool = True) -> EnhancementResult:
    findings = extract_context(raw, tmp_path, _fake_home(tmp_path))
    return enhance_request(
        raw,
        enabled=True,
        model="qwen3.5:4b",
        client=FakeClient(available=available),  # type: ignore[arg-type]
        catalog=(),
        context=findings,
    )


def _sources_section(final_text: str) -> str:
    """The body of the ## Sources of Truth section, up to the next blank line."""
    return final_text.split("## Sources of Truth", 1)[1].split("\n\n", 1)[0]


# --- Case 1: vague request --------------------------------------------------


def _build_vague_repo(tmp_path: Path) -> None:
    (tmp_path / "CLAUDE.md").write_text(
        "# Project Conventions\n\n"
        "- Routes are thin wrappers; business logic lives in services/.\n"
        "- Validate JWT signatures and check token expiry on every request.\n"
        "- Parameterized SQL only.\n",
        encoding="utf-8",
    )
    (tmp_path / "README.md").write_text(
        "# AuthService\n\nA small service handling login and session tokens.\n",
        encoding="utf-8",
    )
    (tmp_path / "ARCHITECTURE.md").write_text(
        "# Architecture\n\nThe auth flow issues a signed JWT after credential checks.\n",
        encoding="utf-8",
    )
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "auth.md").write_text(
        "The authentication flow validates credentials then issues a session token.\n",
        encoding="utf-8",
    )


def test_vague_request_emits_full_contract_with_only_real_sources(tmp_path: Path) -> None:
    _build_vague_repo(tmp_path)
    raw = "Make the auth flow better and clean up the architecture."

    findings = extract_context(raw, tmp_path, _fake_home(tmp_path))
    result = enhance_request(
        raw,
        enabled=True,
        model="qwen3.5:4b",
        client=FakeClient(),  # type: ignore[arg-type]
        catalog=(),
        context=findings,
    )

    assert result.enhanced is True
    assert result.final_text.startswith("# Engineering Task")
    # Every required section header appears for this fully-populated brief.
    for header in REQUIRED_SECTIONS:
        assert header in result.final_text, header

    # Sources of Truth lists exactly the fixture files that were extracted.
    extracted_paths = [finding.source_path for finding in findings]
    assert extracted_paths  # the fixture yielded findings
    sources = _sources_section(result.final_text)
    for path in extracted_paths:
        assert path in sources, path

    # No invented URL/path leaks through — the model's hallucination is dropped.
    assert "6beak" not in result.final_text
    assert "hallucinated" not in result.final_text
    assert "http" not in sources


# --- Case 2: concrete feature -----------------------------------------------


def _build_feature_repo(tmp_path: Path) -> None:
    (tmp_path / "CLAUDE.md").write_text(
        "# Conventions\n\n- Enhancement is opt-in and local-only.\n",
        encoding="utf-8",
    )
    (tmp_path / "README.md").write_text(
        "# SIQspeak\n\nLocal speech-to-text that types transcripts into the active window.\n",
        encoding="utf-8",
    )
    (tmp_path / "ARCHITECTURE.md").write_text(
        "# Architecture\n\nA Win32 message loop drives the tray overlay.\n",
        encoding="utf-8",
    )
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "enhancement.md").write_text(
        "Project documentation context is injected when enhancing spoken coding "
        "prompts, so the model grounds the prompt in real conventions.\n",
        encoding="utf-8",
    )


def test_concrete_feature_matches_relevant_doc_into_sources(tmp_path: Path) -> None:
    _build_feature_repo(tmp_path)
    raw = "Add project documentation context when enhancing my spoken coding prompts."

    findings = extract_context(raw, tmp_path, _fake_home(tmp_path))
    result = enhance_request(
        raw,
        enabled=True,
        model="qwen3.5:4b",
        client=FakeClient(),  # type: ignore[arg-type]
        catalog=(),
        context=findings,
    )

    assert result.enhanced is True
    assert "## System Architecture Findings" in result.final_text
    assert "## Sources of Truth" in result.final_text

    # The relevance-matched doc (mentions "documentation"/"context") is extracted.
    extracted_paths = [finding.source_path for finding in findings]
    assert "docs/enhancement.md" in extracted_paths
    assert "docs/enhancement.md" in _sources_section(result.final_text)


# --- Case 3: regression-sensitive -------------------------------------------


def _build_regression_repo(tmp_path: Path) -> None:
    (tmp_path / "CLAUDE.md").write_text(
        "# Conventions\n\n"
        "- Enhancement falls back to the raw transcript on any failure.\n"
        "- Text-to-speech and the Claude/Codex integrations must keep working.\n",
        encoding="utf-8",
    )
    (tmp_path / "README.md").write_text(
        "# SIQspeak\n\nSpeech-to-text with an optional prompt enhancer.\n",
        encoding="utf-8",
    )
    (tmp_path / "ARCHITECTURE.md").write_text(
        "# Architecture\n\nThe enhancer wraps transcripts before typing them.\n",
        encoding="utf-8",
    )


def test_regression_sensitive_request_carries_non_goals_and_verification(tmp_path: Path) -> None:
    raw = (
        "Improve the prompt enhancer, but don't break text-to-speech or the "
        "Claude and Codex integrations."
    )
    _build_regression_repo(tmp_path)

    result = _enhance(raw, tmp_path)

    assert result.enhanced is True
    assert "## Non-Goals" in result.final_text
    assert "## Verification" in result.final_text


# --- Fallback path ----------------------------------------------------------


def test_unavailable_client_returns_raw_transcript_unchanged(tmp_path: Path) -> None:
    _build_regression_repo(tmp_path)
    raw = "Make the auth flow better and clean up the architecture."

    result = _enhance(raw, tmp_path, available=False)

    # Lossless fallback: the raw transcript is typed verbatim, unenhanced.
    assert result.final_text == raw
    assert result.enhanced is False
    assert result.error is not None
