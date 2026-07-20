"""Discover and rank trusted Agent Skill metadata.

Skill bodies are never executed or interpreted. Only the first bounded YAML
frontmatter block of each `SKILL.md` is parsed for metadata (name, description,
and an optional model-invocation flag). This is a security boundary: discovered
skills are untrusted catalog data, not instructions.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

WORKSPACE_SKILL_DIRS = (
    ".agents/skills",
    ".claude/skills",
    ".codex/skills",
    ".cursor/skills",
    ".github/skills",
)
USER_SKILL_DIRS = (
    ".agents/skills",
    ".claude/skills",
    ".codex/skills",
    ".cursor/skills",
    ".copilot/skills",
)

MAX_SKILL_BYTES = 64 * 1024
MAX_DESCRIPTION_CHARS = 1024
MAX_AUTOMATIC_CANDIDATES = 12

NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_NAME_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9-]*")
_WORD_TOKEN_RE = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class SkillMetadata:
    name: str
    description: str
    path: Path
    disable_model_invocation: bool = False


def discover_skills(workspace: Path | None, home: Path | None) -> tuple[SkillMetadata, ...]:
    """Discover skill metadata under trusted workspace and user roots.

    Workspace roots are scanned before user roots, and directories within each
    root in sorted order, so the first occurrence of a duplicate name wins
    deterministically.
    """
    seen: dict[str, SkillMetadata] = {}
    roots: list[Path] = []
    if workspace is not None:
        roots.extend(Path(workspace) / relative for relative in WORKSPACE_SKILL_DIRS)
    if home is not None:
        roots.extend(Path(home) / relative for relative in USER_SKILL_DIRS)

    for root in roots:
        if not root.is_dir():
            continue
        for skill_dir in sorted(root.iterdir(), key=lambda entry: entry.name):
            if not skill_dir.is_dir():
                continue
            meta = _load_skill(skill_dir)
            if meta is None or meta.name in seen:
                continue
            seen[meta.name] = meta
    return tuple(seen.values())


def find_explicit_skills(request: str, catalog: tuple[SkillMetadata, ...]) -> list[str]:
    """Return names the user named explicitly via `$name`, `/name`, or plain mention."""
    lowered = request.lower()
    mentioned = set(_NAME_TOKEN_RE.findall(lowered))
    explicit: list[str] = []
    for meta in catalog:
        name = meta.name
        if name in mentioned or f"${name}" in lowered or f"/{name}" in lowered:
            explicit.append(name)
    return explicit


def rank_skill_candidates(
    request: str,
    catalog: tuple[SkillMetadata, ...],
) -> list[SkillMetadata]:
    """Rank model-invokable skills by transparent request/metadata token overlap."""
    request_tokens = _word_tokens(request)
    scored: list[tuple[int, SkillMetadata]] = []
    for meta in catalog:
        if meta.disable_model_invocation:
            continue
        metadata_tokens = _word_tokens(f"{meta.name} {meta.description}")
        score = len(request_tokens & metadata_tokens)
        if score:
            scored.append((score, meta))
    scored.sort(key=lambda item: (-item[0], item[1].name))
    return [meta for _, meta in scored[:MAX_AUTOMATIC_CANDIDATES]]


def _word_tokens(text: str) -> set[str]:
    return set(_WORD_TOKEN_RE.findall(text.lower()))


def _load_skill(skill_dir: Path) -> SkillMetadata | None:
    skill_file = skill_dir / "SKILL.md"
    if not skill_file.is_file():
        return None
    try:
        with skill_file.open("rb") as handle:
            content = handle.read(MAX_SKILL_BYTES).decode("utf-8", errors="replace")
    except OSError:
        return None

    frontmatter = _extract_frontmatter(content)
    if frontmatter is None:
        return None
    try:
        data = yaml.safe_load(frontmatter)
    except yaml.YAMLError:
        return None
    if not isinstance(data, dict):
        return None

    name = data.get("name")
    if not isinstance(name, str):
        return None
    name = name.strip().lower()
    if not NAME_PATTERN.match(name):
        return None

    description = data.get("description", "")
    if not isinstance(description, str):
        description = ""
    description = _sanitize(description)[:MAX_DESCRIPTION_CHARS]

    disabled = data.get("disable-model-invocation", False) is True
    return SkillMetadata(
        name=name,
        description=description,
        path=skill_file,
        disable_model_invocation=disabled,
    )


def _extract_frontmatter(content: str) -> str | None:
    """Return the first YAML frontmatter block, or None if absent/unclosed."""
    lines = content.lstrip("﻿").splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    body: list[str] = []
    for line in lines[1:]:
        if line.strip() == "---":
            return "\n".join(body)
        body.append(line)
    return None


def _sanitize(text: str) -> str:
    return _CONTROL_RE.sub("", text).strip()
