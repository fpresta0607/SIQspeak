# Context-Aware Prompt Enhancement — Design & Plan

**Status:** Draft for review (not yet approved)
**Depends on:** the shipped `siqspeak.enhancement` package (workspace, skills, ollama, prompt, service)

## Why

The first enhancement release rewrites every spoken request into a fixed 6-section
"engineering brief" using a small local model with **no project context**. In real
use it was **too long, generic, and missed the actual intent** — it spent words on
filler (`Objective: implement a login endpoint`) instead of the parts that matter,
invented requirements, and clipped output at an arbitrary 2000-char cap. It also had
no idea what project the user was in or how they usually work.

The goal: as the user speaks, the enhancer should **faithfully capture intent, then
enrich it with real context from the project and the user's own history** — becoming
smarter about the goal without a training pipeline.

## Non-negotiable: no fine-tuning

The "learn from my prompts" outcome is delivered by **retrieval (RAG) + few-shot
examples**, not by fine-tuning a local model. Fine-tuning needs a training pipeline,
GPU hours, GGUF conversion, and a custom Modelfile, and goes stale immediately.
Retrieval + few-shot gets ~80% of the benefit at ~5% of the cost and stays current.

## Output shape (reprioritized, dense, never clipped)

Replace the generic `objective/context/requirements/acceptance/verification` schema
with the sections the user identified as high-leverage, in priority order:

1. **End-state behavior** — what "done" actually looks like
2. **Sources of truth** — canonical files/docs/APIs to trust
3. **Hard constraints** — the non-negotiables
4. **Acceptance criteria**
5. **Verification**

Rules baked into the system prompt:
- **Faithful:** preserve the user's intent; do NOT invent requirements or claim a skill ran.
- **Dense, not padded:** spend words on the five sections above; omit a section rather than pad it.
- **Anchored:** populate *Sources of truth* and *Hard constraints* from the project's
  instruction files (below), not from guesses.

### De-clip (fixes truncation)

- Raise per-field cap from 2000 → ~8000 chars and list items 25 → ~60.
- Add one **total-output safety ceiling** (~24000 chars) so a malfunctioning model can't
  type without end. This is a runaway guard, not a content limit — it sits far above any real prompt.
- **Keep** control-character stripping (the keystroke-injection guard from the last review).

## Context the enhancer reads (RAG), in priority order

Resolved from the **active target window** (the editor/tab the user dictated into) or a
manual workspace override.

1. **PRIMARY — project instruction files:** `CLAUDE.md`, `AGENTS.md`, `CODEX.md` in the
   workspace, plus global `~/.claude/CLAUDE.md`. These are authoritative — they seed
   *Sources of truth* and *Hard constraints* and set conventions the output must respect.
2. **Plan docs:** `docs/plans/*.md` in the workspace — how the user structures work
   (relevant-goal context + style).
3. **Raw sessions:** Claude/Codex session transcripts (`~/.claude/projects/**`, Codex logs)
   — the user's actual phrasing, used as few-shot style examples (v2).

**Bounded & local:** each source is byte-capped and only *relevant* excerpts are selected
(not whole-file dumps). Everything stays on `127.0.0.1`; nothing is logged (content-free logging holds).

## Model

Single `qwen3.5:2b` (real Ollama model, 2.7 GB, 256K context — verified in the registry).
Quality knob if 2b underdelivers on the reasoning bar: `qwen3.5:4b` (3.4 GB) / `9b` (6.6 GB),
both fit the user's 8 GB GPU. **Fix the prompt design first; reach for a bigger model only if needed.**

---

## Phase A — Mechanical fixes (independent, ship first)

Separate small PR, no dependency on the intelligence work. Branch: `fix/enhancer-model-and-workspace`.

- **A1** Drop the misleading 2b/4b toggle → single `qwen3.5:2b`. Remove `ENHANCEMENT_MODELS`,
  `SettingsAction.ENHANCER_MODEL`, `_cycle_enhancer_model`. Update tests.
- **A2** Resolve workspace from the **target window title** (the window/tab dictated into),
  not launch-time foreground. Add `window_title(hwnd)`; thread it through `enhance_prompt`.
- **A3** Hardware requirement + pre-download check: probe system RAM (ctypes `GlobalMemoryStatusEx`)
  and NVIDIA VRAM (`nvidia-smi`, best-effort). Show "~2.7 GB · needs ~4 GB RAM/VRAM · [your machine]"
  and **refuse the pull** if the machine can't hold it, with a clear message — never download a model that won't run.

## Phase B — Context-aware, reprioritized, de-clipped enhancement (v1)

TDD, one task per unit.

- **B1** New schema + formatter: five sections above; `prompt.py` `PROMPT_SCHEMA`, `PromptBrief`,
  `format_prompt`. Tests: section order, omitted-when-empty, faithful raw request preserved.
- **B2** De-clip: raise caps, add total safety ceiling, keep control-char strip. Tests: long output
  passes through un-clipped; runaway output stops at the ceiling; control chars stripped.
- **B3** Instruction-file context loader: read `CLAUDE.md`/`AGENTS.md`/`CODEX.md` (workspace + global),
  bounded excerpts, as PRIMARY context. New `enhancement/context.py`. Tests: precedence, byte caps,
  missing files, control-char/secret hygiene.
- **B4** Wire context into the service + system prompt: instruction files → *Sources of truth*/*Hard
  constraints*; workspace plans as secondary context. Tests with fake catalog/context: faithful fallback
  to raw text on any failure still holds.

## Phase C — Few-shot personalization (v2, follow-up)

- **C1** Discover the user's plan docs + session transcripts; select a few *relevant* examples.
- **C2** Include them as style examples in the prompt. Privacy: local-only, bounded, relevant-snippet
  selection (never dump whole sessions). Tests: selection relevance, bounds, opt-out.

## Acceptance criteria

- Speaking a short request produces a **dense, faithful** brief in the five prioritized sections,
  anchored on the project's `CLAUDE.md`/`AGENTS.md`/`CODEX.md`, with **no arbitrary truncation**.
- Enhancement still **falls back to the raw transcript** on any failure (unavailable Ollama, missing
  model, malformed output, exception).
- Workspace reflects the **window/tab dictated into**.
- No model download proceeds unless the machine can run it.
- All content stays local; logs remain content-free; control-char stripping intact.
- Ruff/Pyright clean; enhancement-package coverage ≥ 80%.

## Resolved decisions (approved for execution)

- **Output sections:** exactly the five listed, in that order. No separate "light cleanup" mode —
  the faithful/dense system prompt *is* the light behavior (omit sections rather than pad).
- **Model:** default `qwen3.5:2b` (user was explicit). `4b`/`9b` remain an application constant
  that can be raised later; do not add a UI toggle.
- **v2 corpus reach:** workspace `docs/plans/` first, plus global `~/.claude/projects/**` and
  Codex logs, **bounded** — select a few *relevant* excerpts, never dump whole sessions.

## Final task: Finalize and merge to main

- Rebase `origin/main` into the worktree branch.
- Run `/finalize --merge` (user explicitly authorized merge to `main`, not just a PR):
  review + security + ponytail + tests + rebase + merge to `main` + push.
- On success, `/start` removes the worktree.
