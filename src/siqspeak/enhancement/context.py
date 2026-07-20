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

MAX_PLAN_SOURCES = 3


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
    """Return instruction files then the newest workspace plan docs.

    Instruction files (from :func:`load_instruction_context`) are PRIMARY and
    come first. Up to :data:`MAX_PLAN_SOURCES` most recently modified
    ``docs/plans/*.md`` files under ``workspace`` follow as SECONDARY context,
    each bounded to :data:`MAX_CONTEXT_BYTES`. Ordering is deterministic:
    mtime descending, then name ascending for ties.
    """
    sources = list(load_instruction_context(workspace, home))
    if workspace is not None:
        root = Path(workspace)
        for plan in _recent_plans(root):
            text = _read_bounded(plan, root=root)
            if text is not None:
                sources.append(ContextSource(label=f"docs/plans/{plan.name}", text=text))
    return tuple(sources)


def _recent_plans(workspace: Path) -> list[Path]:
    plans_dir = workspace / "docs" / "plans"
    if not plans_dir.is_dir():
        return []
    plans = [
        path for path in plans_dir.glob("*.md")
        if path.is_file() and not path.is_symlink()
    ]
    plans.sort(key=lambda path: (-path.stat().st_mtime, path.name))
    return plans[:MAX_PLAN_SOURCES]


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
