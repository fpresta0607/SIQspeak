# Local AI, Model, and UI Upgrade Design

## Goal

Modernize SIQspeak without replacing its lightweight native architecture:

- curate currently available CPU-friendly speech models;
- remove the transcription-history hover glitch and refine the UI;
- add optional local prompt enhancement through Ollama;
- discover relevant Agent Skills from trusted user and workspace locations; and
- produce stronger software-development prompts without launching agents or executing skills.

## Research Findings

### History hover glitch

The history panel currently recomputes text layout, rerasterizes the entire panel, allocates a new bitmap, and uploads that bitmap through `UpdateLayeredWindow` whenever the copy-hover row changes. The work runs on the main Win32 message-loop thread.

Measured redraw times for a 50-entry history were approximately 38–95 ms for representative entries, before accounting for the final GDI upload. The application timer runs every 33 ms. This makes pointer stutter and visible redraw artifacts expected even after the earlier font-cache and `SetWindowPos` fixes.

The design removes hover-driven history redraws instead of attempting another timing-sensitive optimization.

### Speech models

The installed `faster-whisper` 1.2.1 release supports English-specific and distilled checkpoints that SIQspeak does not expose. Public Hugging Face model repositories do not require the mandatory account/token flow currently imposed by the installer.

The curated English set is:

| Model | Role | Approximate download |
| --- | --- | ---: |
| `tiny.en` | Fastest | 75 MB |
| `base.en` | Default | 141 MB |
| `small.en` | Balanced | 464 MB |
| `distil-medium.en` | High quality | 755 MB |
| `distil-large-v3.5` | Best English option | 1.45 GB |

Existing configured model identifiers remain loadable for backward compatibility. New installations use `base.en`.

### Prompt model

Ollama is the local inference boundary. `qwen3.5:2b` is the default enhancer because the intended audience is more sensitive to memory and latency than maximum model capability. `qwen3.5:4b` remains an optional quality upgrade.

The application uses Ollama's loopback HTTP API and structured outputs. It does not require the Python Ollama SDK. A deterministic formatter, schema validation, catalog validation, and raw-text fallback compensate for the smaller default model.

### Agent Skills

Codex, Claude Code, Cursor, and VS Code Copilot support `SKILL.md`-based Agent Skills with progressive disclosure. Their default directories differ, so SIQspeak uses a compatibility scanner over trusted user and workspace locations.

SIQspeak reads skill frontmatter metadata only. It never executes skill instructions, scripts, commands, tools, or agents.

## Architecture

### Native application

Retain the existing Win32/Pillow overlay, message loop, global hotkey, microphone capture, transcription worker, focus restoration, and Unicode typing.

New logic is isolated in an `enhancement` package:

- `skills.py`: trusted-path discovery, frontmatter parsing, explicit matching, and semantic candidate preparation;
- `ollama.py`: loopback availability checks, model discovery, model pulling, and schema-constrained chat calls;
- `prompt.py`: response validation and deterministic prompt formatting; and
- `service.py`: orchestration, timeout/fallback behavior, and the public enhancement boundary.

### Transcription flow

Enhancement disabled:

1. Capture speech.
2. Transcribe locally.
3. Store and type the raw transcript.

Enhancement enabled:

1. Capture speech.
2. Transcribe locally and preserve the raw transcript.
3. Resolve the workspace from an explicit override or best-effort foreground-editor detection.
4. Load cached skill metadata for trusted user and workspace locations.
5. Preserve explicitly named skills.
6. Shortlist semantically relevant skills from names and descriptions.
7. Ask the configured Ollama model for a structured implementation brief and final skill selection.
8. Reject unknown or automatically prohibited skill names.
9. Format a portable expert prompt.
10. Store both raw and enhanced text, then type the enhanced text.

The receiving coding agent decides whether and how to invoke requested skills under its own permission model.

### Skill selection rules

- Explicit skill mentions take precedence and are preserved when a matching skill exists.
- Semantic selection may add helpful skills from the discovered catalog.
- Automatic selection is restricted to catalog entries.
- Skills with `disable-model-invocation: true` are excluded from automatic selection.
- An explicitly named restricted skill may remain in the prompt; the receiving agent still enforces its own invocation rules.
- Duplicate skills from multiple sources are represented once in the prompt while retaining source metadata internally.
- Malformed frontmatter, oversized descriptions, control characters, and inaccessible paths are ignored safely.

### Prompt structure

The model returns structured fields rather than an unconstrained final paragraph:

- objective;
- context;
- requirements;
- acceptance criteria;
- verification steps; and
- selected skill names.

The application formats these fields consistently and includes the preserved original request. This makes output quality less dependent on model prose and gives the user a reviewable prompt before submission.

### Failure behavior

The raw transcription is the fallback for:

