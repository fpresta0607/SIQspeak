"""Assemble bounded, provenance-tagged context for Code-mode prompt enhancement.

Two sources feed the enhancer, in priority order:

1. **Instruction floor (always):** the agent-instruction files (`CLAUDE.md`,
   `AGENTS.md`, `CODEX.md` in the workspace + global `~/.claude/CLAUDE.md`) plus a
   name-only `.mcp.json` tooling finding. These are read — never executed or
   interpreted — and reduced to a small always-kept overview plus the sections
   most relevant to the spoken request, so a large instruction file adds only a
   few kilobytes to the prompt instead of tens. The floor is never dropped for
   budget.
2. **Query-driven snippets:** the request's search terms are grepped across the
   workspace (`retrieval.py`) and only the matching `path:line` snippets are
   injected — never whole files.

This text flows into the LLM prompt (not typed via SendInput), so normal newlines
and markdown are preserved; only NUL bytes are stripped as a hygiene measure.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from siqspeak.enhancement.query import extract_query_terms

MAX_CONTEXT_BYTES = 16 * 1024

# Hard bounds enforced by extract_context.
MAX_CHARS_PER_FILE = MAX_CONTEXT_BYTES  # reuse the 16 KiB per-file read cap
MAX_TOTAL_CHARS = 48 * 1024  # combined size of returned finding text
MAX_FINDINGS = 10  # returned finding count

# Instruction-floor chunking: an oversized CLAUDE.md/AGENTS.md used to enter the
# prompt whole (up to the 16 KiB read cap), inflating latency. Each instruction
# file is now reduced to a small overview (its title/preamble) plus the sections
# most relevant to the request, capped well below the read cap.
MAX_INSTRUCTION_CHARS_PER_FILE = 3000  # chunked floor: overview + relevant sections
MAX_INSTRUCTION_OVERVIEW_CHARS = 900   # always-kept preamble/first section

_HEADER_LINE_RE = re.compile(r"^#{1,6}\s+\S")

WORKSPACE_INSTRUCTION_FILES = ("CLAUDE.md", "AGENTS.md", "CODEX.md")

AGENT_INSTRUCTION = "agent_instruction"

_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


@dataclass(frozen=True)
class ContextFinding:
    source_path: str
    category: str  # agent_instruction | architecture | implementation_pattern
    #               | tooling | constraint | verification
    text: str
    confidence: str  # high | medium | low


def extract_context(
    request: str,
    workspace: Path | None,
    home: Path | None,
) -> tuple[ContextFinding, ...]:
    """Return ranked, bounded, provenance-tagged context for a spoken request.

    The always-present instruction floor (agent-instruction files + a name-only
    `.mcp.json` tooling finding) comes first and is never dropped for budget.
    Query-driven grep snippets (`retrieval.py`), ranked and `path:line`-attributed,
    follow and are subject to the ``MAX_TOTAL_CHARS`` budget. Snippets from files
    already in the floor are skipped, and repeat paths / near-duplicate texts are
    collapsed. Read-only and local; it never logs content and never raises — on any
    failure it returns whatever was safely gathered so far.
    """
    # Deferred import: retrieval.py imports from this module, so a top-level import
    # here would be circular.
    from siqspeak.enhancement.retrieval import retrieve_snippets

    seen_paths: set[str] = set()
    seen_texts: set[str] = set()
    floor: list[ContextFinding] = []
    snippets: list[ContextFinding] = []

    def _accept(finding: ContextFinding, bucket: list[ContextFinding]) -> None:
        normalized = _normalize_text(finding.text)
        if finding.source_path in seen_paths or normalized in seen_texts:
            return
        seen_paths.add(finding.source_path)
        seen_texts.add(normalized)
        bucket.append(finding)

    try:
        try:
            terms = extract_query_terms(request)
        except Exception:
            # A non-str/malformed request must not sink the floor; chunk on the
            # overview only (empty terms) and continue.
            terms = ()

        for finding in _discover(workspace, home, terms):
            _accept(finding, floor)

        if workspace is not None:
            floor_paths = {finding.source_path for finding in floor}
            for finding in retrieve_snippets(terms, workspace):
                # Never re-inject an instruction/tooling file already in the floor
                # as a lower-trust snippet (its source_path carries a `:line`).
                base_path = finding.source_path.rsplit(":", 1)[0]
                if base_path in floor_paths:
                    continue
                _accept(finding, snippets)
    except Exception:
        # Best-effort: return whatever was gathered before the failure.
        pass

    result: list[ContextFinding] = []
    total_chars = 0
    # Authoritative instruction-floor findings are ALWAYS kept (only MAX_FINDINGS
    # bounds them); the total-chars budget must never silently drop them.
    for finding in floor:
        if len(result) >= MAX_FINDINGS:
            break
        result.append(finding)
        total_chars += len(finding.text)
    # The ranked snippet tail is subject to the total-chars budget.
    for finding in snippets:
        if len(result) >= MAX_FINDINGS:
            break
        if total_chars + len(finding.text) > MAX_TOTAL_CHARS:
            continue
        result.append(finding)
        total_chars += len(finding.text)
    return tuple(result)


def _discover(
    workspace: Path | None,
    home: Path | None,
    terms: tuple[str, ...],
) -> list[ContextFinding]:
    """Read the always-present instruction floor.

    Agent-instruction files (workspace, then global) followed by the name-only
    ``.mcp.json`` tooling finding. Every file is symlink-guarded, containment-
    checked, and byte-capped by ``_read_bounded``, then reduced by
    ``_chunk_instruction`` to a small overview plus the ``terms``-relevant sections.
    """
    findings: list[ContextFinding] = []

    def _add_file(path: Path, root: Path | None, source_path: str, category: str,
                  confidence: str) -> None:
        text = _read_bounded(path, root=root)
        if text is None or not text.strip():
            return
        chunked = _chunk_instruction(text, terms)
        if not chunked:
            return
        findings.append(ContextFinding(source_path, category, chunked, confidence))

    if workspace is not None:
        root = Path(workspace)
        for filename in WORKSPACE_INSTRUCTION_FILES:
            _add_file(root / filename, root, filename, AGENT_INSTRUCTION, "high")

    if home is not None:
        global_path = Path(home) / ".claude" / "CLAUDE.md"
        _add_file(global_path, None, "~/.claude/CLAUDE.md", AGENT_INSTRUCTION, "high")

    if workspace is not None:
        mcp_finding = _read_mcp(Path(workspace))
        if mcp_finding is not None:
            findings.append(mcp_finding)

    return findings


def _read_mcp(root: Path) -> ContextFinding | None:
    """Return a tooling finding of ``.mcp.json`` server names — never any values."""
    text = _read_bounded(root / ".mcp.json", root=root)
    if text is None:
        return None
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    servers = data.get("mcpServers")
    if not isinstance(servers, dict):
        # No recognizable server map — never fall back to leaking top-level keys.
        return None
    names = sorted(
        _CONTROL_RE.sub("", key).strip() for key in servers if isinstance(key, str)
    )
    names = [name for name in names if name]
    if not names:
        return None
    return ContextFinding(".mcp.json", "tooling", ", ".join(names), "medium")


def _chunk_instruction(text: str, terms: tuple[str, ...]) -> str:
    """Reduce an instruction file to a small overview plus request-relevant sections.

    The leading block (title + preamble, i.e. everything before the first markdown
    header) is always kept as an overview. Remaining ``#``/``##`` sections are scored
    by how many query ``terms`` they contain; the top-scoring ones are appended in
    document order until ``MAX_INSTRUCTION_CHARS_PER_FILE`` is reached. With no query
    terms (or no matching section) only the overview survives. Deterministic.
    """
    sections = _split_sections(text)
    if len(sections) <= 1:
        return text[:MAX_INSTRUCTION_CHARS_PER_FILE].strip()

    overview = sections[0].strip()[:MAX_INSTRUCTION_OVERVIEW_CHARS].strip()
    lowered = [term.lower() for term in terms if term]
    scored: list[tuple[int, int, str]] = []
    if lowered:
        for index, section in enumerate(sections[1:]):
            low = section.lower()
            score = sum(low.count(term) for term in lowered)
            if score:
                scored.append((score, index, section.strip()))
    scored.sort(key=lambda item: (-item[0], item[1]))

    chosen: list[tuple[int, str]] = []
    used = len(overview)
    for _score, index, block in scored:
        if used + len(block) + 2 > MAX_INSTRUCTION_CHARS_PER_FILE:
            continue
        chosen.append((index, block))
        used += len(block) + 2
    chosen.sort(key=lambda item: item[0])

    parts = [overview, *(block for _index, block in chosen)]
    return "\n\n".join(part for part in parts if part)[:MAX_INSTRUCTION_CHARS_PER_FILE]


def _split_sections(text: str) -> list[str]:
    """Split markdown into blocks that each begin at a real (non-fenced) header.

    The first block is the title/preamble. Header lines inside fenced code blocks
    (``` or ~~~) are ignored so a ``# comment`` in a code sample never splits a
    section. Each source line lands in exactly one block.
    """
    sections: list[str] = []
    current: list[str] = []
    in_fence = False
    for line in text.splitlines(keepends=True):
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            current.append(line)
            continue
        if not in_fence and current and _HEADER_LINE_RE.match(line):
            sections.append("".join(current))
            current = []
        current.append(line)
    if current:
        sections.append("".join(current))
    return sections


def _normalize_text(text: str) -> str:
    return " ".join(text.lower().split())


def _is_within(path: Path, root: Path | None) -> bool:
    """Reject symlinks; for workspace files require containment under ``root``.

    Guards against symlinks/junctions escaping the intended root. Global files
    (``root is None``) only need the symlink check — home is trusted.
    """
    try:
        if path.is_symlink():
            return False
        if root is not None:
            resolved = path.resolve()
            root_resolved = root.resolve()
            if resolved != root_resolved and root_resolved not in resolved.parents:
                return False
    except OSError:
        return False
    return True


def _read_bounded(path: Path, root: Path | None = None) -> str | None:
    if not _is_within(path, root):
        return None
    if not path.is_file():
        return None
    try:
        with path.open("rb") as handle:
            # Bounded read: at most MAX_CONTEXT_BYTES; any content past the cap
            # is silently truncated so one huge file can't flood the prompt.
            raw = handle.read(MAX_CONTEXT_BYTES)
    except OSError:
        return None
    return raw.replace(b"\x00", b"").decode("utf-8", errors="replace")
