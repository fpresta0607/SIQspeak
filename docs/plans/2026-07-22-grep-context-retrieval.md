# Grep-Driven Context Retrieval for Code Mode

**Goal:** Replace Code mode's whole-file context loading (read ~6 files incl. big historical `docs/plans/*.md`, ~40 KB, keyword-rank the files) with **query-driven grep retrieval**: extract the request's terms → grep the repo → inject only the matching snippets (~8–12 KB) with `path:line` provenance. This is how coding agents actually gather context.

**Why:** whole-file pre-loading is slow (a 4b model over ~40 KB), dilutes/hallucinates (the plan docs bleed stale facts into every answer), and never surfaces relevant *source* code. Query-driven grep is fast, targeted, source-aware, and needs no vector DB / embeddings / re-ranker.

**Preserve:** the `ContextFinding` shape, trust-tier messages, deterministic `sources_of_truth`, the Engineering Task contract, mode routing (Default/Code/Email), lossless raw fallback, loopback-only, content-free logging. Email mode is unaffected (it uses no repo context). Only *how findings are gathered* changes.

## Architecture — the retrieval pipeline (replaces `extract_context`'s file-reading)

1. **Query-term extraction** (`enhancement/query.py`, new): tokenize the request; drop stopwords; keep identifiers; split `camelCase`/`snake_case`; capture quoted phrases and explicit file/symbol mentions. Return a bounded, deduped ordered term list.
2. **Grep retriever** (`enhancement/retrieval.py`, new):
   - **Engine:** prefer `ripgrep` (`rg`) if on PATH (fast, respects `.gitignore`, skips binaries) — detect availability like `nvidia-smi`; **fall back** to a bounded Python `os.walk` + `re` when `rg` is absent (no hard dependency). Use fixed arg lists (no shell), a timeout, `CREATE_NO_WINDOW`, `-n` for line numbers, case-insensitive, word-ish matching.
   - **Scope:** the resolved workspace root; skip `.git`/`node_modules`/build/binary; respect `.gitignore`. Search source + docs by term; instruction files (`CLAUDE.md`/`AGENTS.md`/`CODEX.md`) are always read as the floor (unchanged).
   - **Snippet extraction:** per hit, take the enclosing markdown `##` section (docs) or matching line ± N lines (code), attributed `path:line`. Never whole files.
   - **Rank & dedup:** score by distinct query-terms matched × file-type priority (instruction > source > docs), mtime tiebreak; dedup overlapping snippets.
   - **Bounds (module constants):** `MAX_HITS`, `MAX_SNIPPET_CHARS`, `MAX_TOTAL_CHARS ≈ 8–12 KB`, `MAX_FILES_SEARCHED`, `MAX_LINE_BYTES`. Never raise out.
3. **Swap into `extract_context`:** instruction files (always) + grep snippets (query-driven) → `ContextFinding`s. Drop the `docs/plans/**` glob. Keep `.mcp.json` name-only tooling finding. Fall back to instruction-files-only when grep finds nothing.

## Security (the sharp edge — grepping arbitrary repo files is a new secret path)
- **Secret-file denylist** applied before reading ANY hit: `.env*`, `*.key`, `*.pem`, `id_rsa*`, `*.pfx`, `*.tfvars`, `*.secret`, `.npmrc`, `.netrc`, and never read `.mcp.json` values (names-only path already exists). Also honor `.gitignore` (rg does natively; the Python fallback must too, at least skip common secret/ignored dirs).
- Reuse existing **containment/symlink guards** (`_is_within`), the **control/exfil scrub** on injected text, **content-free logging** (log counts/`path` only, never snippet text), and the **untrusted-reference trust tier** framing.
- The `rg`/subprocess call: fixed args, timeout, no shell, swallow all errors → empty result (never break enhancement).

## Performance
`rg`/grep is milliseconds; LLM inference dominates and scales with context size. ~40 KB → ~8–12 KB of *relevant* text ≈ **2–4× faster Code mode** before touching model size. Optional per-repo file-list cache (mtime-keyed) only if enumeration is slow on huge repos — likely unnecessary; do NOT build speculatively.

## Phases
1. **Query extraction** (`query.py` + tests): terms, identifier splitting, stopwords, bounds. Pure.
2. **Grep retriever** (`retrieval.py` + tests): rg-or-Python engine, snippet extraction, rank/dedup/bounds, **secret denylist + containment**, never-raises. Fixture-repo tests incl. a planted `.env` that must NOT be retrieved.
3. **Integrate into `extract_context`** (`context.py` + tests): instruction floor + grep snippets; drop the `docs/plans` glob; instruction-only fallback. `ContextFinding` shape + service/trust-tier tests stay green.
4. **Verify + review:** real-model Code-mode latency before/after (record numbers); adversarial code + security review (focus: secret denylist, containment, no content logging, subprocess safety); full `pytest`/`ruff`/`pyright`; enhancement coverage ≥ 80%.

## Final task: Finalize and merge to main
- Rebase `origin/main`; adversarial review; fix findings; `/finalize --merge` to `main` (user's standing preference this session); push; remove worktree; restart SIQspeak; live-test Code-mode latency + grounding.