- Ollama not installed or unavailable;
- configured model missing;
- pull or inference timeout;
- malformed or schema-invalid model output;
- invalid skill selections;
- workspace-discovery failure; and
- unexpected enhancement exceptions.

Enhancement failures do not discard speech or block later recordings. The UI shows a concise status and logs technical details without logging secrets.

## Workspace and Skill Discovery

Workspace resolution uses:

1. a persisted manual workspace folder override;
2. best-effort foreground VS Code or Cursor workspace detection; then
3. no workspace-specific catalog if neither is reliable.

User and workspace scanners support the relevant compatibility locations:

- `.agents/skills`;
- `.claude/skills`;
- `.codex/skills`;
- `.cursor/skills`;
- `.github/skills`;
- `~/.agents/skills`;
- `~/.claude/skills`;
- `~/.codex/skills`;
- `~/.cursor/skills`; and
- `~/.copilot/skills`.

Scanning is bounded by known roots and `SKILL.md` filenames. Plugin caches and arbitrary recursive home-directory searches are excluded.

## UI Design

### Visual direction

Retain SIQspeak's dark navy and cyan identity with Fluent-inspired typography, spacing, borders, compact cards, consistent icon weight, restrained highlights, and minimal animation.

### Pill and status

The three-icon pill remains. Recording, transcribing, and the new enhancing state use clear, visually distinct but restrained feedback. The application never animates inactive panels on the 30 FPS timer.

### History

- Copy controls remain subtly visible instead of appearing on hover.
- Pointer movement does not trigger panel rendering or window repositioning.
- Entries use compact cards with timestamp, optional `Enhanced` badge, readable final text, and a stable copy action.
- Copy confirmation is an explicit content event and may trigger one redraw.
- Persisted enhanced entries store both `raw_text` and final `text`; legacy entries continue rendering.

### Settings

Add:

- Prompt enhancement toggle;
- detected/manual workspace folder;
- Ollama availability and configured-model status;
- enhancer model selector, defaulting to `qwen3.5:2b`; and
- an explicit install/download action when Ollama or the model is unavailable.

The existing hotkey remains unchanged. When the toggle is enabled, the same hotkey produces enhanced prompts. When disabled, it provides immediate raw dictation.

### Speech model panel

Show the curated English choices with Fastest, Default, Balanced, High Quality, and Best Quality labels. Remove mandatory Hugging Face authentication UI. Preserve loading of legacy configured model identifiers without advertising obsolete choices.

## Installer

The installer:

- installs Python dependencies;
- downloads `base.en` for new installations;
- downloads public Hugging Face models anonymously;
- detects Ollama;
- offers Ollama installation guidance when absent;
- offers `qwen3.5:2b` as an explicit prompt-enhancer download; and
- never downloads multi-gigabyte LLM weights without confirmation.

Model downloads report progress and actionable network/storage failures.

## Security and Privacy

- Audio, raw transcription, skill metadata, and enhanced prompts remain local.
- Ollama requests are restricted to the loopback endpoint.
- Workspace paths are normalized and must remain within explicitly trusted roots.
- Only YAML frontmatter metadata is parsed from skills.
- Skill scripts and supporting resources are never opened or executed by SIQspeak.
- Skill descriptions are treated as untrusted data in the model prompt.
- Automatically prohibited skills are not selected.
- Logs contain statuses and error classes, not full prompts, tokens, or secrets.

## Testing

Automated coverage includes:

- configuration defaults and migrations;
- trusted skill-root enumeration;
- valid and malformed frontmatter;
- explicit skill matching;
- semantic candidate filtering;
- restricted and hallucinated skill rejection;
- deterministic prompt formatting;
- Ollama availability, timeout, invalid JSON, and missing-model behavior;
- raw transcription fallback;
- legacy and enhanced history entries;
- anonymous speech-model downloads;
- curated model metadata; and
- the copy-hover regression: pointer movement performs no history render or panel reposition.

Fresh verification includes the full test suite, Ruff, Pyright, coverage, mocked Ollama integration tests, installer script checks, and a manual Windows checklist for smooth history interaction, focus restoration, toggle persistence, enhancement status, model progress, and raw fallback.

## Sources

- [Faster Whisper](https://github.com/SYSTRAN/faster-whisper)
- [Distil-Whisper large-v3.5](https://huggingface.co/distil-whisper/distil-large-v3.5)
- [Hugging Face snapshot downloads](https://huggingface.co/docs/huggingface_hub/package_reference/file_download)
- [Ollama structured outputs](https://docs.ollama.com/capabilities/structured-outputs)
- [Ollama Windows support](https://docs.ollama.com/windows)
- [Qwen 3.5 models in Ollama](https://ollama.com/library/qwen3.5)
- [Agent Skills specification](https://agentskills.io/specification)
- [Claude Code skills](https://code.claude.com/docs/en/slash-commands)
- [VS Code Agent Skills](https://code.visualstudio.com/docs/agent-customization/agent-skills)

