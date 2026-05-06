# Heredoc-Python Audit — Issue #13 Phase 1

> **Status (2026-05-07): RESOLVED.** All 20 heredocs cataloged here have been
> replaced. See PRs #19 (v0.5.0-rc2 — Phase 2B), #20 (v0.5.0-rc3 — Phase 2C),
> and the v0.5.0 final PR (Phase 2D). The drift-prevention test at
> `tests/test_skill_prose_no_heredoc_python.py` now enforces zero heredocs in
> `skills/**/SKILL.md`. This document is retained as a historical artifact.

Generated: 2026-05-06  
Branch: `fix/issue-13-heredoc-python`  
Auditor: Claude Sonnet (audit-only, no code changes)

---

## Summary

- **Total heredoc occurrences**: 20 (`python3 - <<'PY'` blocks)
- **`python3 -c` one-liners**: 3 (2 trivial, 1 candidate)
- **Skill files affected**: 2 (`skills/vision/SKILL.md`, `skills/implement/SKILL.md`)
- **Category distribution**: (a) 4 · (b) 12 · (c) 4
- **Estimated total scope**: ~320 LOC heredoc body eliminated; ~180 LOC new bin CLI surface
- **Recommended phase-2 PR count**: 3 (one per category, or vision/implement split + new helpers)

All 20 heredocs use the `<<'PY'` quoted form (no `$`-interpolation; tabs not stripped). No `<<PY` unquoted or `<<-PY` strip-tab variants found.

---

## Occurrences

### 1. `skills/vision/SKILL.md:41-52` — List available spec/skill templates

- **Category**: (b)
- **Body length**: 10 lines
- **Heredoc style**: `<<'PY'`
- **What it does**: Calls `templates.list_templates()` and prints a `TEMPLATES_AVAILABLE: N` summary with up to 10 template names/kinds.
- **Existing test coverage**: Yes — `tests/test_templates.py` covers `list_templates()` directly; the heredoc body is not tested.
- **Proposed replacement**: Add `--list` flag to a new `bin/templates.py` CLI entry point: `python3 bin/templates.py --list --limit 10`. Stdout: `TEMPLATES_AVAILABLE: N\n  <kind>: <name>\n...`
- **Leverage flag**: low — pure read, no path construction, failure is a no-op (empty list).

---

### 2. `skills/vision/SKILL.md:70-84` — Initialize or resume walker state

- **Category**: (b)
- **Body length**: 13 lines
- **Heredoc style**: `<<'PY'`
- **What it does**: Loads `state/.walk.json` via `walker.load`; if missing, calls `walker.init_walk(spec_intent=..., spec_draft_path=...)` and persists. Prints `WALK: N rounds, M pending, stop=...`.
- **Existing test coverage**: Yes — `tests/test_walker.py` tests `init_walk`, `load`, `persist` extensively. Heredoc body not tested.
- **Proposed replacement**: Add CLI to `bin/walker.py`: `python3 bin/walker.py init-or-resume --intent "<text>" --draft "specs/<slug>.spec.md.draft"`. Stdout: `WALK: N rounds, M pending, stop=<reason>`.
- **Leverage flag**: **high** — constructs `spec_draft_path` from a slug substitution inline; slug errors produce wrong paths silently. Any path drift here produces a stale `state/.walk.json` pointing at the wrong draft.

---

### 3. `skills/vision/SKILL.md:113-128` — Tier-3 yield-delta check during walk loop

- **Category**: (b)
- **Body length**: 14 lines
- **Heredoc style**: `<<'PY'` (indented with 3 spaces — the `PY` delimiter is `   PY`)
- **What it does**: Loads walk state, calls `spec_evaluator.evaluate(draft_path, config_path, bundle_persist_dir)`, counts T3 findings, appends to `yield_history`, re-persists walk. Prints `YIELD: N new T3 findings...`.
- **Existing test coverage**: No direct test; `test_spec_evaluator.py` covers `evaluate()` but not this orchestration path.
- **Proposed replacement**: Add `python3 bin/walker.py yield-check --draft "<draft-path>"` — calls evaluate internally, updates yield_history, prints YIELD line. Consumes config from `~/.spectre/reviewer.toml` by default.
- **Leverage flag**: medium — stale draft path substitution is a risk; the indented-PY delimiter style is the most fragile heredoc form (leading spaces in delimiter confuse some shells).

