# Settings Enhancer Drawer

**Status:** Draft for approval
**Branch:** `feat/settings-enhancer-drawer`
**Type:** feature (UI)

## Goal

Merge the two separate AI-mode settings cards — the **Enhancer model** row and the
**Enhancer ready / hardware / download** status card — into a single collapsible
**Enhancer drawer** nested directly under the **Mode** row. Shown only in Code/Email
modes. Sleeker: one summary line when collapsed, full controls when expanded.

```
Microphone            [ default ⌄ ]
Mode                  [ Code ]
                      AI: structured coding brief from your repo
  ▶ Enhancer          qwen3.5:4b · Ready        ← collapsed: header + summary
Workspace             [ Auto ] C:\dev\...
[ Quit ]

# expanded:
  ▼ Enhancer
     qwen3.5:4b · Balanced · ~3.4 GB · needs ~6 GB    ← click to cycle model
     [detected] 32 GB RAM · RTX 4070
     Enhancer ready                                   ← or Download/Retry button / progress bar
```

## Current state (recon)

- `settings_panel.py::_settings_layout` stacks rows; in AI modes it appends
  `ENHANCER_MODEL` (48px) + `INSTALL_MODEL` (84px). Geometry, render, and the
  click hit-tester (`settings_action_at_y`) are deliberately driven off this one
  pure layout function so they never drift.
- Rendering: `_draw_model` (model + Ready/Download chip + requirement) and
  `_draw_status` (hardware readout + status message + action button / progress bar).
- Clicks: `click_handlers._handle_settings_click` routes `ENHANCER_MODEL →
  _cycle_enhancer_model`, `INSTALL_MODEL → _install_model_action`. The mic row is
  the existing precedent for a collapsible band (`_handle_mic_click` hit-tests
  sub-zones by y-offset within the band).
- State: `mic_expanded` is the collapsible precedent; reset in `_hide_settings_panel`.

## Design

One collapsible band, mirroring the mic pattern exactly (header toggles; sub-zones
are hit-tested by y-offset). No new render/geometry drift risk because everything
stays keyed off `_settings_layout`.

1. **State** (`state.py`): add `enhancer_drawer_expanded: bool = False`.
2. **Enum** (`settings_panel.py`): replace `ENHANCER_MODEL` + `INSTALL_MODEL` with a
   single `SettingsAction.ENHANCER`. (No back-compat shim — delete the two members.)
3. **Layout** (`_settings_layout`): in AI modes append one `ENHANCER` row after MODE
   (not after WORKSPACE — drawer sits under Mode per the ask). Height:
   - collapsed → `SETTINGS_ROW_H` (48)
   - expanded → `SETTINGS_ROW_H` + `ENHANCER_DRAWER_BODY_H` (new const, ~96) so the
     model line, hardware readout, and status/action all fit.
4. **Render**: new `_draw_enhancer_drawer` replacing `_draw_model` + `_draw_status`.
   - Header: `▶/▼ Enhancer` label + right-aligned summary chip.
     - collapsed summary = `"<model> · <Ready|Download>"` (green/cyan), reusing
       `_model_state_display`.
   - Expanded body (reuse existing helpers): model+requirement line
     (`_model_requirement_label`, clickable to cycle), hardware readout
     (`state.enhancement_hardware`), and the status message + action button /
     progress bar (reuse `_status_display` + the existing pull-progress bar draw).
5. **Clicks** (`click_handlers.py`): route `SettingsAction.ENHANCER →
   _handle_enhancer_click(state, ry)`, mirroring `_handle_mic_click`:
   - ry in header band → toggle `enhancer_drawer_expanded`.
   - expanded + ry in model sub-row → `_cycle_enhancer_model`.
   - expanded + ry in action-button sub-row → `_install_model_action`.
   Keep `_cycle_enhancer_model` / `_install_model_action` unchanged.
6. **Signature / reset**: add `enhancer_drawer_expanded` to
   `_settings_render_signature`; reset it in `_hide_settings_panel` (like `mic_expanded`).

## Non-goals

- No change to enhancement behavior, Ollama calls, model catalog, or hardware gate.
- No change to Mode / Workspace / Mic / Quit rows beyond the insert position.
- No new persisted config (drawer state is ephemeral UI, like `mic_expanded`).

## Tests

- `test_settings_panel.py` / `test_settings_actions.py`:
  - Default mode → no ENHANCER row; AI modes → exactly one ENHANCER row after MODE.
  - Collapsed vs expanded band height; panel total height reflects it.
  - `settings_action_at_y` maps the whole band (collapsed and expanded) to `ENHANCER`.
  - Remove/replace references to the deleted `ENHANCER_MODEL` / `INSTALL_MODEL`.
- New `_handle_enhancer_click` unit tests (pure, no Win32): header toggles expand;
  expanded model sub-row cycles model; expanded action sub-row triggers install.
  Follow the `_handle_mic_click` test style.
- Render smoke: `_render_settings_panel` runs for default / code-collapsed /
  code-expanded without error and returns a buffer of the expected height.

## Acceptance criteria

- In Code/Email, a single "Enhancer" drawer sits under Mode; collapsed shows
  `model · state`, expands to model-cycle + requirement + hardware + status/action.
- Default mode shows no enhancer UI at all.
- Model cycling, download/retry, Ollama-missing, and pull-progress all still work
  from inside the drawer.
- Geometry/render/hit-test stay in sync (all keyed off `_settings_layout`).
- Ruff + pyright clean; full suite green; new drawer tests included.

## Final task: Finalize and close worktree
- Rebase `origin/main` into the worktree branch (Step 5)
- Run `/finalize` (open PR — do not pass `--merge`)
- On success, `/start` removes the worktree (Step 7)
