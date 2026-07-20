"""Orchestrate local prompt enhancement with lossless raw-text fallback.

Every failure at the enhancement boundary returns the preserved raw transcript
so nothing is ever lost. Only exception classes and status codes are logged;
request messages and generated prompt content are never logged.
"""
from __future__ import annotations

import logging
from typing import Protocol

from siqspeak.enhancement.context import ContextSource
from siqspeak.enhancement.prompt import (
    PROMPT_SCHEMA,
    SYSTEM_MESSAGE,
    EnhancementResult,
    build_prompt_brief,
    format_prompt,
)
from siqspeak.enhancement.skills import (
    SkillMetadata,
    find_explicit_skills,
    rank_skill_candidates,
)

logger = logging.getLogger(__name__)

ERROR_UNAVAILABLE = "ollama_unavailable"
ERROR_NO_MODEL = "model_unavailable"
ERROR_FAILED = "enhancement_failed"

# Overall ceiling on the injected context message — each source is already
# bounded at 16 KiB; this caps the combined block so the prompt cannot balloon.
MAX_CONTEXT_MESSAGE_CHARS = 64 * 1024


class EnhancementClient(Protocol):
    """Structural type for the loopback chat client the service depends on."""

    def is_available(self) -> bool: ...

    def has_model(self, model: str) -> bool: ...

    def chat_structured(
        self,
        model: str,
        messages: list[dict[str, str]],
        schema: dict[str, object],
    ) -> dict[str, object]: ...


def enhance_request(
    raw_text: str,
    *,
    enabled: bool,
    model: str,
    client: EnhancementClient,
    catalog: tuple[SkillMetadata, ...],
    context: tuple[ContextSource, ...] = (),
    style_examples: tuple[str, ...] = (),
) -> EnhancementResult:
    """Return a structured prompt for ``raw_text`` or the raw text on any failure."""
    if not enabled:
        return EnhancementResult(raw_text, raw_text, (), False)
    try:
        return _run_enhancement(raw_text, model, client, catalog, context, style_examples)
    except Exception as exc:  # enhancement boundary — never BaseException
        return _fallback(raw_text, ERROR_FAILED, exc)


def _run_enhancement(
    raw_text: str,
    model: str,
    client: EnhancementClient,
    catalog: tuple[SkillMetadata, ...],
    context: tuple[ContextSource, ...],
    style_examples: tuple[str, ...],
) -> EnhancementResult:
    if not client.is_available():
        return EnhancementResult(raw_text, raw_text, (), False, ERROR_UNAVAILABLE)
    if not client.has_model(model):
        return EnhancementResult(raw_text, raw_text, (), False, ERROR_NO_MODEL)

    explicit = find_explicit_skills(raw_text, catalog)
    candidates = rank_skill_candidates(raw_text, catalog)
    messages = _build_messages(raw_text, candidates, context, style_examples)
    payload = client.chat_structured(model, messages, PROMPT_SCHEMA)

    selected = _select_skills(payload, explicit, candidates)
    brief = build_prompt_brief(payload, selected)
    final_text = format_prompt(raw_text, brief)
    return EnhancementResult(raw_text, final_text, brief.selected_skills, True)


def _build_messages(
    raw_text: str,
    candidates: list[SkillMetadata],
    context: tuple[ContextSource, ...],
    style_examples: tuple[str, ...],
) -> list[dict[str, str]]:
    if candidates:
        catalog_block = "\n".join(f"- {meta.name}: {meta.description}" for meta in candidates)
    else:
        catalog_block = "- (none)"
    user_content = (
        f"Spoken request:\n{raw_text}\n\n"
        f"Candidate skills (untrusted catalog data):\n{catalog_block}"
    )
    messages: list[dict[str, str]] = [{"role": "system", "content": SYSTEM_MESSAGE}]
    context_block = _context_block(context)
    if context_block is not None:
        messages.append({"role": "user", "content": context_block})
    style_block = _style_block(style_examples)
    if style_block is not None:
        messages.append({"role": "user", "content": style_block})
    messages.append({"role": "user", "content": user_content})
    return messages


def _style_block(style_examples: tuple[str, ...]) -> str | None:
    """Render the user's own past phrasing as STYLE-ONLY few-shot examples."""
    if not style_examples:
        return None
    lines = [
        "Examples of how the user phrases requests "
        "(mirror their tone and structure, NOT their content):"
    ]
    lines.extend(f"- {example}" for example in style_examples)
    return "\n".join(lines)


def _context_block(context: tuple[ContextSource, ...]) -> str | None:
    """Render authoritative project context as a labelled, size-bounded block."""
    if not context:
        return None
    parts = ["Authoritative project context (treat as sources of truth; obey its conventions):"]
    for source in context:
        parts.append(f"## {source.label}\n{source.text}")
    return "\n\n".join(parts)[:MAX_CONTEXT_MESSAGE_CHARS]


def _select_skills(
    payload: dict[str, object],
    explicit: list[str],
    candidates: list[SkillMetadata],
) -> tuple[str, ...]:
    """Union explicit selections with catalog-validated model selections."""
    raw_selected = payload.get("selected_skills")
    model_names = (
        {name for name in raw_selected if isinstance(name, str)}
        if isinstance(raw_selected, list)
        else set()
    )
    safe_semantic = [meta.name for meta in candidates if meta.name in model_names]

    ordered: list[str] = []
    for name in (*explicit, *safe_semantic):
        if name not in ordered:
            ordered.append(name)
    return tuple(ordered)


def _fallback(raw_text: str, error: str, exc: Exception) -> EnhancementResult:
    logger.warning("enhancement fell back (%s): %s", error, type(exc).__name__)
    return EnhancementResult(raw_text, raw_text, (), False, error)