---

### 4. `skills/vision/SKILL.md:177-184` — Setup wizard provision

- **Category**: (b)
- **Body length**: 6 lines
- **Heredoc style**: `<<'PY'`
- **What it does**: Calls `setup_wizard.config_path_default()` then `setup_wizard.maybe_provision(target)`, prints `WIZARD: <result> (<target>)`.
- **Existing test coverage**: Yes — `tests/test_setup_wizard.py`.
- **Proposed replacement**: `setup_wizard.py` already has functions; just needs a CLI entry: `python3 bin/setup_wizard.py provision`. Stdout: `WIZARD: <result> (<path>)`. This is the smallest possible (b) replacement — 6 lines → 1 line.
- **Leverage flag**: **high** — `maybe_provision` detects API keys; if the heredoc body drifts from the actual wizard signature (e.g. new `SPECTRE_SECRETS_FILE` param added), the skill silently uses the old call signature. This is the pattern that caused the v0.4.2.2 `FileNotFoundError` class of bug.

---

### 5. `skills/vision/SKILL.md:194-215` — Pre-lock spec evaluator (§6.4)

- **Category**: (b)
- **Body length**: 20 lines
- **Heredoc style**: `<<'PY'`
- **What it does**: Calls `spec_evaluator.evaluate(Path("specs/<slug>.spec.md.draft"), config_path, bundle_persist_dir=Path("state"))`, serializes findings to JSON, prints findings list + `TIERS_RUN` + `MAX_SEVERITY`.
- **Existing test coverage**: Yes — `tests/test_spec_evaluator.py`, `tests/test_bundle_handoff_integration.py`.
- **Proposed replacement**: `python3 bin/spec_evaluator.py evaluate --draft "specs/<slug>.spec.md.draft" --config ~/.spectre/reviewer.toml --bundle-dir state`. Stdout: JSON findings + TIERS_RUN + MAX_SEVERITY lines. `spec_evaluator.py` has no `__main__` today; needs one added.
- **Leverage flag**: **high** — constructs `Path("specs/<slug>.spec.md.draft")` inline with slug substituted by the agent. Path construction drift is the #1 sidecar-path bug class from #12 P3. If the slug is wrong, the evaluator silently evaluates the wrong file and writes a sidecar keyed to the wrong hash.

---

### 6. `skills/vision/SKILL.md:270-283` — Write ADR for a spec decision

- **Category**: (b)
- **Body length**: 12 lines
- **Heredoc style**: `<<'PY'`
- **What it does**: Calls `adr.write_adr(Path("decisions"), title, date, body, supersedes)`, prints `ADR: <path>`.
- **Existing test coverage**: Yes — `tests/test_adr.py`.
- **Proposed replacement**: `python3 bin/adr.py write --dir decisions --title "<title>" --date "<ISO>" --body "<body>" [--supersedes NNNN]`. Stdout: `ADR: <path>`. `adr.py` has no `__main__`; needs one.
- **Leverage flag**: low — pure write, no path drift risk beyond the hardcoded `decisions/` dir.

---

### 7. `skills/vision/SKILL.md:291-301` — Update graph for ADR supersedes

- **Category**: (b)
- **Body length**: 9 lines
- **Heredoc style**: `<<'PY'`
- **What it does**: Calls `adr.update_graph_for_supersedes(Path("specs/.graph.md"), new_adr_id, old_adr_id)`. No-op when nodes absent.
- **Existing test coverage**: Yes — `tests/test_adr.py` and `tests/test_graph.py`.
- **Proposed replacement**: `python3 bin/adr.py update-graph --graph specs/.graph.md --new adr-NNNN --old adr-MMMM`. Can share the same `__main__` entry added for occurrence 6.
- **Leverage flag**: low — no path construction; hardcoded `specs/.graph.md`.

---

### 8. `skills/vision/SKILL.md:311-334` — Resource node inference from eval bundle

