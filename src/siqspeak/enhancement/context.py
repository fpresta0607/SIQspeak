"""Load project instruction files as bounded context for prompt enhancement.

Instruction files (`CLAUDE.md`, `AGENTS.md`, `CODEX.md`) are the primary sources
of truth for the enhancer. They are read as plain text only — never executed or
interpreted — and each is byte-capped so a huge instruction file cannot blow the
model's context window. This text flows into the LLM prompt (not typed via
SendInput), so normal newlines and markdown are preserved; only NUL bytes are
stripped as a hygiene measure.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

MAX_CONTEXT_BYTES = 16 * 1024

WORKSPACE_INSTRUCTION_FILES = ("CLAUDE.md", "AGENTS.md", "CODEX.md")


@dataclass(frozen=True)
class ContextSource:
    label: str
    text: str


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
        for filename in WORKSPACE_INSTRUCTION_FILES:
            text = _read_bounded(Path(workspace) / filename)
            if text is not None:
                sources.append(ContextSource(label=filename, text=text))
    if home is not None:
        text = _read_bounded(Path(home) / ".claude" / "CLAUDE.md")
        if text is not None:
            sources.append(ContextSource(label="~/.claude/CLAUDE.md", text=text))
    return tuple(sources)


def _read_bounded(path: Path) -> str | None:
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
