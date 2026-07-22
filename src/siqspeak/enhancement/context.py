"""Assemble bounded, provenance-tagged context for Code-mode prompt enhancement.

Two sources feed the enhancer, in priority order:

1. **Instruction floor (always):** the agent-instruction files (`CLAUDE.md`,
   `AGENTS.md`, `CODEX.md` in the workspace + global `~/.claude/CLAUDE.md`) read
   as plain text, plus a name-only `.mcp.json` tooling finding. These are read —
   never executed or interpreted — each byte-capped so a huge file cannot blow the
   model's context window, and are never dropped for budget.
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
        for finding in _discover(workspace, home):
            _accept(finding, floor)

        if workspace is not None:
            floor_paths = {finding.source_path for finding in floor}
            terms = extract_query_terms(request)
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


def _discover(workspace: Path | None, home: Path | None) -> list[ContextFinding]:
    """Read the always-present instruction floor.

    Agent-instruction files (workspace, then global) followed by the name-only
    ``.mcp.json`` tooling finding. Every file is symlink-guarded, containment-
    checked, and byte-capped by ``_read_bounded``.
    """
    findings: list[ContextFinding] = []

    def _add_file(path: Path, root: Path | None, source_path: str, category: str,
                  confidence: str) -> None:
        text = _read_bounded(path, root=root)
        if text is None or not text.strip():
            return
        findings.append(ContextFinding(source_path, category, text, confidence))

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