- **Category**: (c)
- **Body length**: 22 lines
- **Heredoc style**: `<<'PY'`
- **What it does**: Reads `specs/<slug>.spec.md.draft`, SHA-256s it, calls `spec_evaluator.load_persisted_bundle(Path("state/.eval-bundle.json"), draft_sha256, draft_path)` — falling back to `build_bundle(draft)` on mismatch — then iterates `bundle.preview_resources` and prints each resource.
- **Existing test coverage**: Partial — `tests/test_bundle_handoff_integration.py` covers bundle load/save; no test for this exact read-print path.
- **Proposed replacement**: New helper `bin/bundle_resources.py`: `python3 bin/bundle_resources.py list-resources --draft "specs/<slug>.spec.md.draft" --bundle state/.eval-bundle.json`. Stdout: one `<id> (<kind>:<identifier>)` line per resource. Falls back to rebuild if bundle mismatches. Exits 0 always; no resources → empty stdout.
- **Leverage flag**: **high** — computes SHA-256 of the draft inline; if the slug substitution is wrong, the bundle lookup produces a `BUNDLE_MISMATCH` every time and silently rebuilds (masking the path error). This is the exact sidecar-path drift pattern from #12 P3.

---

### 9. `skills/vision/SKILL.md:387-408` — Write eval sidecar (§6.7 step 4)

- **Category**: (b)
- **Body length**: 20 lines
- **Heredoc style**: `<<'PY'` (indented 3 spaces)
- **What it does**: Calls `eval_metadata.write_sidecar(spec, evaluator_version, tiers_run, findings, dismissals, config_path, config_hash, deepseek_model_version, policy_hash)` — where all values come from `result.sidecar_payload` captured in §6.4. The draft path comment ("already renamed to .spec.md by step 1") is a known trap: the variable is still named `draft` but points at `.spec.md`.
- **Existing test coverage**: Yes — `tests/test_eval_metadata.py`, `tests/test_vision_sidecar_path_consistency.py`.
- **Proposed replacement**: `python3 bin/eval_metadata.py write-sidecar --spec "specs/<slug>.spec.md" --bundle state/.eval-bundle.json`. Reads `sidecar_payload` from the persisted bundle rather than requiring the caller to re-thread all individual fields. `eval_metadata.py` has no `__main__`; needs one.
- **Leverage flag**: **high** — the misleading `draft` variable pointing at `.spec.md` is a latent path confusion bug. The `sidecar_path_for(spec)` call is inside `write_sidecar` but the caller constructs the `spec` Path inline with slug substitution. Policy hash drift between what §6.4 computed and what §6.7 writes is the exact bug class caught by `test_vision_sidecar_path_consistency.py`.

---

### 10. `skills/vision/SKILL.md:420-433` — Append CDLC ledger `generate` transition

- **Category**: (b)
- **Body length**: 12 lines
- **Heredoc style**: `<<'PY'`
- **What it does**: Calls `cdlc_ledger.append_transition(kind="generate", payload={spec_slug, round_count, tiers_run}, project_path=pathlib.Path.cwd())`.
- **Existing test coverage**: Yes — `tests/test_cdlc_ledger.py`.
- **Proposed replacement**: `python3 bin/cdlc_ledger.py append --kind generate --spec-slug "<slug>" --round-count N --tiers-run "<tiers>"`. `cdlc_ledger.py` has no `__main__`; needs one. Shared entry point for all ledger appends (occurrences 10, 13, 20).
- **Leverage flag**: medium — ledger writes are non-blocking; a failure doesn't corrupt state. Risk is slug drift producing wrong metadata in the ledger.

---

### 11. `skills/implement/SKILL.md:103-136` — Persistence-Tier classifier (§3.5)

- **Category**: (b)
- **Body length**: 33 lines
- **Heredoc style**: `<<'PY'`
- **What it does**: Calls `tier.classify(current_action)`, parses §8.1 locked paths via `coverage_gate.parse_81_block`, calls `tier.should_halt(t, na, action, reasons, spec_locked_paths)`, prints `TIER:`, `reason:`, `NEVER_AUTONOMOUS:`, `HALT:` lines.
- **Existing test coverage**: Yes — `tests/test_tier.py`, `tests/test_coverage_gate.py`. Heredoc body not tested end-to-end.
- **Proposed replacement**: `python3 bin/tier.py classify --action "<action>" --spec "specs/<active-spec>.spec.md"`. Stdout: `TIER: <t>`, `reason: <r>` per reason, `NEVER_AUTONOMOUS: <na>` if present, `HALT: <bool>`. `tier.py` has no `__main__`; needs one. This is the longest heredoc in the file — 33 lines.
- **Leverage flag**: **high** — constructs `active_spec_path = pathlib.Path("specs") / "<active spec name>.spec.md"` from an agent-substituted placeholder. Wrong spec name → `spec_locked_paths` is empty → locked-path halts silently bypass. This is structurally identical to the sidecar-path drift pattern.

