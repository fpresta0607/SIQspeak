# Fix: distil model download keeps failing

## Diagnosis (evidenced)

- Distil models are large: `distil-medium.en` 755 MB, `distil-large-v3.5` 1.4 GB (vs `base.en` ~140 MB).
- Downloads are anonymous (local-only, no HF token) → HF throttles/rate-limits large transfers.
- `_download_and_load` calls `huggingface_hub.snapshot_download` **once**. A single transient
  network drop/throttle during the long transfer raises → caught → surfaces "Download failed" /
  "Network error". No retry.
- Reproduced: the on-disk cache dir for `distil-medium.en` held only `refs/main` — no blobs,
  no `model.bin` — the signature of an interrupted download (tray app quits kill the `daemon=True`
  download thread). `_is_model_cached` then correctly reports "not cached", so the user re-clicks
  and hits the same fragile transfer → "keeps failing".
- HuggingFace already writes a resumable `.incomplete` blob (confirmed: 67 MB partial appeared),
  so calling `snapshot_download` again **resumes** — the app just never retries automatically.

## Fix

Wrap `snapshot_download` in `_download_and_load` (`src/siqspeak/model/manager.py`) with a bounded
retry-with-resume loop:

- On a transient network error (`ConnectionError`, `TimeoutError`, or `_classify_download_error`
  → "Network error"), sleep briefly and retry — the resume picks up the `.incomplete` blob.
- Cap attempts (e.g. 4). Non-transient errors (disk full, missing repo) fail immediately — no point
  retrying those.
- Preserve existing behavior: final failure still sets `state.download_error` via
  `_classify_download_error`.

No new dependencies. One function changed.

## Verification

- `demo()`/self-check: a small assert-based test that a retrying wrapper calls the downloader again
  after a transient error and stops after success (mock the downloader — no network in tests).
- `ruff check .`
- `pytest` (existing suite stays green).

### Final task: Finalize and close worktree
- Rebase `origin/main` into the worktree branch (Step 5)
- Run `/finalize --merge` (user requested PR + merge to main)
- On success, `/start` removes the worktree (Step 7)
