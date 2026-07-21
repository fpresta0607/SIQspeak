# Engineering-Grade Prompt Enhancer (v1)

**Goal:** Evolve the enhancement pipeline so a loosely spoken request becomes a grounded, engineering-grade implementation brief for a downstream coding agent — anchored in the repo's instruction/doc files, with provenance, ranking, bounds, trust boundaries, and a strict output contract.

**Scope (v1):** instruction + documentation files only. Request-relevant SOURCE/TEST file retrieval is v2 (fast-follow). The local model *synthesizes* the injected context — it does not itself crawl the repo; the produced brief is what lets the downstream agent investigate.

**Preserve:** text-to-speech + transcription behavior; the lossless raw-transcript fallback on any failure; loopback-only Ollama; content-free logging; the model selector + workspace detection just shipped.

## Phase 1 — Context extraction with provenance, ranking, bounds (`context.py`)

- `ContextFinding` frozen dataclass: `source_path: str`, `category: Literal["agent_instruction","architecture","implementation_pattern","tooling","constraint","verification"]`, `text: str`, `confidence: Literal["high","medium","low"]`.
- Discover from the workspace (+ global `~/.claude/CLAUDE.md`): `CLAUDE.md`/`AGENTS.md`/`CODEX.md` (agent_instruction, high), `README.md`/`ARCHITECTURE.md`/`CONTRIBUTING.md` (architecture, high/medium), `docs/**/*.md` (architecture, medium). Also read `.mcp.json` if present → tooling findings (server names only; never secrets).
- **Deterministic-first ranking by relevance to the request** (token overlap with request terms, like `rank_skill_candidates`); dedup overlapping findings; **hard limits**: max files, max chars/file, total-context cap, max findings — all module constants.
- Each finding keeps source attribution. Category assigned by filename/dir. Symlink/containment guards + byte caps carried over.
- Preserve `load_instruction_context` (used elsewhere); add the richer `extract_context(request, workspace, home) -> tuple[ContextFinding, ...]`.
- Tests: discovery per file type; relevance ranking picks request-matching docs; dedup; bounds enforced; missing optional docs degrade to fewer findings (no crash); malformed `.mcp.json` handled safely; global instruction file always included.

## Phase 2 — Engineering Task output contract (`prompt.py`)

- New `PROMPT_SCHEMA` + `PromptBrief` with the sections: `requested_outcome`, `current_state_evidence`, `system_architecture_findings` (list), `implementation_requirements` (list), `non_goals` (list), `sources_of_truth` (list), `investigation_path` (list), `acceptance_criteria` (list), `verification` (list), `final_report_requirements`.
- Formatter emits the exact `# Engineering Task` markdown contract; omit empty sections; keep the raw request verbatim; keep control-char stripping + total safety ceiling.
- **Facts vs assumptions:** system message instructs the model to label unverified statements as assumptions and to draw `sources_of_truth` ONLY from the provided (attributed) context — never invent URLs/paths/APIs.
- Output-contract validation: `build_prompt_brief` validates required fields present & typed; on a malformed/partial payload it raises (→ service falls back to raw), never emits a half-brief silently.
- Tests: valid → full contract; missing/typed-wrong fields rejected; empty sections omitted; sources_of_truth constrained to provided paths; no-clip; ceiling; control chars stripped.

## Phase 3 — Service orchestration, trust boundaries, error handling (`service.py`, `app.py`)

- Pipeline: intent/raw text → `extract_context` (ranked/bounded) → build messages with **distinct trust tiers** as separate messages: (1) system instructions; (2) authoritative repo instructions (agent_instruction findings) — untrusted for *directives*; (3) retrieved evidence (other findings) — untrusted reference; (4) user intent. Retrieved text can never override system behavior (existing guard, extended).
- `enhance_request(..., context: tuple[ContextFinding, ...])`; `app.py` calls `extract_context(raw_text, workspace, home)`.
- **Error handling (observable, not silent):** missing required `~/.claude/CLAUDE.md` or workspace instruction files → log a warning + proceed with partial grounded context; malformed `.mcp.json` → skip tooling findings + warn; empty transcript → no enhancement; LLM failure / output missing required sections → **raw-transcript fallback** with a short error code. Never fabricate context to fill a gap.
- Bounds enforced before the model call (total context cap).
- Tests: instruction findings reach the messages; irrelevant docs excluded; missing metadata → observable warning; malformed `.mcp.json` safe; injection text in a doc cannot change the output schema/behavior; every failure mode still returns the raw transcript.

## Phase 4 — Verification cases + full gate

- Add the 3 representative-input assertions (vague auth request; "add doc context"; regression-sensitive request) as tests asserting the output contains the required sections and does not invent unsupported architecture.
- Full `pytest` + `ruff` + `pyright` green; enhancement-package coverage ≥ 80%.

## Final task: Finalize and merge to main
- Rebase `origin/main`; adversarial code + security review; fix findings; `/finalize`-style gate; merge to `main`; push; remove worktree; restart SIQspeak.