---

### 12. `skills/implement/SKILL.md:161-178` — Record tier-gate observation

- **Category**: (b)
- **Body length**: 16 lines
- **Heredoc style**: `<<'PY'`
- **What it does**: Calls `observations.fingerprint_halt(action, classifier_label)` then `observations.record_halt(kind, fingerprint, project_path, spec_slug, action, classifier_label)`, prints `OBSERVED: <fp[:12]}...`.
- **Existing test coverage**: Yes — `tests/test_observations.py`.
- **Proposed replacement**: `python3 bin/observations.py record-halt --action "<action>" --label "<label>" --spec-slug "<slug>"`. Stdout: `OBSERVED: <fp[:12]>...`. `observations.py` has no `__main__`; needs one.
- **Leverage flag**: medium — observations are advisory (personal-rules keying). Fingerprint drift between this call and a future personal-rules lookup would mean halts recur even after adoption; annoying but not data-corrupting.

---

### 13. `skills/implement/SKILL.md:186-200` — Append CDLC ledger `halt` transition

- **Category**: (b)
- **Body length**: 13 lines
- **Heredoc style**: `<<'PY'`
- **What it does**: Calls `cdlc_ledger.append_transition(kind="halt", payload={fingerprint, label, action, user_answer}, project_path=pathlib.Path.cwd())`.
- **Existing test coverage**: Yes — `tests/test_cdlc_ledger.py`.
- **Proposed replacement**: `python3 bin/cdlc_ledger.py append --kind halt --fingerprint "<fp>" --label "<label>" --action "<action>" --user-answer "<yes|halt|skip>"`. Shares `__main__` entry with occurrence 10.
- **Leverage flag**: low — ledger writes non-blocking; no path construction.

---

### 14. `skills/implement/SKILL.md:212-232` — Persist `pending_adoption_prompt` to scratchpad

- **Category**: (b)
- **Body length**: 19 lines
- **Heredoc style**: `<<'PY'`
- **What it does**: Loads `state/scratchpad.json` via `_scratchpad.load`, sets `tracks[track]["pending_adoption_prompt"]` = structured dict, calls `sp.atomic_write`. Prints `PENDING_ADOPTION_PROMPT_PERSISTED: <fp[:12]>...`.
- **Existing test coverage**: Yes — `tests/test_scratchpad.py`.
- **Proposed replacement**: `python3 bin/_scratchpad.py set-pending-adoption --track "<track>" --fingerprint "<fp>" --label "<label>" --action "<action>"`. Stdout: `PENDING_ADOPTION_PROMPT_PERSISTED: <fp[:12]>...`. `_scratchpad.py` has no `__main__`; needs one.
- **Leverage flag**: **high** — uses `__import__("datetime")` inline to get UTC timestamp — a known fragility pattern; wrong timezone or import failure silently corrupts the timestamp field. Also: this block is the durability mechanism for §3.5b; if it fails, the adoption prompt is lost across a session boundary.

---

### 15. `skills/implement/SKILL.md:242-257` — Read `pending_adoption_prompt` from scratchpad

- **Category**: (b)
- **Body length**: 14 lines
- **Heredoc style**: `<<'PY'`
- **What it does**: Loads scratchpad, reads `tracks[track]["pending_adoption_prompt"]`, prints `NO_PENDING_PROMPT` or `PROMPT: fp=... label=...`.
- **Existing test coverage**: Yes — `tests/test_scratchpad.py`.
- **Proposed replacement**: `python3 bin/_scratchpad.py get-pending-adoption --track "<track>"`. Stdout: `NO_PENDING_PROMPT` or `PROMPT: fp=<fp[:12]>... label=<label>`. Shares `__main__` entry with occurrence 14.
- **Leverage flag**: low — pure read; no path construction; failure is safe (no prompt fires).

