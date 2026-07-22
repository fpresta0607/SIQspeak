# Enhancement Modes: Default / Code / Email

**Goal:** Replace the boolean "Enhance prompts" toggle with a 3-mode selector controlling what happens to a dictation before it's typed:
- **Default** — raw Whisper transcript, no LLM (today's "enhance off" behavior).
- **Code** — the engineering-grade prompt enhancer we just shipped (context extraction + Engineering Task brief).
- **Email** — NEW: an LLM rewrites the rough spoken email into a polished one: **greeting + well-structured body + brief closing (e.g. "Thanks,"), NO signature**; a `[name]` placeholder when no recipient is dictated.

Both Code and Email use the local Ollama model (existing model selector powers both). Email needs NO repository context (it's speech→email, not codebase-grounded) — so it skips `extract_context` (faster).

**Preserve:** transcription/TTS behavior; lossless raw-transcript fallback on ANY failure (unavailable Ollama, missing model, malformed output, exception) for both Code and Email; loopback-only; content-free logging; the model selector + workspace detection.

## Phase 1 — Mode state + config migration
- `config.py`: `ENHANCEMENT_MODES = ("default", "code", "email")`; `resolve_enhancement_mode(value) -> str` (validate, fall back to "default").
- `state.py`: replace `enhancement_enabled: bool` with `enhancement_mode: str = "default"`. (Grep all readers.)
- `app.py main()`: `state.enhancement_mode = resolve_enhancement_mode(cfg.get("enhancement_mode", "code" if cfg.get("enhancement_enabled") else "default"))` — migrate legacy `enhancement_enabled`.
- `config.py save_state_config`: persist `enhancement_mode` (drop `enhancement_enabled`).
- Tests: mode default; validation/fallback; legacy `enhancement_enabled=True` → "code"; persistence round-trip.

## Phase 2 — Email pipeline (new module)
- `src/siqspeak/enhancement/email.py`: `EMAIL_SYSTEM_MESSAGE` (rewrite the dictated rough email into a professional, concise email; a greeting line using `[name]` if no recipient is given; a well-structured body preserving the user's intent/facts; a brief closing like `Thanks,`; **never** add a signature/name/title; do not invent facts; strip control/exfil per existing `_clean`). A small `EMAIL_SCHEMA` + `EmailDraft(greeting, body: tuple[str,...], closing)` + `format_email` → `"<greeting>\n\n<body paragraphs>\n\n<closing>"`. `enhance_email(raw_text, *, model, client) -> EnhancementResult` with the lossless raw fallback on every failure (mirror `service.enhance_request`'s fallback contract). Reuse `prompt._clean` for scrubbing.
- Tests: valid draft → formatted email (greeting/body/closing, no signature); `[name]` placeholder present when no recipient; every fallback (unavailable/missing-model/malformed/exception) returns the raw transcript; control/exfil scrubbed.

## Phase 3 — Routing by mode
- `state.py` `EnhancePrompt` protocol unchanged (`(raw_text, window_title, window_hwnd) -> EnhancementResult`).
- `app.py` `_install_enhancer` `enhance_prompt`: branch on `state.enhancement_mode` — `"code"` → existing `extract_context` + `enhance_request`; `"email"` → `enhance_email` (no context). `"default"` never reaches here.
- `audio/recording.py` `_transcribe_and_type`: gate on `state.enhancement_mode != "default"` (was `enhancement_enabled`). Keep the `enhancing` state + all guards + lossless behavior. Log entry records the mode.
- Tests (`test_enhanced_transcription.py`): default mode types raw and calls NO enhancer; code mode routes to the code path; email mode routes to email; each still falls back to raw on failure.

## Phase 4 — Settings UI: 3-mode selector
- `settings_panel.py`: replace the "Enhance prompts" toggle row with a **Mode** row cycling Default → Code → Email (segmented/cycle, mirroring the model selector). Show the active mode + a one-line description. Show the enhancer-model row + install/status ONLY when mode != "default" (both Code and Email need the model). `_settings_render_signature` includes `enhancement_mode`.
- `interaction/click_handlers.py`: `_cycle_enhancement_mode` advances the mode + persists (`save_state_config`); route the new `SettingsAction.MODE`.
- Tests (`test_settings_panel.py`, `test_settings_actions.py`): mode row hit-testing; cycle default→code→email→default + persist; model row hidden in default, shown in code/email; signature changes on mode change.

## Phase 5 — Docs + finalize
- `CLAUDE.md` / `README.md`: document the 3 modes (default/code/email), email format (greeting+body+closing, no signature), that Code+Email use the model.
- Full `pytest` + `ruff` + `pyright` green; enhancement coverage ≥ 80%.

## Final task: Finalize and merge to main
- Rebase `origin/main`; adversarial code + security review (email prompt is a new untrusted-text→typed-output path); fix findings; merge to `main` (user's standing preference this session); push; remove worktree; restart SIQspeak; live-test Code + Email with the real model.
