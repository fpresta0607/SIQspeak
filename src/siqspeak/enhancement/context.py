"""Load project instruction files as bounded context for prompt enhancement.

Instruction files (`CLAUDE.md`, `AGENTS.md`, `CODEX.md`) are the primary sources
of truth for the enhancer. They are read as plain text only — never executed or
interpreted — and each is byte-capped so a huge instruction file cannot blow the
model's context window. This text flows into the LLM prompt (not typed via
SendInput), so normal newlines and markdown are preserved; only NUL bytes are
stripped as a hygiene measure.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

MAX_CONTEXT_BYTES = 16 * 1024

# Hard bounds for rich extraction (all enforced by extract_context).
MAX_CHARS_PER_FILE = MAX_CONTEXT_BYTES  # reuse the 16 KiB per-file read cap
MAX_FILES = 16  # total files read in one extraction
MAX_DOC_FILES = 12  # docs/**/*.md considered per extraction
MAX_TOTAL_CHARS = 48 * 1024  # combined size of returned finding text
MAX_FINDINGS = 10  # returned finding count

WORKSPACE_INSTRUCTION_FILES = ("CLAUDE.md", "AGENTS.md", "CODEX.md")

_AGENT_INSTRUCTION = "agent_instruction"

# Named workspace files beyond the agent-instruction set:
# (filename, category, confidence).
_NAMED_DOC_SOURCES = (
    ("ARCHITECTURE.md", "architecture", "high"),
    ("README.md", "architecture", "medium"),
    ("CONTRIBUTING.md", "constraint", "medium"),
)

_WORD_TOKEN_RE = re.compile(r"[a-z0-9]+")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


@dataclass(frozen=True)
class ContextSource:
    label: str
    text: str


@dataclass(frozen=True)
class ContextFinding:
    source_path: str
    category: str  # agent_instruction | architecture | implementation_pattern
    #               | tooling | constraint | verification
    text: str
    confidence: str  # high | medium | low


def load_instruction_context(
    workspace: Path | None,
    home: Path | None,
) -> tuple[ContextSource, ...]:
    """Return bounded excerpts of project instruction files in priority order.

    Workspace files (`CLAUDE.md`, `AGENTS.md`, `CODEX.md`) come first in that
    order, then the global `~/.claude/CLAUDE.md`. Missing files are skipped.
    """
    sources: list[ContextSource] = []
    if workspace is not None:
        root = Path(workspace)
        for filename in WORKSPACE_INSTRUCTION_FILES:
            text = _read_bounded(root / filename, root=root)
            if text is not None:
                sources.append(ContextSource(label=filename, text=text))
    if home is not None:
        text = _read_bounded(Path(home) / ".claude" / "CLAUDE.md")
        if text is not None:
            sources.append(ContextSource(label="~/.claude/CLAUDE.md", text=text))
    return tuple(sources)


def load_workspace_context(
    workspace: Path | None,
    home: Path | None,
) -> tuple[ContextSource, ...]:
    """Return only the project instruction files as bounded context.

    Thin wrapper over :func:`load_instruction_context`: workspace
    ``CLAUDE.md``/``AGENTS.md``/``CODEX.md`` first, then the global
    ``~/.claude/CLAUDE.md``. Plan docs are intentionally excluded to keep the
    injected context focused on conventions and sources of truth rather than
    diluting the model with large, task-specific narrative.
    """
    return load_instruction_context(workspace, home)


def extract_context(
    request: str,
    workspace: Path | None,
    home: Path | None,
) -> tuple[ContextFinding, ...]:
    """Return ranked, bounded, provenance-tagged context for a spoken request.

    Reads instruction/doc files (never executes them), tags each with a source
    path, category and confidence, then orders agent-instruction findings first
    (always kept — they are authoritative) followed by the remaining findings
    ranked by request/text token overlap. Near-duplicates and repeat paths are
    collapsed, and the hard ``MAX_*`` bounds are enforced. Read-only and local;
    it never logs content and never raises — on any failure it returns whatever
    was safely gathered so far.
    """
    request_tokens = _word_tokens(request)
    seen_paths: set[str] = set()
    seen_texts: set[str] = set()
    instruction: list[ContextFinding] = []
    scored: list[tuple[int, str, ContextFinding]] = []

    try:
        for finding in _discover(workspace, home):
            normalized = _normalize_text(finding.text)
            if finding.source_path in seen_paths or normalized in seen_texts:
                continue
            seen_paths.add(finding.source_path)
            seen_texts.add(normalized)
            if finding.category == _AGENT_INSTRUCTION:
                instruction.append(finding)
            else:
                score = _score(request_tokens, finding)
                scored.append((score, finding.source_path, finding))
    except Exception:
        # Best-effort: return whatever was gathered before the failure.
        pass

    scored.sort(key=lambda item: (-item[0], item[1]))
    ordered = instruction + [finding for _, _, finding in scored]

    result: list[ContextFinding] = []
    total_chars = 0
    for finding in ordered:
        if len(result) >= MAX_FINDINGS:
            break
        if total_chars + len(finding.text) > MAX_TOTAL_CHARS:
            continue
        result.append(finding)
        total_chars += len(finding.text)
    return tuple(result)


def _discover(workspace: Path | None, home: Path | None) -> list[ContextFinding]:
    """Read candidate files in priority order, honouring the MAX_FILES budget.

    Agent-instruction files (workspace, then global) are read first so they are
    never starved by a large ``docs/`` tree.
    """
    findings: list[ContextFinding] = []
    budget = MAX_FILES

    def _add_file(path: Path, root: Path | None, source_path: str, category: str,
                  confidence: str) -> None:
        nonlocal budget
        if budget <= 0:
            return
        text = _read_bounded(path, root=root)
        if text is None:
            return
        budget -= 1
        text = text[:MAX_CHARS_PER_FILE]
        if not text.strip():
            return
        findings.append(ContextFinding(source_path, category, text, confidence))

    if workspace is not None:
        root = Path(workspace)
        for filename in WORKSPACE_INSTRUCTION_FILES:
            _add_file(root / filename, root, filename, _AGENT_INSTRUCTION, "high")

    if home is not None:
        global_path = Path(home) / ".claude" / "CLAUDE.md"
        _add_file(global_path, None, "~/.claude/CLAUDE.md", _AGENT_INSTRUCTION, "high")

    if workspace is not None:
        root = Path(workspace)
        for filename, category, confidence in _NAMED_DOC_SOURCES:
            _add_file(root / filename, root, filename, category, confidence)

        mcp_finding = _read_mcp(root)
        if mcp_finding is not None and budget > 0:
            budget -= 1
            findings.append(mcp_finding)

        docs_root = root / "docs"
        if docs_root.is_dir():
            doc_paths = sorted(docs_root.rglob("*.md"), key=lambda entry: entry.as_posix())
            for doc_path in doc_paths[:MAX_DOC_FILES]:
                if budget <= 0:
                    break
                source_path = doc_path.relative_to(root).as_posix()
                _add_file(doc_path, root, source_path, "architecture", "medium")

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
    raw_keys = servers.keys() if isinstance(servers, dict) else data.keys()
    names = sorted(
        _CONTROL_RE.sub("", key).strip() for key in raw_keys if isinstance(key, str)
    )
    names = [name for name in names if name]
    if not names:
        return None
    return ContextFinding(".mcp.json", "tooling", ", ".join(names), "medium")


def _score(request_tokens: set[str], finding: ContextFinding) -> int:
    finding_tokens = _word_tokens(f"{finding.source_path} {finding.text}")
    return len(request_tokens & finding_tokens)


def _word_tokens(text: str) -> set[str]:
    return set(_WORD_TOKEN_RE.findall(text.lower()))


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