---

### 16. `skills/implement/SKILL.md:263-277` — Clear `pending_adoption_prompt` from scratchpad

- **Category**: (b)
- **Body length**: 13 lines
- **Heredoc style**: `<<'PY'`
- **What it does**: Loads scratchpad, sets `tracks[track]["pending_adoption_prompt"] = None`, atomic writes. Prints `PROMPT_CLEARED`.
- **Existing test coverage**: Yes — `tests/test_scratchpad.py`.
- **Proposed replacement**: `python3 bin/_scratchpad.py clear-pending-adoption --track "<track>"`. Stdout: `PROMPT_CLEARED`. Shares `__main__` entry with occurrences 14 and 15.
- **Leverage flag**: low — pure write; no path construction; idempotent (setting None twice is safe).

---

### 17. `skills/implement/SKILL.md:296-314` — Append personal-rules adoption

- **Category**: (b)
- **Body length**: 17 lines
- **Heredoc style**: `<<'PY'`
- **What it does**: Checks `personal_rules.adoption_count_this_session_persistent() >= DEFAULT_BRAKE_THRESHOLD`; if over threshold prints BRAKE and exits; otherwise calls `personal_rules.append_adoption(classifier_label, fingerprint, reason)` and prints `ADOPTED. (N/3 this session)`.
- **Existing test coverage**: Yes — `tests/test_personal_rules.py`.
- **Proposed replacement**: `python3 bin/personal_rules.py adopt --label "<label>" --fingerprint "<fp>" --reason "<reason>"`. Stdout: `BRAKE: ...` or `ADOPTED. (N/3 this session)`. `personal_rules.py` has no `__main__`; needs one.
- **Leverage flag**: medium — brake check uses `_default_scratchpad_path()` which assumes cwd; if cwd is wrong the counter is read from the wrong file and the brake never fires. This is the exact session-counter drift bug documented in the v0.4.1 fix notes.

---

### 18. `skills/implement/SKILL.md:330-342` — Resource lock acquire (§3.6)

- **Category**: (b)
- **Body length**: 11 lines
- **Heredoc style**: `<<'PY'`
- **What it does**: Calls `track.ensure_supervisor_running(Path("."))`, then for each resource ID calls `track.acquire(Path("."), track_name, resource_id)` — prints `QUEUED:` or `ACQUIRED:` per resource, exits 1 on queue.
- **Existing test coverage**: Yes — `tests/test_track.py`.
- **Proposed replacement**: `python3 bin/track.py acquire --track "<track>" --resources "<rid1>,<rid2>"`. Stdout: `ACQUIRED: <rid>` or `QUEUED: <rid> (position N)`. Exit 1 if any queued. `track.py` has no `__main__`; needs one.
- **Leverage flag**: low — no path construction; supervisor path is derived from `Path(".")`.

---

### 19. `skills/implement/SKILL.md:388-413` — State Auditor (§5.5)

- **Category**: (c)
- **Body length**: 25 lines
- **Heredoc style**: `<<'PY'`
- **What it does**: Loads `state/scratchpad.json` via raw `json.load` (not `_scratchpad.load`), reads `paths_touched`, calls `auditor.audit_action(current_action, paths_touched, properties)`, writes audit results back to `state/scratchpad.json` via raw `json.dump` (not `_scratchpad.atomic_write`), prints `AUDIT: N checks, passed=True/False` + failures.
- **Existing test coverage**: Yes — `tests/test_auditor.py`.
- **Proposed replacement**: New helper `bin/auditor_cli.py` (or add `__main__` to `auditor.py`): `python3 bin/auditor.py run --action "<action>" --track "<track>"`. Reads scratchpad via `_scratchpad.load`, writes via `_scratchpad.atomic_write` (fixes the non-atomic raw write). Stdout: `AUDIT: N checks, passed=<bool>` + failure lines.
- **Leverage flag**: **high** — uses raw `json.dump` instead of `_scratchpad.atomic_write`, which is a data-corruption risk if Claude Code is interrupted mid-write. Also reads `sp.get("paths_touched", [])` directly from the v2 scratchpad root (but v2 schema stores `paths_touched` under `tracks.<track>.paths_touched`), so on v2 scratchpads this silently reads an empty list every time.

---

### 20. `skills/implement/SKILL.md:427-440` — Append CDLC ledger `implement` transition

- **Category**: (b)
- **Body length**: 12 lines
- **Heredoc style**: `<<'PY'`
- **What it does**: Calls `cdlc_ledger.append_transition(kind="implement", payload={step, spec_slug, action}, project_path=pathlib.Path.cwd())`.
- **Existing test coverage**: Yes — `tests/test_cdlc_ledger.py`.
- **Proposed replacement**: `python3 bin/cdlc_ledger.py append --kind implement --step N --spec-slug "<slug>" --action "<action>"`. Shares `__main__` entry with occurrences 10 and 13.
- **Leverage flag**: low — ledger writes non-blocking; no path construction.

---

### 21. `skills/implement/SKILL.md:503-510` — Resource lock release (§6.7)

- **Category**: (b)
- **Body length**: 7 lines
- **Heredoc style**: `<<'PY'`
- **What it does**: For each resource ID calls `track.release(Path("."), track_name, resource_id)`. No output.
- **Existing test coverage**: Yes — `tests/test_track.py`.
- **Proposed replacement**: `python3 bin/track.py release --track "<track>" --resources "<rid1>,<rid2>"`. Shares `__main__` entry with occurrence 18.
- **Leverage flag**: low — no path construction; release is idempotent.

---

### 22. `skills/implement/SKILL.md:558-562` — Write ADR for project finding (§7.5)

- **Category**: (b)
- **Body length**: 3 lines
- **Heredoc style**: `<<'PY'`
- **What it does**: Calls `adr.write_adr(slug, title, body)`. This is the shortest heredoc in the codebase — 3 lines of actual logic.
- **Existing test coverage**: Yes — `tests/test_adr.py`.
- **Proposed replacement**: `python3 bin/adr.py write --slug "<slug>" --title "<title>" --body "<body>"`. Shares `__main__` entry with occurrence 6.
- **Leverage flag**: low — only fires on Path B retry success (rare); no path drift risk.

---

## `python3 -c` one-liners (candidates)

### C1. `skills/vision/SKILL.md:33` — Print first 50 local symbols

```python
python3 -c "import json; d=json.load(open('state/local-symbols.json')); print(json.dumps(d[:50], indent=2))"
```

- **Assessment**: (a) — this is a trivial single-file read + pretty-print. Replace with `Read state/local-symbols.json` (native harness tool), then the agent reads the first 50 entries from the parsed content. No heredoc risk; no shell injection risk in the current form. **Recommend keeping as-is** or replacing with native `Read` — not worth a bin helper.

### C2. `skills/vision/SKILL.md:253` (prose reference only)

```python
python3 -c "from bin import findings as F; ..."
```

- **Assessment**: Prose description only (inside a backtick example, not an executable block). Not a live invocation. No action needed.

### C3. `skills/vision/SKILL.md:414` — Clear eval bundle

```python
python3 -c "from bin import spec_evaluator; from pathlib import Path; spec_evaluator.clear_bundle(Path('state/.eval-bundle.json'))"
```

- **Assessment**: (b) — 1-line call to `spec_evaluator.clear_bundle`. Add `--clear-bundle` flag to the `spec_evaluator.py` CLI proposed for occurrence 5: `python3 bin/spec_evaluator.py clear-bundle --bundle state/.eval-bundle.json`. Current form is safe but would benefit from the shared CLI for consistency.

---

## High-leverage targets (recommended first phase-2 PR)

These 5 occurrences share the sidecar-path-construction and atomic-write bug patterns that produced the v0.4.2.2 live failure:

1. **#5 — `vision/SKILL.md:194-215` (§6.4 spec evaluator)** — constructs `Path("specs/<slug>.spec.md.draft")` inline; wrong slug → evaluates wrong file silently. The `policy_hash` written here must match what §6.7 sidecar writes — drift between these two calls is what `test_vision_sidecar_path_consistency.py` guards but cannot fully prevent in prose.

2. **#9 — `vision/SKILL.md:387-408` (§6.7 write sidecar)** — the misleading `draft` variable pointing at `.spec.md`, constructs `Path` inline. Policy hash drift is the specific bug class; the existing regression test exists because this already bit once.

3. **#8 — `vision/SKILL.md:311-334` (resource node inference)** — SHA-256 computed inline from agent-substituted path; bundle mismatch silently rebuilds masking path errors. No `_scratchpad.atomic_write` equivalent — plain bundle read.

4. **#11 — `implement/SKILL.md:103-136` (tier classifier, §3.5)** — largest heredoc (33 lines); constructs `active_spec_path` inline; wrong spec name → empty `spec_locked_paths` → locked-path halts silently bypass. Hot path (runs on every `/implement` invocation).

5. **#19 — `implement/SKILL.md:388-413` (State Auditor, §5.5)** — raw `json.dump` instead of `_scratchpad.atomic_write` (corruption risk on interrupt); reads `paths_touched` from wrong schema level (v2 scratchpad root vs. `tracks.<track>.paths_touched`). Silent wrong-level read means `auditor.audit_action` always receives `[]` for `paths_touched` on v2 scratchpads — the auditor has been silently no-op for every post-v2-migration invocation.

---

## Phase-2 PR breakdown proposal

### PR 1 — Category (a) + `python3 -c` cleanup (estimated: ~30 LOC changed)

- Replace `vision/SKILL.md:33` one-liner with native `Read state/local-symbols.json` tool call.
- Replace `vision/SKILL.md:414` clear-bundle one-liner with `spec_evaluator.py --clear-bundle` once PR 2 lands (dependency).
- Scope: 1 skill file, 2 prose changes.

### PR 2 — High-leverage category (b) path-construction heredocs in vision/ (estimated: ~120 LOC heredoc removed, ~80 LOC bin CLI surface added)

Targets: occurrences 5, 8, 9, 10, 4 (wizard), 2 (walker init).

New bin CLI entry points needed:
- `bin/spec_evaluator.py` — add `__main__` with `evaluate` + `clear-bundle` subcommands.
- `bin/eval_metadata.py` — add `__main__` with `write-sidecar` subcommand.
- `bin/bundle_resources.py` — new file (occurrence 8 has no existing home).
- `bin/walker.py` — add `__main__` with `init-or-resume` subcommand.
- `bin/cdlc_ledger.py` — add `__main__` with `append` subcommand (shared across occurrences 10, 13, 20).
- `bin/setup_wizard.py` — add `__main__` with `provision` subcommand.

### PR 3 — Remaining category (b) heredocs in implement/ + category (c) (estimated: ~170 LOC heredoc removed, ~100 LOC bin CLI + tests added)

Targets: occurrences 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22.

New bin CLI entry points needed:
- `bin/tier.py` — add `__main__` with `classify` subcommand.
- `bin/observations.py` — add `__main__` with `record-halt` subcommand.
- `bin/_scratchpad.py` — add `__main__` with `set-pending-adoption`, `get-pending-adoption`, `clear-pending-adoption` subcommands.
- `bin/personal_rules.py` — add `__main__` with `adopt` subcommand.
- `bin/track.py` — add `__main__` with `acquire` + `release` subcommands.
- `bin/auditor.py` — add `__main__` with `run` subcommand (fixes raw-json-dump + wrong schema level — category (c) fix bundled here).
- `bin/adr.py` — add `__main__` with `write` + `update-graph` subcommands.

New bin file needed:
- `bin/bundle_resources.py` — occurrence 8 (category c, no existing home). ~25 LOC + tests.

Unit tests for each new `__main__` entry point: ~8 new test files or extensions, ~60 LOC.

---

## Total scope estimate

| Category | Occurrences | Heredoc LOC removed | New bin LOC | New test LOC |
|----------|-------------|---------------------|-------------|--------------|
| (a)      | 4 (incl. -c)| ~15                 | 0           | 0            |
| (b)      | 17          | ~285                | ~150        | ~50          |
| (c)      | 2 (occ 8, 19)| ~47               | ~60         | ~30          |
| **Total**| **23**      | **~347**            | **~210**    | **~80**      |

Full scope: ~290 LOC net change across 2 skill files + ~10 bin files touched/created. Splits cleanly into 3 PRs each under 150 LOC. Recommend the PR 2 / PR 3 split (not a single PR) because the `spec_evaluator` + `eval_metadata` CLI surface has the most test risk and deserves its own review.
