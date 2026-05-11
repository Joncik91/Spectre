# Changelog

All notable changes to the Spectre plugin.

## v0.7.1 — 2026-05-11

**Fixed: Tier 1 `self-cycle-produces` check (#42).**

A step whose `action:` consumes a path declared in its OWN `produces:` — with no earlier step producing it — now emits a `self-cycle-produces` block finding. Caught real-world in `test-spectrere`'s LLM-routing-gateway spec where step 3 referenced `_manifest.toml` as both input (`--manifest …`) and output (`produces: file:…/_manifest.toml`).

Detection: `shlex`-tokenized `action:` strings, suffix allowlist (`.toml/.json/.sqlite/.onnx/.skops/.yaml/.yml/.md/.py/.txt/.db/.sqlite3`), input-option allowlist (`--manifest/--config/--from/--input/--source/--file/--from-file`, both `--opt value` and `--opt=value`). Subtracts write-destinations from `_action_authored_path()` (cp/install/tee/redirect targets). Suffix-matches relative action paths against absolute `produces:` paths. Dedupes per-step.

Tests: +12 new (1331 → 1343). Coverage: minimal case, severity, prior-producer exemption, multi-path partial, gateway repro, directory-target guard, joined `--opt=value`, two-opts-one-path dedup.

## v0.7.0 — 2026-05-08

**Added: cognitive-substrate contract (§8.2) + Tier 1 taint flow + adversarial-pathway rubric.**

Spec evaluator now checks the cognitive-substrate contract (§8.2) on top of the technical contract (§8.1) — receiver fingerprint, trust boundaries, contextual binding, provenance, UX contract, possibility-walk, judgment-cap, ROI. Driven by vault concepts in `concepts/context-as-cognitive-substrate.md` (with adversarial review by Copilot/GPT-5.4).

### Added — Substrate wizard (`bin/substrate_wizard.py`)

- 4 mandatory questions fire at /vision Step 0.5: receiver fingerprint, trust profile, contextual binding, provenance.
- Cache at `~/.spectre/substrate-cache/<author-spec-hash>.json`; author-spec hash strips the auto-injected §8.2 block so wizard injection doesn't invalidate its own cache.
- Schema-versioned (`SUBSTRATE_WIZARD_VERSION = "0.7"`); mismatch → re-prompt.
- CLI: `PYTHONPATH="${CLAUDE_PLUGIN_ROOT}" python3 -m bin.substrate_wizard run --author-spec-hash <hex64>`.

### Added — Tier 1 §8.2 + taint flow (`bin/substrate_ast.py`)

- Required-field block checks: `receiver-fingerprint`, `trust-profile`, `contextual-binding`, `provenance`, `ux-contract` non-empty.
- Warn-severity informational checks: `assumptions-killed` empty (block when steps>3), `requires-situated-judgment` claim cap = `max(1, floor(0.3 × n_steps))`, `roi-budget`.
- **Per-step trust annotations** mandatory when `trust-profile` includes `untrusted-input` or `handles-secrets`. Missing annotation → block `trust-annotation-required`. Malformed value → warn + fail-closed default.
- **Taint flow** with 4 sink categories: filesystem-write (`mutates:`), shell-eval (`bash -c`, `python -c`, `node -e`, `eval`, `$(...)`), SQL/template (`INSERT|UPDATE|REPLACE|DELETE FROM|jinja2|template_render|format_map`), network-egress (`curl|wget|httpie|http POST|PUT|--data|--data-binary|--data-urlencode|--data-raw|--post-file=|--upload-file|-d|-F|-T` with body from a tainted produces). `sanitizes:` clears taint on the OUTPUT, NOT the source. Source-step actions are sink-checked even when produces is empty.

### Added — Tier 3 adversarial-pathway rubric (`bin/llm_judge.py`)

- System prompt extended (~120 tokens) with adversarial-pathway rubric: for every step touching untrusted source, name the exploit class one move ahead.
- New contradiction tuple kind `adversarial-pathway` (block-severity by default; CoT faithfulness pass demotes unfaithful citations).

### Added — Envelope substrate binding

- `bin/handoff_envelope.py` schema gains `substrate_sha256` field (SHA-256 over §8.2 bytes; empty string for pre-v0.7 specs). Included in the integrity-hash domain alongside `spec_sha256`/`sidecar_sha256`.
- `bin/handoff_validator.py` Tier 0 verifies `substrate_sha256` matches live §8.2 bytes; tampering → block `envelope-tampered:substrate-bytes-changed:`. Pre-v0.7 envelope (field absent or empty) → warn `envelope-missing-substrate`, /implement proceeds.

### Added — Sidecar substrate_resolution

- `<slug>.eval.json` gains `substrate_resolution` dict: `receiver_hash`, `trust_profile`, `taint_outcome`, `provenance_chain`, `axis_completeness`. Wired through `spec_evaluator` so real /vision runs populate the field.

### Added — Skill prose + template

- `skills/vision/SKILL.md` Step 0.5 wires the wizard.
- `specs/template.spec.md` documents §8.2 + per-step trust annotations.

### Bumped

- `EVALUATOR_VERSION = "0.7.0"`.
- `marketplace.json` 0.6.2 → 0.7.0.

### Tests

- 38+ new test functions across `test_substrate_wizard.py`, `test_substrate_ast.py`, `test_llm_judge_adversarial.py`, `test_handoff_envelope_substrate.py`. Baseline 1280 → 1331+.

### Vault sources

- `/root/claude-obsidian/concepts/context-as-cognitive-substrate.md` (informing essay).
- `/root/claude-obsidian/concepts/heidegger-predicted-gen-ai-comparison.md` (cross-essay engineering convergence).

## v0.6.2 — 2026-05-08

**Fixed: contract-shadow false positive (#36) and Tier 3 silent-fail trio (#37).**

### Fixed — Contract-shadow false positive on `from X import Y` (#36)

- **`bin/spec_ast.py`** — `_PYTHON_IMPORT_ALT_RE` previously matched `import is_blocked` inside `from foo.bar import is_blocked`, capturing the imported SYMBOL as a module name. Since `is_blocked` is not declared anywhere, the heuristic shadow couldn't suppress it. Fix: skip ALT-regex spans that overlap with `from X import` spans already covered by `_PYTHON_IMPORT_RE`.
- **`bin/spec_ast.py`** — Contract resolution + heuristic shadow now match parent prefixes: `package:foo` satisfies `module:foo.bar`; `module:foo.bar` satisfies `module:foo.bar.baz`. Closes the `package:spectre_daemon` does-not-shadow `module:spectre_daemon.blocklist` case from the v0.6.1 retest.
- **`tests/test_spec_ast_v052_gaps.py`** — three regression tests covering symbol-misclassification, parent-package, and parent-module shadow.

### Fixed — Tier 3 silent-fail trio (#37)

- **`bin/setup_wizard.py`** — auto-migration of stale `~/.spectre/reviewer.toml`. Detects v0.5.0-era `model = "deepseek-reasoner"` AND pre-#25 single-`timeout_s` configs, backs the original up to `reviewer.toml.bak-<timestamp>`, rewrites with current defaults (deepseek-v4-flash + chunk/total split timeouts). Preserves the user's `enabled` flag and `api_key_env`. New return code: `"migrated"`.
- **`bin/llm_judge.py`** — distinguishes auth from network errors. HTTP 401/403 now produce `"auth failure (HTTP NNN — check ~/.spectre/secrets.env or DEEPSEEK_API_KEY)"` instead of the generic `"socket-timeout — DeepSeek unreachable"`. HTTP 400 hints model-unavailable; 5xx reads `"provider error"`.
- **`skills/vision/SKILL.md`** — Tier 3 surfacing prominence. Requires a `⚠ Tier 3 unavailable due to auth` banner ABOVE the tier status block when the message contains "auth failure", so credential issues are not buried in the findings list.
- **Tests** — `tests/test_setup_wizard.py` (5 new migration tests), `tests/test_llm_judge.py` (4 new auth/error-class distinction tests), `tests/test_setup_wizard_cli.py` (existing test updated to v0.6.2 schema).

### Bumped

- `EVALUATOR_VERSION = "0.6.2"`
- `marketplace.json` version → 0.6.2

## v0.6.1 — 2026-05-07

**Fixed: skill prose PYTHONPATH ergonomics (issue #30).**

- Fixed: skill prose now consistently prefixes every `python3 -m bin.X` invocation with `PYTHONPATH="${CLAUDE_PLUGIN_ROOT}"` so plugin-internal modules resolve correctly from the user's project cwd. Closes #30.
- Added: PYTHONPATH note section at the top of both `skills/vision/SKILL.md` and `skills/implement/SKILL.md` explaining the prefix requirement.
- Added: `tests/test_skill_pythonpath_consistency.py` — CI sentinel that scans all `skills/**/SKILL.md` bash code blocks and asserts every `python3 -m bin.X` line carries the `PYTHONPATH="${CLAUDE_PLUGIN_ROOT}"` prefix. Catches future regressions.

## v0.6.0 — 2026-05-07

**Vault-informed improvements: handoff envelope (Context Sled with bytewise integrity), walker yield countdown, negative-path enforcement, Tier 3 CoT faithfulness, executor-owned step heading.**

Five vault concept pages mapped onto Spectre weak points after v0.5.2:
- `concepts/context-as-cognitive-substrate.md` (marginal yield, assumption-killing)
- `entities/standardized-handoff-envelope.md`, `entities/context-sled.md`, `entities/handoff-validator.md` (Tier 0 integrity)
- `entities/planner-generator-evaluator-triad.md` (Spectre realization patterns)
- `research/cot-monitorability.md` (Tier 3 faithfulness)
- `random-internet-finds/.../harness-engineering-software-agents.md` (channel selection)

User cut at concept #6 (Agent Security Bench) — out of scope for v0.6.

### Added — Handoff envelope (Context Sled with bytewise integrity)

- **`bin/handoff_envelope.py`** (NEW) — JSON-Schema-validated envelope wrapping vision→implement handoff. Hand-rolled validator (stdlib only). Schema: `protocol_version`, `receiver`, `spec_path`, `sidecar_path`, `policy_hash`, `spec_sha256`, `sidecar_sha256`, `contract_resolution`, `walker_yield_history`, `walker_stop_reason`, `decisions_indexed`, `integrity_hash`, `created_at`. Critical: integrity hash covers actual artifact bytes (spec.md + sidecar.eval.json), not just envelope metadata — closes Gap E from the v0.5.2 essay-followup.
- **`bin/handoff_validator.py`** (NEW) — Tier 0 check `validate_on_implement_start(project_path)`. Distinguishes `envelope-missing` (warn, pre-v0.6 spec), `envelope-tampered` (block, content modified after lock), `envelope-malformed` (block, schema violation). CLI: `python3 -m bin.handoff_validator check --project-path <path>`.
- **`bin/eval_metadata.py`** — `write_envelope_alongside_sidecar()` helper + `write-envelope` CLI subcommand.

### Added — Walker yield countdown + negative-path concern

- **`bin/walker.py`** — `yield_status_line(state)` returning prediction-ready `"YIELD: round N added M new T3 findings; stopping when last K rounds all <T (currently: [a,b,c])"` instead of raw delta. New `negative-path` concern kind + `generate_negative_path_concerns(state, steps)` with idempotency guard.

### Added — Negative-path Tier 1 enforcement

- **`bin/spec_ast.py`** — new optional `negative-paths:` block on each step (list of `{trigger, handler}` dicts). Tier 1 check: warn `missing-negative-path` when `produces:` is non-empty and `negative-paths:` is missing; **block** when `reboot-survival: required` (data-loss hazard). Malformed-only declarations under `reboot-survival: required` also escalate to block (cannot be dodged with a half-broken entry). Case-insensitive `reboot-survival` matching.

### Added — Tier 3 CoT faithfulness check

- **`bin/llm_judge.py`** — single batched cite-and-verify pass after primary contradiction tuples. Block-severity tuples (`missing-producer`, `shallow-ownership`) demoted to warn `tier3-unfaithful-contradiction` if DeepSeek can't cite supporting spec text (case-insensitive substring match). Parse failure → conservative: keep block, append `tier3-faithfulness-malformed` warn. Zero extra API calls when no block tuples exist.

### Changed — Skill prose + spec template

- **`skills/vision/SKILL.md`** Step 6.7 — extends lock with envelope write via `python3 -m bin.eval_metadata write-envelope`.
- **`skills/implement/SKILL.md`** new **Step 0.7 — Tier 0 handoff integrity check** (between Step 0.5 track selection and Step 1 read context). Calls `python3 -m bin.handoff_validator check`. Documents 4 outcomes (envelope-missing warn, envelope-tampered block, no active spec block, schema violation block).
- **`specs/template.spec.md`** — `negative-paths:` documented in §6 with trigger/handler schema, warn/block calibration. v0.6 envelope invariant added to §5 (alongside v0.5.2 venv invariant).

### Tests

- 1109 → 1265 passing (+156 new tests).

### References

- v0.5.2 closure — issue #32, PR #33.
- v0.6.0 design — informed by `/root/claude-obsidian/concepts/context-as-cognitive-substrate.md` and adjacent vault concept pages (no GitHub design issue filed; this was a direct improvement plan).

## v0.5.2 — 2026-05-07

**Closure of the pre-lock evaluator regression surfaced by the v0.5.1 retest. Five gap classes shipped past three tiers in v0.5.1 (`tier 1: PASS (2 warn)`, `tier 2: PASS (0)`, `tier 3: PASS (21 info)`); `/implement auto` then halted five times on bugs the evaluator should have caught. Per Copilot/GPT-5.4 peer review (#32): the fix is deterministic contracts + executor-owned environment + hard gating, NOT prose-inferred graphs.**

### Summary

The v0.5.1 retest of yt-readable surfaced gap classes A (uncreated artifact), B (import-before-install), C (scaffold-without-implementation), D (unparseable Python in verification), E (PEP 668 / venv) — all detectable at lock time with deterministic checks. v0.5.2 closes all five plus reshapes Tier 3 from prose-adversarial-review to JSON contradiction tuples.

### Added

- **`bin/managed_venv.py`** (NEW) — executor-owned Python environment (closes Gap E from #31, design #32):
  - `ensure_venv(project_path)` — creates `state/.venv/` mode 0700 idempotently. HALTs on a stale `pyvenv.cfg` referencing a missing system Python (e.g. after upgrade from 3.13 → 3.14).
  - `pip_install_editable(project_path, target=None)` — editable install into the venv.
  - `normalize_action(action, venv_python)` — regex-based head-token rewriter (anchored after `&&`/`||`/`;`/`|`/`&`). Preserves shell operators byte-identical, preserves heredocs (structural detection, not substring), preserves absolute paths, handles env-var prefixes (`PYTHONPATH=src python3 -m foo`).
  - `persist_venv_python` / `load_venv_python` — per-track scratchpad helpers using v2 schema with v1 fallback.
  - CLI: `python3 -m bin.managed_venv ensure|pip-install-editable|normalize`.
  - Implement skill prose: new §6.0 "Environment policy" + Step 1.5 wires this in before tier classification.
  - Spec template: §5 reframes venv as "Spectre executor invariant" not spec-author obligation.

- **Explicit step contracts** (closes Gap C, design #32, P3):
  - Two new optional fields on each step: `produces:` and `requires:` — list of `<type>:<value>` entries.
  - 8 contract types: `file:<path>`, `package:<name>`, `console-script:<name>`, `route:<METHOD> <path>`, `module:<dotted.name>`, `binary:<name>`, `db-table:<name>`, `db-column:<table>.<col>`.
  - Tier 1 cross-validates `requires:` against prior `produces:`. Mismatch → block-severity `unowned-requirement`.
  - Step with no contracts → warn-severity `missing-contract` (backward compat — existing specs still work).
  - Malformed entries → warn-severity `malformed-contract`, evaluator continues.
  - `.eval.json` sidecar gets a `contract_resolution` block recording which `requires:` resolved to which step's `produces:`.
  - Spec template documents the 8 contract types and lowercase-prefix convention.

- **Tier 1 deterministic gap-closers** (closes Gaps A, C, D from #31, design #32, P1):
  - `verification-syntax-error` (block) — every `python3 -c "<body>"` in actions/verifications is `compile()`-checked at lock time. Catches the v0.5.1 Step 5 bug (multi-statement `for x in y: assert x` doesn't parse).
  - `action-invokes-uncreated-artifact` (block) — actions invoking absolute paths under `mutates:` that no prior step's heredoc/cp/tee/install authored.
  - `unowned-requirement-heuristic` (block) — verifications asserting on curl routes, HTML tags, SQL columns, or Python imports with no prior owner. Curl-route allowlist for universal probes (`/`, `/healthz`, `/health`, `/ready`, `/metrics`, `/ping`, `/status`). Bare `import X` and `from X import Y` both checked anywhere in `-c "..."` body. SQL ownership requires `CREATE TABLE <name>(` anchor (tighter than substring match).
  - P1↔P3 integration: heuristic respects explicit `produces:` declarations — if a step declares `produces: ["package:foo"]`, the import-foo heuristic shadows.

- **Tier 3 contradiction-tuple protocol** (#32, P4):
  - DeepSeek system prompt rewritten to ~540 tokens forcing JSON-only output.
  - 10 contradiction kinds + `unrecognized` fallback: `missing-producer`, `shallow-ownership`, `ambiguous-contract`, `negative-path-omission`, `idempotency-risk`, `migration-on-existing-state`, `partial-failure-window`, `concurrency-race`, `verification-false-positive`.
  - Single API call replaces three-prompt prose loop.
  - Severity mapping: `missing-producer`/`shallow-ownership` → block; `ambiguous-contract`/`partial-failure-window`/`verification-false-positive` → warn; rest → info.
  - `build_step_table()` truncates action/verification summaries to 1000 chars to cap input budget; truncation is annotated so DeepSeek can flag `ambiguous-contract` if needed.
  - Parse-failure resilience: malformed JSON → `tier3-malformed-response` warn, evaluator does not crash.

### Changed

- **`DEEPSEEK_MODEL` default**: `deepseek-reasoner` → `deepseek-v4-flash` (`bin/spec_evaluator.py:53`, `bin/setup_wizard.py:102`). The new structured-input/structured-output Tier 3 protocol is faster and cheaper on v4-flash; reasoner's prose-style output isn't needed for tuple emission.

### Tests

- 121 new tests (988 → 1109 passing).

### References

- Issue #31 — original five gap classes from v0.5.1 retest.
- Issue #32 — v0.5.2 design brief (deterministic contracts + executor-owned env + hard gating, per Copilot/GPT-5.4 peer review).

## v0.5.1 — 2026-05-07

**Patch release from a v0.5.0 end-to-end live test — 5 issues filed, all closed. Net effect: every code path the live test exercised now succeeds without runtime heredoc fallback or schema guessing.**

### Summary

Discovered during a v0.5.0 end-to-end live test that surfaced walker mid-walk mutations still happening via in-process Python calls in skill prose, scratchpad reset still hand-rolling JSON in the /vision lock step, the Tier 1 parser rejecting h3-headed §8.1 blocks and unexpanded brace patterns, and Tier 3 using a single timeout for both per-chunk recv and total wall-clock budget. All five issues closed in this patch.

### Added

- **`bin/walker.py`** — 4 new subcommands (closes #22, #23):
  - `get-state --state-path p [--json]` — full state dump; use in place of schema-discovery dance (#23).
  - `peek-pending --state-path p [--json]` — return next concern body without consuming it (#23).
  - `answer-concern --id <id> --answer <str> --state-path p` — record an answer atomically; replaces `walker.record_answer` in-process call (#22).
  - `append-concern --id <id> --kind <k> --receiver <r> --summary <s> --state-path p` — append a final-pass concern; replaces runtime heredoc mutation of `state/.walk.json` (#22).
  - `stop --reason <author-arbitrated|tier3-yield-converged|max-rounds|per-receiver-exhausted> --state-path p` — set stop reason atomically (#22).
  - `--json` flag on `init-or-resume` (existing subcommand) — structured JSON stdout instead of prose line (#23).
- **`bin/_scratchpad.py`** — 2 new subcommands (closes #26):
  - `ensure-v2 --scratchpad p` — promote v1 scratchpad to v2 schema; no-op if already v2.
  - `reset --active-spec <path> --scratchpad p` — atomic track reset (`step=1`, all counters zeroed) for the active spec; replaces hand-rolled v2 dict Write in `/vision` lock step.

### Fixed

- **Tier 1 parser fragility** (closes #24): `spec_evaluator.parse_81_block` now accepts h2 (`## 8.1`) or h3 (`### 8.1`) for the §8.1 header, expands brace patterns (`{a,b}` → two paths), and strips markdown bold/code markers from path lines before matching. Previously, specs that used h3 or inline backticks in path lists produced false-positive `missing-81-block` findings.
- **Tier 3 timeout split** (closes #25): `bin/llm_judge.py` (`_TierThreeReviewer`) now uses two distinct timeouts — `chunk_timeout_s = 60` (per-recv socket timeout) and `total_timeout_s = 600` (total wall-clock abort). The old `timeout_s` key reads as `chunk_timeout_s` alias for backward compatibility. Wizard (`bin/setup_wizard.py`) writes both keys on new installs.

### Changed

- `skills/vision/SKILL.md` — Step 4 walk loop replaced in-process `walker.next_concern`, `walker.record_answer`, `walker.revise_answer`, `walker.should_stop`, and `state.stop_reason =` mutations with explicit `peek-pending`, `answer-concern`, `get-state`, and `stop` CLI invocations. Step 6.7 scratchpad reset replaced hand-rolled v2 JSON Write with `ensure-v2` + `reset` CLI calls.
- `skills/implement/SKILL.md` — no prose changes this patch (implement prose was already CLI-driven from v0.5.0).

### Tests

988 total (was 928 at v0.5.0; +60 across 5 issues' test suites).

### References

Closes #22, #23, #24, #25, #26.

### Migration

Existing users with `timeout_s = 180` in `~/.spectre/reviewer.toml` keep that value as `chunk_timeout_s` via back-compat alias — no action required. To pick up the new `total_timeout_s = 600` wall-clock budget, either edit `~/.spectre/reviewer.toml` manually to add `total_timeout_s = 600` under `[tier3]`, or `rm ~/.spectre/reviewer.toml` and re-run `/vision` to let the wizard rewrite both keys.

---

## v0.5.0 — 2026-05-07

**Final v0.5.0 release. Phase 2D of issue #13 closes the heredoc-python replacement initiative — every `python3 - <<'PY' ... PY` block in `skills/**/SKILL.md` is now a tested `python3 -m bin.<module> <subcommand>` invocation against a CLI surface, or a native harness tool call. An entire bug class (path drift, hash drift, escape-layer fragility, scratchpad-schema-blind reads) is gone from the prose surface.**

### Summary

v0.5.0 is the cumulative release of the heredoc-python replacement initiative tracked under issue #13. Across three release candidates and one final, twenty heredoc-Python blocks were replaced by tested CLI entry points on `bin/` modules, and the drift-prevention test at `tests/test_skill_prose_no_heredoc_python.py` now enforces zero heredocs anywhere under `skills/**/SKILL.md` as a permanent CI guard. Skill prose now invokes documented, version-controlled CLIs whose schemas are pinned by argparse — slug substitutions, path drift, and inline `Path("specs/<slug>...")` constructions are eliminated by construction.

### Added

CLI entrypoints (`if __name__ == "__main__":`) on the eight `bin/` modules Phase 2D needed (4 vision-flow + 3 implement-flow + 1 cross-flow). All subcommands wrap existing public functions; no new business logic added.

- **`bin/cdlc_ledger.py`** — 2 subcommands:
  - `append --kind <generate|test|lock|implement|halt|adapt> [--project p] (--payload json|--payload-kv KEY=VALUE)` — atomic append to `state/cdlc-ledger.json`. Stdout: `APPENDED: kind=<k>`.
  - `read --project p` — print all transitions as JSON.
- **`bin/observations.py`** — 2 subcommands:
  - `record-halt --action <a> --label <l> [--kind k] [--spec-slug s]` — fingerprint + JSONL append to `~/.spectre/observations.jsonl` + best-effort CDLC ledger halt sidecar. Stdout: `OBSERVED: <fp[:12]>...`.
  - `find-recurrences [--kind k] [--threshold n]` — print recurring fingerprints as JSON.
- **`bin/_scratchpad.py`** — 3 subcommands wrapping atomic state mutations:
  - `set-pending-adoption --scratchpad p --track t --fingerprint fp --label l --action a` — atomic-write `tracks.<track>.pending_adoption_prompt`; auto-promotes v1→v2; stamps `recorded_at` with UTC ISO.
  - `get-pending-adoption [--scratchpad p] [--track t] [--json]` — emit `NO_PENDING_PROMPT` or `PROMPT: fp=<fp[:12]>... label=<l>` (or full prompt as JSON).
  - `clear-pending-adoption [--scratchpad p] [--track t]` — atomic set-to-None; idempotent.
- **`bin/personal_rules.py`** — 2 subcommands:
  - `adopt --label l --fingerprint fp --reason r [--scratchpad p] [--track t]` — sandbox-paradox-brake-aware adoption; emits `ADOPTED. (N/3 this session)` or `BRAKE: ...`. Brake check happens BEFORE TOML write so the v0.4.1 fork-counter bug stays fixed structurally.
  - `session-count [--scratchpad p] [--track t]` — print persistent counter value.
- **`bin/track.py`** — 2 subcommands wrapping the supervisor client:
  - `acquire --project p --track t --resources r1,r2,...` — ensure_supervisor_running + acquire each rid; exits 1 on first QUEUED.
  - `release --project p --track t --resources r1,r2,...` — idempotent release.
- **`bin/adr.py`** — 2 subcommands:
  - `write --dir <decisions> --title <t> --body <b> [--date d] [--supersedes id]` — atomic-write the ADR; date defaults to today's ISO; emits `ADR: <path>`. With `--supersedes`, also flips the old ADR's `status: accepted` → `status: superseded`.
  - `update-graph --graph p --new id --old id` — append a supersedes edge; no-op when the manifest or either node is absent.
- **`bin/templates.py`** — 1 subcommand:
  - `list [--limit N] [--json]` — surface `~/.spectre/templates/{specs,skills}/` content. Default prose: `TEMPLATES_AVAILABLE: N` + up to N `<kind>: <name>` lines.
- **`bin/setup_wizard.py`** — 1 subcommand:
  - `provision [--target p] [--secrets-file p] [--api-key-env name]` — runs `maybe_provision()`; emits `WIZARD: <result> (<target>)`.
- **`bin/walker.py`** — extends existing `__main__` with 1 new subcommand:
  - `yield-check --draft p [--state-path p] [--config p] [--bundle-dir d]` — re-evaluates the draft, counts new T3 findings (excluding `tier3-unavailable`), appends to `yield_history`, re-persists. Skips silently with `YIELD: skipped (...)` on no-state / no-draft / round=0 preconditions.

### Changed

The 18 medium-/low-leverage `python3 - <<'PY' ... PY` heredocs cataloged in the issue #13 audit have all been replaced:

- **`skills/vision/SKILL.md`** — 7 heredocs replaced (§0 templates, §3 walker init/resume, §4 Tier-3 yield-delta, §6.3a setup wizard, §6.5 ADR write + graph supersedes, §6.7 CDLC generate). Heredoc count: 7 → 0. Net LOC reduction: ~58 lines. Also replaced the v0.5.0-rc2 leftover `python3 -c "from bin import spec_evaluator..."` clear-bundle one-liner with the Phase 2A `spec_evaluator clear-bundle` subcommand for prose consistency.
- **`skills/implement/SKILL.md`** — 11 heredocs replaced (§3.5 record-halt + cdlc-halt + persist-pending-adoption-prompt, §3.5b read-pending + clear-pending + adopt branch, §3.6 resource acquire, §6 cdlc-implement, §6.7 resource release, §7.5 project-finding ADR write). Heredoc count: 11 → 0. Net LOC reduction: ~134 lines. The §3.5b "Sandbox-paradox brake" prose paragraph also rewritten to remove the now-stale "each `python3 - <<'PY'` heredoc forks a fresh process" rationale — that warning is no longer applicable, and the new CLI explicitly consults the persistent counter on every call.

Combined with Phase 2B (3 heredocs, vision/SKILL.md) and Phase 2C (2 heredocs, implement/SKILL.md), the cumulative replacement: 20/20 heredocs gone. Heredoc count: 0/0.

### Tests

**928 passing** (was 814 at v0.5.0-rc3 → +114 from Phase 2D's eight new CLI test files, four new walker yield-check tests, and the global drift-prevention guard). New test files:

- `tests/test_cdlc_ledger_cli.py` — 16 tests (append happy path + payload formats + payload-kv + JSON file + stdin + bad input + read empty + read after append + round-trip).
- `tests/test_observations_cli.py` — 15 tests (record-halt happy/persistence/fingerprint determinism/missing-flag + find-recurrences empty/below-threshold/at-threshold).
- `tests/test_scratchpad_cli.py` — 18 tests (set/get/clear with v1→v2 promotion, sibling-track preservation, JSON mode, missing-flag).
- `tests/test_personal_rules_cli.py` — 13 tests (adopt happy + persistent counter bump + brake at threshold + per-track + missing-flag + session-count).
- `tests/test_track_cli.py` — 13 tests (acquire happy + multi-resource + queued exits 1 + release happy + release idempotent + supervisor lifecycle + missing-flag).
- `tests/test_adr_cli.py` — 15 tests (write happy + persisted-fields + supersedes flips status + auto-id + missing-flag + update-graph noop-cases).
- `tests/test_templates_cli.py` — 10 tests (list empty/one-spec/one-skill/limit/JSON/missing-flag).
- `tests/test_setup_wizard_cli.py` — 9 tests (no-key/with-env-key/with-secrets-file/exists/target-output).

`tests/test_walker_cli.py` extended with 4 yield-check tests (no-state-skipped, no-draft-skipped, round-zero-skipped, missing-flag-exits-2).

The drift-prevention test at `tests/test_skill_prose_no_heredoc_python.py` is now load-bearing: per-file ceilings tightened to zero AND a new `test_no_python3_heredoc_anywhere_in_skills` walks the entire `skills/**/SKILL.md` tree. Future heredoc-Python introductions break CI immediately.

Smoke-tested all 18 replacements against `/tmp/spectre-phase2d-test/`: the load-bearing on-disk fields (`pending_adoption_prompt`, CDLC ledger payloads, ADR file contents) are byte-identical to the reference heredoc behavior. The CLI is structurally more careful than the heredoc was — `_scratchpad set-pending-adoption` auto-promotes v1→v2 and preserves unknown v1 fields under `_v1_unknown` (the heredoc silently dropped them).

### Migration

None — the change is purely additive on the CLI surface. End users of `/vision` and `/implement` see no behavior change. Internal-API consumers of `bin/*` Python functions also see no change; only new `__main__` entry points were added.

### References

- Issue #13: https://github.com/Joncik91/Spectre/issues/13 (closed)
- Audit: `docs/superpowers/audits/2026-05-06-issue-13-heredoc-audit.md` — historical artifact (status: RESOLVED)
- Drift-prevention: `tests/test_skill_prose_no_heredoc_python.py`

### v0.5.0 cumulative release notes (rc1 → rc2 → rc3 → final)

The v0.5.0 minor cycle landed in four phases. Each prerelease was tagged and merged independently so the release ledger has a clean per-PR audit trail; this release rolls them up.

- **v0.5.0-rc1 — Phase 2A (PR #18).** Foundational CLI infrastructure. Added `__main__` entry points on `bin/spec_evaluator.py` (`evaluate`, `slug-to-path`, `clear-bundle`), `bin/eval_metadata.py` (`policy-hash`, `sidecar-path`, `write-sidecar`, `sha256`), and the existing `bin/walker.py init-or-resume`. No skill-prose changes; the CLIs shipped first so PR #19 could use them. Closed v0.4.2.6's State Auditor v2-schema-blind read by adding `_scratchpad.get_paths_touched` (v1+v2-aware). Closed issue #12 P3 sidecar-path drift by routing all draft/spec path construction through `slug-to-path`.
- **v0.5.0-rc2 — Phase 2B (PR #19).** High-leverage prose surgery in `skills/vision/SKILL.md` — replaced 3 heredocs (§6.4 evaluator, §6.6 resource node inference, §6.7 sidecar write) using only the Phase 2A CLI surface. Net LOC reduction: ~46 lines.
- **v0.5.0-rc3 — Phase 2C (PR #20).** The remaining 2 high-leverage heredocs in `skills/implement/SKILL.md` (§3.5 Persistence-Tier classifier — the longest heredoc in the repo at 33 LOC, §5.5 State Auditor) replaced with new `bin.tier evaluate-action` and `bin.auditor audit-and-clear` CLI entry points. The auditor CLI's atomic-write also fixed v0.4.2.6's residual `json.dump` corruption-on-interrupt risk.
- **v0.5.0 — Phase 2D (this release).** The final 18 medium-/low-leverage heredocs replaced; 8 new CLI entry points added; drift-prevention tightened to zero heredocs globally. Closes issue #13.

Companion releases shipped on the v0.4 line during the same window:
- **v0.4.2.5 (PR #16).** Issue #12 P2: Tier 3 reviewer prong timeouts + retries (60s timeout per prong, 1 retry on transport errors, surface `tier3-prong-timeout` finding when both prongs fail).
- **v0.4.2.6 (PR #17).** Closed two structural bugs surfaced in v0.5.0-rc1's audit: State Auditor v2-schema-blind `paths_touched` read (silent no-op for every post-v2-migration `/implement` invocation) and `compact.py` v2 schema drift in the SessionStart hydrator. Both were rolled into v0.5.0-rc1's CLI surface as a structural fix.

**Third prerelease toward v0.5.0. Phase 2C of issue #13 (heredoc replacement) — the two high-leverage targets in `skills/implement/SKILL.md` deferred from Phase 2B (because they needed new CLI surface). No behavioral changes to /vision or /implement flow.**

### Added

CLI entrypoints (`if __name__ == "__main__":`) on two `bin/` modules. All subcommands wrap existing public functions; no new business logic added. The `audit-and-clear` orchestration also fixes the §5.5 heredoc's structural bugs (raw `json.dump` write-back, v2-schema-blind `paths_touched` read).

- **`bin/tier.py`** — 3 subcommands:
  - `classify --action <text>` — runs `tier.classify(action)` and prints `TIER: <t>` + one `reason: <r>` line per reason + (if matched) `NEVER_AUTONOMOUS: <label>`.
  - `should-halt --action <text> [--spec <path>]` — runs classify + `tier.should_halt`; prints `HALT: true|false`. `--spec`, when given, feeds §8.1 locked paths (via `coverage_gate.parse_81_block`) into `should_halt` so personal-rules cannot override locked-path halts.
  - `evaluate-action --action <text> [--spec <path>] [--json]` — single orchestrated call collapsing the §3.5 SKILL.md heredoc body. Emits the §3.5 prose-format output (or a structured JSON payload with `--json`).

- **`bin/auditor.py`** — 2 subcommands:
  - `audit-action --action <text> --paths <json-array> [--properties <json>] [--prose]` — pure check; wraps `auditor.audit_action`. Default JSON summary; `--prose` emits the §5.5 `AUDIT: N checks, ...` format.
  - `audit-and-clear --action <text> [--scratchpad <path>] [--track <name>] [--properties <json>] [--json]` — single orchestrated call collapsing the §5.5 SKILL.md heredoc body: load scratchpad via `_scratchpad.load`, read `paths_touched` via `_scratchpad.get_paths_touched` (v1+v2 schema-aware), run `auditor.audit_action`, persist `last_audit_*` back to the track, atomic-write the scratchpad. Sibling tracks preserved.

### Changed

The 2 high-leverage `python3 - <<'PY' ... PY` heredocs in `skills/implement/SKILL.md` deferred from Phase 2B have been replaced:

- **§3.5 — Persistence-Tier classifier** (audit occurrence #11, the longest heredoc in the repo at 33 LOC) → `python3 -m bin.tier evaluate-action --action "<current_action verbatim>" --spec "specs/<active spec name>.spec.md"`. The CLI runs classify → parse §8.1 → should_halt → emit prose-format output in one invocation. Same on-screen contract: `TIER:` / `reason:` / optional `NEVER_AUTONOMOUS:` / `HALT: true|false` lines.
- **§5.5 — State Auditor (informational)** (audit occurrence #19, 25 LOC) → `python3 -m bin.auditor audit-and-clear --action "<current_action>" --scratchpad state/scratchpad.json --track "<current_track>"`. The CLI runs the load → audit → write-back cycle as a single atomic operation. The heredoc body's two latent bugs — v1-schema-only `paths_touched` read on v2 scratchpads (silent no-op, partially fixed by v0.4.2.6 `get_paths_touched`) and raw `json.dump` write-back (corruption risk on interrupt) — are now structurally impossible from the CLI side.

LOC reduction in `skills/implement/SKILL.md`: ~58 LOC of heredoc-Python removed; ~31 LOC of CLI invocations + prose added. Net: ~27 LOC reduction.

Heredoc count: `vision/SKILL.md` unchanged at 7; `implement/SKILL.md` drops 13 → 11. 18 heredocs remain across both skill files (7 vision + 11 implement) — Phase 2D handles the remaining cleanup tail toward v0.5.0 final.

### Tests

**814 passing** (770 baseline + 44 new). Two new test files + one extension:

- `tests/test_tier_cli.py` — 12 subprocess-based tests covering `classify` (silent/host/never-autonomous + missing-flag), `should-halt` (silent/host/locked-path immunity + missing-flag), `evaluate-action` (prose format, JSON parseability, JSON `halt` field, locked-paths list, never-autonomous in JSON, missing-spec graceful, round-trip parity vs heredoc body, missing-flag, unknown-subcommand).
- `tests/test_auditor_cli.py` — 21 subprocess-based tests covering `audit-action` (empty paths → noop, missing path fail, existing path pass, prose format, prose `passed=True`, bad JSON, non-list paths, bad properties, missing action) and `audit-and-clear` (happy path, persisted `last_audit_passed`, persisted `last_audit_kinds`, v2 paths_touched drives audit, persisted failures, atomic-write preserves siblings, JSON flag, prose default, on-disk parity vs heredoc, missing scratchpad fallback, missing action, unknown subcommand).
- `tests/test_skill_prose_no_heredoc_python.py` — extended with 2 new scope-limited drift guards (§3.5 classifier block + §5.5 State Auditor) and tightened ceilings: `vision/SKILL.md` ≤ 7 (unchanged), `implement/SKILL.md` ≤ 11 (down from 13).

Smoke-tested both replacements against a fixture spec (`/tmp/spectre-phase2c-test/`): byte-identical on-disk track state and identical prose-format output between the heredoc reference run and the new CLI invocation.

### Notes

Phase 2C of issue #13 closes all 5 high-leverage audit targets. The remaining 18 heredocs (7 vision + 11 implement) are medium-/low-leverage — Phase 2D handles the cleanup tail. CDLC ledger transitions, walker yield-check, ADR writes, observation/track/personal-rules/scratchpad sub-section heredocs are still in place pending their own CLI surface.

### References

- Issue #13: https://github.com/Joncik91/Spectre/issues/13
- Audit: `docs/superpowers/audits/2026-05-06-issue-13-heredoc-audit.md`

---

## v0.5.0-rc2 — 2026-05-07

**Second prerelease toward v0.5.0. Phase 2B of issue #13 (heredoc replacement) — high-leverage prose surgery in `skills/vision/SKILL.md`. No behavioral changes to /vision or /implement flow.**

### Changed

3 of the 5 high-leverage `python3 - <<'PY' ... PY` heredocs called out in the issue #13 audit have been replaced in `skills/vision/SKILL.md`. The replacement form for each:

- **§6.4 — Pre-lock spec evaluator** (audit occurrence #5) → `python3 -m bin.spec_evaluator slug-to-path --slug <slug>` for canonical draft path derivation, then `python3 -m bin.spec_evaluator evaluate --spec <draft> --config ~/.spectre/reviewer.toml --bundle-dir state --output state/.eval-result.json`. The slug → path step now goes through the validated CLI (no inline `Path("specs/<slug>...")` substitution); the result is persisted for §6.7 to consume.
- **§6.6 — Resource node inference (read from bundle)** (audit occurrence #8) → native `Read` on `state/.eval-bundle.json` (which §6.4 already persisted, keyed by draft SHA-256). Removed inline SHA-256 + `load_persisted_bundle` Python; the bundle file is trusted because §6.4 wrote it in the same workflow.
- **§6.7 step 4 — Write the `.eval.json` sidecar** (audit occurrence #9) → `python3 -m bin.spec_evaluator slug-to-path` for the locked-spec path, then a 1-line stdlib JSON extraction of `sidecar_payload` from `state/.eval-result.json` piped to `python3 -m bin.eval_metadata write-sidecar --spec <spec>`. The misleading `draft` variable that pointed at `.spec.md` is gone, and `policy_hash`/`tiers_run`/`dismissals`/`findings_summary`/`evaluator_version` now flow verbatim from §6.4 — eliminating the policy-hash drift bug class that `test_vision_sidecar_path_consistency.py` was added to guard.

LOC reduction in `skills/vision/SKILL.md`: ~62 LOC of heredoc-Python removed; ~16 LOC of CLI invocations + native-tool prose added. Net: ~46 LOC reduction.

### Deferred to Phase 2C

Audit targets #11 (`skills/implement/SKILL.md` §3.5 Persistence-Tier classifier, 33 LOC heredoc) and #19 (§5.5 State Auditor, 25 LOC heredoc) are deferred to Phase 2C. Both require new CLI entry points on `bin/tier.py` and `bin/auditor.py` that Phase 2A did not ship; extending the CLI surface mid-Phase-2B would have retroactively broken Phase 2A's "additive only" guarantee. Phase 2C will land those CLIs alongside the §3.5 / §5.5 prose replacements in a single coherent PR.

20 heredocs remain (7 vision + 13 implement) per `grep -c "python3 - <<"` against both skill files; of the 5 high-leverage audit targets, 3 are closed and 2 are deferred to Phase 2C. Phase 2C handles the medium-leverage targets, Phase 2D the cleanup tail.

### Tests

**770 passing** (765 baseline + 5 new). One new test file:
- `tests/test_skill_prose_no_heredoc_python.py` — 5 scope-limited drift guards: §6.4, §6.6, and §6.7 sidecar-write block must contain zero heredoc-Python and must invoke their respective Phase 2A CLIs; both skill files have heredoc-count ceilings (vision ≤ 7, implement ≤ 13) so accidental new heredocs surface in CI.

The existing `tests/test_vision_sidecar_path_consistency.py` skill-prose drift checks still pass — the §6.7 prose still references `.spec.md.eval.json` (append-suffix) via the CLI's stdout.

### Notes

Phase 2B of issue #13. CDLC ledger transitions, walker yield-check, ADR writes, and other (b)/(c)-category heredocs (audit occurrences #1–#3, #6–#7, #10) remain in place — they are out of scope for this PR's "5 high-leverage targets" objective and depend on CLI surface that Phase 2A did not ship.

### References

- Issue #13: https://github.com/Joncik91/Spectre/issues/13
- Audit: `docs/superpowers/audits/2026-05-06-issue-13-heredoc-audit.md`

---

## v0.5.0-rc1 — 2026-05-06

**First prerelease toward v0.5.0. Phase 2A of issue #13 (heredoc replacement). Pure additive infrastructure — no behavioral changes to existing flows.**

### Added

CLI entrypoints (`if __name__ == "__main__":`) on three `bin/` modules. All subcommands wrap existing public functions; no new business logic added. No `skills/**/SKILL.md` changes (Phase 2B does that).

- **`bin/spec_evaluator.py`** — 3 subcommands:
  - `evaluate --spec <path> [--config <path>] [--bundle-dir <path>] [--output <path>]` — runs `evaluate()`, writes JSON result (findings + max_severity + sidecar_payload) to stdout or file.
  - `slug-to-path --slug <slug>` — prints canonical `specs/<slug>.spec.md` path.
  - `clear-bundle --bundle <path>` — removes the persisted eval bundle (idempotent).

- **`bin/eval_metadata.py`** — 4 subcommands:
  - `policy-hash [--config <path>] [--severity-overrides <json>]` — calls `compute_policy_hash()`, prints 64-char hex.
  - `sidecar-path --spec <path>` — calls `sidecar_path_for()`, prints the `.eval.json` path.
  - `write-sidecar --spec <path> --payload <file-or-stdin>` — calls `write_sidecar()` from a JSON payload (keys match `sidecar_payload` dict from `EvaluatorResult`). Payload via file path or `-`/omitted for stdin.
  - `sha256 --file <path> | --stdin` — SHA-256 of a file or stdin; prints hex digest. Resource-node helper (audit occurrence #8).

- **`bin/walker.py`** — 1 subcommand:
  - `init-or-resume --intent <text> --draft <path> [--state-path <path>]` — loads existing walk state or initialises via `init_walk()`, persists it, prints `WALK: N rounds, M pending, stop=<reason|none>`. Covers audit occurrence #2.

### Tests

**760 passing** (695 baseline + 65 new). Three new test files (subprocess-based CLI tests, one assertion per test):
- `tests/test_spec_evaluator_cli.py` — 19 tests covering `evaluate`, `slug-to-path`, `clear-bundle` (happy paths + error cases + output-file flag + JSON validity).
- `tests/test_eval_metadata_cli.py` — 33 tests covering `policy-hash` (TOML + severity-overrides + error), `sidecar-path`, `write-sidecar` (file + stdin + error cases), `sha256` (file + stdin + error cases).
- `tests/test_walker_cli.py` — 13 tests covering `init-or-resume` (fresh init, resume, round-count persistence, error cases, missing flags).

### Fixed

- `write-sidecar` CLI now preserves caller-supplied `findings_summary` (was silently zeroed when `findings=[]` was passed to `write_sidecar()`; counts came from the empty list instead of the payload).

### Notes

- This is the first prerelease toward v0.5.0.
- Phase 2A of issue #13 (heredoc-python replacement audit). No heredocs replaced yet — Phase 2B replaces the high-leverage targets using these CLIs.
- `bin/walker.py` defers `yield-check` subcommand — that orchestration path has no single existing function to wrap (compound: load → evaluate → update yield_history → persist). It will land in Phase 2B alongside the heredoc replacement.
- Stdlib only: `argparse`, `json`, `tomllib`, `hashlib`, `pathlib`, `sys`. No new dependencies.

### References

- Issue #13: heredoc-python replacement
- Audit: `docs/superpowers/audits/2026-05-06-issue-13-heredoc-audit.md`

## v0.4.2.6 — 2026-05-06

**Patch release — fix #13 audit finding (State Auditor silent no-op on v2 scratchpads).**

### Fixed
- **State Auditor schema level** — `skills/implement/SKILL.md` §5.5 heredoc was reading `paths_touched` via `sp.get("paths_touched", [])` directly from the scratchpad root. After the v1→v2 migration `paths_touched` moved to `data["tracks"][track]["paths_touched"]`, so the auditor silently received `[]` on every post-migration run and `auditor.audit_action` was a no-op for all v2 scratchpads. (Discovered during issue #13 audit: `docs/superpowers/audits/2026-05-06-issue-13-heredoc-audit.md`, occurrence #19.)
- Heredoc now uses `_scratchpad.get_paths_touched(sp, track="<current_track>")` which falls back to the v1 top-level key for mixed-version transitions.
- Heredoc now writes audit results back via `_scratchpad.atomic_write` instead of raw `json.dump`, eliminating the data-corruption risk on interrupted writes (also flagged in #19).
- **`bin/compact.py` PostToolUse hook never migrated to v2** — on every hook fire it was appending to `data["paths_touched"]` at root, leaving `tracks.default.paths_touched` frozen with stale data from migration time. The helper added in the prior commit prefers the v2-tracks path, so the auditor received stale data. `compact.py` now writes to `data["tracks"]["default"]["paths_touched"]` for v2 scratchpads; root-level write is preserved as fallback for unmigrated (v1/hand-edited) dicts only.
- **`isinstance(list)` guard on `get_paths_touched()`** — a corrupt `paths_touched: "string"` field no longer propagates to `auditor.audit_action` (which iterates it char-by-char). Both the v2-tracks and v1-root branches now verify the value is a list before returning it; a non-list value falls through to the next branch and ultimately returns `[]`.

### Tests
**694 passing** (690 baseline + 4 new). New tests:
- `tests/test_auditor.py::test_paths_touched_resolved_from_v2_schema_level` — v2 fixture; assert auditor sees actual paths under `tracks.default.paths_touched`.
- `tests/test_auditor.py::test_paths_touched_falls_back_to_v1_schema_level` — v1-style fixture (top-level key); assert lookup still returns the list.
- `tests/test_auditor.py::test_paths_touched_returns_empty_for_missing_field` — neither key present → `[]`, no crash.
- `tests/test_compact.py::test_v2_scratchpad_paths_touched_written_to_tracks_not_root` — end-to-end integration: seeds a v2 scratchpad, fires compact via subprocess (real hook path), asserts `tracks.default.paths_touched` contains the new path, root `paths_touched` is absent, and `get_paths_touched()` returns the v2 list.

### References
- Issue #13 audit: `docs/superpowers/audits/2026-05-06-issue-13-heredoc-audit.md` (occurrence #19)

## v0.4.2.5 — 2026-05-06

**Patch release — closes #12 P2 (Tier 3 prong timeouts on deepseek-reasoner).**

### Fixed
- **#12 P2** — Default `timeout_s` raised from 30s to 180s in `JudgeConfig` (`bin/llm_judge.py`) and `TIER3_TIMEOUT_S` (`bin/spec_evaluator.py`). New installs provisioned by `setup_wizard.write_config` also default to 180s. Existing `~/.spectre/reviewer.toml` is untouched (wizard is idempotent).
- **Retry-with-backoff** — `_call_deepseek` now retries up to 3 times (4 total attempts) on `socket.timeout`, `TimeoutError`, `urllib.error.URLError`, HTTP 429, and HTTP 5xx. Backoff: 2s, 4s, 8s (capped at 60s) plus 0–1s random jitter. Fail-fast on HTTP 400, 401, 403. Stdlib only (`time.sleep`, `random.uniform`).
- **Prong name + attempt count in error message** — On final failure, `_run_prompt` now emits: `Tier 3 unavailable: timeout in <prong_name> after 4 attempts (last error: <kind>)` where `<kind>` is `socket-timeout`, `http-<code>`, or `connection-error`.

### Tests
**690 passing** (683 baseline + 7 new). New tests in `tests/test_llm_judge.py`:
- `test_call_deepseek_retries_on_socket_timeout` — 2 timeouts then success; assert 3 attempts.
- `test_call_deepseek_retries_on_http_503` — 2 × 503 then success; assert 3 attempts.
- `test_call_deepseek_does_not_retry_on_http_401` — single attempt, error propagates.
- `test_call_deepseek_gives_up_after_3_retries` — always fails; assert 4 attempts, exception bubbles.
- `test_run_prompt_includes_prong_name_in_timeout_message` — assert `"context-gap"` in message.
- `test_default_timeout_s_is_180` — `JudgeConfig().timeout_s == 180`.
- `test_backoff_capped_at_60_seconds` — sleep durations all ≤ 60s.

### Migration
Existing users with `~/.spectre/reviewer.toml` keep their current `timeout_s` value (wizard never overwrites). To pick up the new 180s default: `rm ~/.spectre/reviewer.toml` and re-run `/vision` (wizard regenerates), or edit `timeout_s` manually.

### Changed
- `bin/spec_evaluator.py:EVALUATOR_VERSION` 0.4.2.4 → 0.4.2.5.
- `.claude-plugin/marketplace.json` plugin version 0.4.2.4 → 0.4.2.5.

### References
- Issue: https://github.com/Joncik91/Spectre/issues/12

## v0.4.2.4 — 2026-05-06

**Patch release — closes #12 P3 (sidecar path inconsistency).**

### Fixed
- **#12 P3** — `bin/eval_metadata.py` now exposes `sidecar_path_for(spec_path) -> Path` as the single source of truth for the sidecar filename convention. The sidecar is always the spec filename with `.eval.json` appended (append-suffix: `foo.spec.md.eval.json`), never replace-suffix (`foo.eval.json`). `write_sidecar()` is updated to call `sidecar_path_for()` internally. `skills/vision/SKILL.md` prose updated in three places to show the full append-suffix form and reference `eval_metadata.sidecar_path_for()` so future skill-prose drift is immediately visible.

### Tests
**681 passing** (675 baseline + 6 new). New test file `tests/test_vision_sidecar_path_consistency.py`: asserts `sidecar_path_for` produces append-suffix, not replace-suffix; checks parent-directory preservation; verifies `write_sidecar` return value equals `sidecar_path_for`; pins `SIDECAR_EXTENSION == ".eval.json"`.

### Changed
- `bin/spec_evaluator.py:EVALUATOR_VERSION` 0.4.2.3 → 0.4.2.4.
- `.claude-plugin/marketplace.json` plugin version 0.4.2.3 → 0.4.2.4.

### References
- Issue: https://github.com/Joncik91/Spectre/issues/12

## v0.4.2.3 — 2026-05-06

**Patch release — closes #12 P1 (Tier 3 silently skipped when key is in secrets.env).**

### Fixed
- **#12** — `bin/llm_judge._call_deepseek()` now falls back to `~/.spectre/secrets.env` (or the path in `SPECTRE_SECRETS_FILE`) when `DEEPSEEK_API_KEY` is absent from the live environment. `resolve_api_key()` (new public helper) mirrors the probe order documented in `setup_wizard.detect_api_key()`: env var first, secrets file second. Quoted values (`KEY="value"` and `KEY='value'`) are stripped. The key is never logged. Users who follow the documented setup flow (add key to `secrets.env`, run `/vision`) no longer get Tier 3 silently downgraded.
- Skip-reason rendering distinguished: `_run_prompt` now catches `_NoApiKeyError` before the generic `RuntimeError` handler and emits `"Tier 3 skipped (no-api-key): …"` — separate from `"Tier 3 skipped (disabled-in-config): …"` already emitted by `spec_evaluator.evaluate()`.

### Tests
**675 passing** (670 baseline + 5 new). New tests in `tests/test_llm_judge.py`: `test_tier3_reads_secrets_env_when_envvar_unset`, `test_tier3_strips_quotes_from_secrets_env_value`, `test_tier3_skipped_no_api_key_when_neither_env_nor_file_has_key`, `test_tier3_envvar_takes_precedence_over_secrets_file`, `test_tier3_renders_distinct_no_api_key_skip_reason`.

### Changed
- `bin/spec_evaluator.py:EVALUATOR_VERSION` 0.4.2.2 → 0.4.2.3.
- `.claude-plugin/marketplace.json` plugin version 0.4.2.2 → 0.4.2.3.

### References
- Issue: https://github.com/Joncik91/Spectre/issues/12

## v0.4.2.2 — 2026-05-06

**Patch release — closes #10 (v0.4.2.1 regression).**

### Fixed
- **#10** — `bin/setup_wizard.maybe_provision()` no longer prompts on the detected-key path. v0.4.2.1 fixed only the no-key branch; the yes/no prompt for an existing key still called `input()` and raised `EOFError` in non-interactive contexts. Configuring the API key in `~/.spectre/secrets.env` (or the `DEEPSEEK_API_KEY` env var) is itself the opt-in signal — Tier 3 enables silently. To opt out: edit `~/.spectre/reviewer.toml` and set `[tier3] enabled = false`. To re-prompt provisioning: delete `~/.spectre/reviewer.toml`. The `prompt_fn` parameter and the `"declined"` outcome are removed from the public API; both branches (key-detected, key-absent) are now non-interactive.

### Tests
**670 passing.** New regression test `test_maybe_provision_detected_key_does_not_call_input` monkeypatches `builtins.input` to fail-on-call and asserts the detected-key path returns `"enabled"`. The legacy `test_maybe_provision_disables_on_user_no` (asserted the now-removed `"declined"` outcome) is deleted. Existing test `test_detect_api_key_returns_none_when_env_missing_and_no_openclaw` now monkeypatches HOME so it doesn't depend on host-side `~/.spectre/secrets.env`.

### Changed
- `bin/spec_evaluator.py:EVALUATOR_VERSION` 0.4.2.1 → 0.4.2.2.
- `.claude-plugin/marketplace.json` plugin version 0.4.2.1 → 0.4.2.2.

### References
- Issue: https://github.com/Joncik91/Spectre/issues/10

## v0.4.2.1 — 2026-05-06

**Patch release — two blocking bugs surfaced by the v0.4 end-to-end live test.**

### Fixed
- **#7** — `bin/setup_wizard.maybe_provision()` no longer prompts when no `DEEPSEEK_API_KEY` is found. Adding the API key is a prerequisite to using Spectre, not an in-flow decision; the wizard now silently writes the `enabled=false` placeholder, prints one stderr breadcrumb naming the resolved secrets path and the env-var name, and returns `"setup-skipped"`. Eliminates `EOFError` in non-interactive contexts (subagents, scripts, paste-stdin, observer flows). The `_SETUP_BANNER` constant and the `(retry / skip)` loop are removed.
- **#8 finding 2** — `bin/spec_evaluator.evaluate()` now populates `policy_hash`, `config_hash`, and `deepseek_model_version` in `result.sidecar_payload`, matching the schema `skills/vision/SKILL.md` §6.7.4 documents. Previously `eval_metadata.write_sidecar()`'s required `policy_hash` kwarg raised `KeyError` on every well-formed lock; today's workaround (manual `compute_policy_hash` from outside the evaluator) is no longer needed. `policy_hash` is always computed; `config_hash` is the SHA-256 of the config TOML bytes when `config_path` exists, `None` otherwise; `deepseek_model_version` captures `tier3.model` only when Tier 3 actually reached the API.

### Tests
**670 passing** (664 v0.4.2 baseline + 3 wizard silent-skip + 5 evaluator sidecar parity − 2 retry/skip tests obsoleted by the new flow). Wizard non-interactive smoke test added; full `/vision` lock now succeeds end-to-end without manual intervention.

### Changed
- `bin/spec_evaluator.py:EVALUATOR_VERSION` 0.4.2 → 0.4.2.1.
- `.claude-plugin/marketplace.json` plugin version 0.4.2 → 0.4.2.1.

### Out of scope (deferred to v0.5)
- Issue #8 finding 1 — `~/.spectre/**` never-touches collision with spec-author-declared paths. Needs a design call on spec-subject vs meta-tool path boundary.
- Issue #8 finding 3 — scratchpad v2 schema clash with auto-tracker hook. Needs hook audit.
- Issue #8 finding 4 — ADR over-generation curation. UX/curation discussion.

### References
- Issues: https://github.com/Joncik91/Spectre/issues/7 and https://github.com/Joncik91/Spectre/issues/8

## v0.4.2 — 2026-05-06

**v0.4 line — CDLC Ledger + Distribute + Adapt (third and final v0.4 release).**

### Added
- `bin/cdlc_ledger.py` — per-project lifecycle transition log at `state/cdlc-ledger.json`. Records every Generate→Test→Lock→Implement→Halt→Adapt transition with timestamps and payloads. Public API: `append_transition`, `read_ledger`, `cdlc_ledger_path_default`.
- `bin/templates.py` — Distribute leg. `~/.spectre/templates/{specs,skills}/` directory + import/export tooling. Public API: `list_templates`, `import_template`, `export_template`, `templates_dir_default`.
- `bin/template_patcher.py` — Adapt's auto-patch proposer. When `observations.find_recurrences(threshold=3)` returns recurring fingerprints AND no personal-rules entry covers them, writes a markdown patch to `~/.spectre/template-patches/proposed/<slug>.md`. Public API: `detect_patch_candidates`, `propose_patch`, `list_proposed_patches`.
- `bin/_scratchpad.track_default()` gains `pending_adoption_prompt: dict | None` so `/implement` §3.5b survives compact/restart.

### Changed
- `bin/hydrate.py` (SessionStart hook) surfaces "N pending template-patch proposals" when `~/.spectre/template-patches/proposed/` is non-empty.
- `skills/vision/SKILL.md` Step 0 surfaces template-import as an option alongside codebase fingerprint scan.
- `skills/implement/SKILL.md` §3.5 writes `pending_adoption_prompt` to scratchpad on TIER GATE halt + user=yes; §3.5b reads it post-Path-A and clears after prompt fires. Ledger writes at halt + Path A.
- `bin/setup_wizard.py` extended to provision `~/.spectre/templates/{specs,skills}/` and `~/.spectre/template-patches/{proposed,accepted,rejected}/` (mode 0700 dirs, mode 0600 files inside).
- `bin/spec_evaluator.py:EVALUATOR_VERSION` 0.4.1 → 0.4.2.
- `.claude-plugin/marketplace.json` plugin version 0.4.1 → 0.4.2.

### Tests
**664 passing** (614 v0.4.1 baseline + 11 cdlc_ledger + 14 templates + 12 template_patcher + 2 scratchpad + 5 hydrate + 4 setup_wizard + 2 observations/personal_rules wire-up). Audit fixes during build: clear pending_adoption_prompt FIRST in §3.5b (prevent replay), ledger write non-blocking in §3.5, step number ambiguity in §6 Path A pinned to pre-increment, hydrate idempotency regression test for slug-parity contract.

### Architecture references
- Design: `docs/superpowers/specs/2026-05-06-spectre-v0.4-cdlc-closure.md`
- Plan: `docs/superpowers/plans/2026-05-06-v0.4.2-cdlc-distribute.md`

### Out of scope (v0.5+)
- Remote sync of `~/.spectre/templates/` (git-backed team registries).
- Auto-merge of template-patches (always proposes; manual accept).
- Real-time observe→adapt loop (recurrence check fires only at SessionStart).

## v0.4.1 — 2026-05-06

**v0.4 line — Observe + Adapt legs (second of three releases).**

### Added
- `bin/observations.py` — append-only halt log at `~/.spectre/observations.jsonl`. Public API: `record_halt`, `find_recurrences`, `fingerprint_halt`.
- `bin/personal_rules.py` — TOML-backed rule overrides at `~/.spectre/personal-rules.toml`. Public API: `load_personal_rules`, `is_classifier_halt_overridden`, `append_adoption`, `adoption_count_this_session`. Sandbox-paradox brake caps adoptions at 3 per session.
- `~/.spectre/personal-rules.toml` — empty placeholder auto-provisioned by setup_wizard.

### Changed
- `bin/tier.should_halt()` consults `personal_rules.is_classifier_halt_overridden()` before returning True. Personal rules can ONLY downgrade; project-locked §8.1 rules are immune.
- `skills/implement/SKILL.md` — every TIER GATE halt records a fingerprint to `observations.jsonl`. New §3.5b post-halt-success prompt: after user picks `yes` and verification passes, prompts "Adopt this halt-class as personal-rule-skip? (adopt / once-only / never-ask-again)". Stops firing after 3 adoptions/session.
- `bin/setup_wizard.py` — extended to provision `~/.spectre/personal-rules.toml` on first run.
- `bin/spec_evaluator.py:EVALUATOR_VERSION` 0.4.0 → 0.4.1.
- `.claude-plugin/marketplace.json` plugin version 0.4.0 → 0.4.1.

### Tests
**614 passing** (569 v0.4.0 baseline + 14 observations + 22 personal_rules + 5 setup_wizard + 4 tier integration). The personal_rules count includes 4 audit-fix tests for the persistent brake counter and the TOML escape hardening.

### Architecture references
- Design: `docs/superpowers/specs/2026-05-06-spectre-v0.4-cdlc-closure.md`
- Plan: `docs/superpowers/plans/2026-05-06-v0.4.1-observe-adapt.md`

### Deferred to v0.4.2
- `bin/cdlc_ledger.py` + `state/cdlc-ledger.json`
- `~/.spectre/templates/` Distribute leg
- Adapt's auto-template-patch proposal flow
- Aggregated retroactive Adapt prompt (≥3× recurrence detection — code is in observations.find_recurrences but the prompt surface ships in v0.4.2)

## v0.4.0 — 2026-05-06

**v0.4 line — Interrogation-driven /vision (first of three releases).**

### Added
- `bin/walker.py` — strict-hybrid state machine for spec interrogation. Owns walk state, dependency-tracked invalidation, stop conditions. Public API: `Concern`, `WalkState`, `init_walk`, `next_concern`, `record_answer`, `revise_answer`, `should_stop`, `persist`, `load`.
- `~/.spectre/walker.toml` — auto-provisioned config (max_rounds, yield_threshold, yield_converge_rounds, brake_threshold).
- `state/.walk.json` — per-spec/per-track walk persistence; atomic JSON writes.

### Changed
- `skills/vision/SKILL.md` — Steps 1–5 rewritten as walker-driven interrogation loop. Steps 6.4–6.7 (evaluator + ADR + Resource + lock) preserved unchanged.
- `bin/setup_wizard.py` — extended to provision `~/.spectre/walker.toml` alongside `~/.spectre/reviewer.toml`.
- `bin/spec_evaluator.py:EVALUATOR_VERSION` 0.3.1 → 0.4.0.
- `.claude-plugin/marketplace.json` plugin version 0.3.2 → 0.4.0.

### Tests
**569 passing** (504 v0.3.2 baseline + 60 new walker tests + 5 new wizard tests). Audit fixes added during build: yield_converge_rounds precondition, walker_version validation, init_walk seeds 4 §8.1 concerns, skill writes stop_reason after should_stop.

### Architecture references
- Design: `docs/superpowers/specs/2026-05-06-spectre-v0.4-cdlc-closure.md`
- Plan: `docs/superpowers/plans/2026-05-06-v0.4.0-walker.md`

### Deferred to v0.4.1
- `bin/observations.py` + live opt-out at /implement halt sites
- `bin/personal_rules.py` + sandbox-paradox brake

### Deferred to v0.4.2
- `bin/cdlc_ledger.py` + Distribute leg (~/.spectre/templates/) + Adapt template-patch proposals

## v0.3.2 — 2026-05-06

**Setup-wizard usability follow-up to v0.3.1.**

The v0.3.1 wizard silently wrote a disabled placeholder when no DeepSeek key was found anywhere — meaning a fresh user running `/vision` for the first time never saw a prompt, never learned Tier 3 existed, and stayed disabled forever. This release fixes that, and also moves the canonical secrets location from a host-specific path into Spectre's own config dir.

### Added
- `bin/setup_wizard.secrets_path_default()` — returns `~/.spectre/secrets.env`. Single, in-Spectre, host-agnostic location for the DeepSeek API key.
- New wizard outcome `setup-skipped` (replaces v0.3.1's silent `no-key`). Returned only when the user explicitly types `skip` after seeing the setup banner.
- New wizard outcome path: when no key is found, the wizard prints a setup banner with both the env-var route and the `~/.spectre/secrets.env` route, then loops on `(retry / skip)`. `retry` re-probes — drop the key, type `retry`, and the wizard detects + prompts for opt-in. No second `/vision` invocation needed.

### Changed
- `bin/setup_wizard._resolve_secrets_file_path()` now defaults to `~/.spectre/secrets.env` when no explicit path or `SPECTRE_SECRETS_FILE` env var is provided. v0.3.1 returned None (silent fall-through); v0.3.2 always probes the canonical location.
- `README.md` — replaced the brief "Optional Tier 3" paragraph with a full "First-run setup" section that walks through the three-source key discovery order and the retry-loop behavior. Standard-Readme spec preserved.
- `README.md` — added `/implement auto` to the Usage section (v0.3.1 introduced the mode but the README never documented it).
- `EVALUATOR_VERSION` bumped 0.3.1 → 0.3.2; marketplace.json plugin version aligned.

### Tests
**504 passing** (500 v0.3.1 baseline + 4 new for v0.3.2 wizard outcomes: `secrets_path_default`, `~/.spectre/secrets.env` detection, auto-probe on `secrets_file_path=None`, retry-after-drop flow). The original `no-key` test was rewritten to assert `setup-skipped` since the contract changed.

## v0.3.1 — 2026-05-06

**Closes [#1](https://github.com/Joncik91/Spectre/issues/1) — 9 UX/safety gaps surfaced by the v1.1.0 BTC proxy test run.**

Pure UX/safety hardening release. No new features; every change either makes a load-bearing defense visible (Tier 3 skip), wires a documented defense to actual code (systemctl/loginctl in NEVER_AUTONOMOUS), or removes friction without lowering safety (`/implement auto`, loopback curl downgrade).

### Added
- `bin/setup_wizard.py` — first-run auto-provisioner for `~/.spectre/reviewer.toml`. Detects `DEEPSEEK_API_KEY` in env (or `.env`-style file pointed to by `SPECTRE_SECRETS_FILE`), prompts once with cost estimate, writes TOML at mode 0600. Writes `enabled=false` placeholder on decline/no-key so subsequent runs don't re-prompt. Closes the user-side ask: no more out-of-band TOML provisioning.
- `bin/spec_lint.py` — Tier 1.5 spec-author lints. Two checks today: `runuser-no-cd` (warn — `runuser -l user -c '<cmd>'` without `cd` lands in `$HOME`, masking failures) and `unsafe-heredoc` (info — heredoc-script bodies without `set -euo pipefail`). Wired into the evaluator's Tier 1 pipeline.
- `tests/test_setup_wizard.py` (17 cases) and `tests/test_spec_lint.py` (14 cases).
- `bin/_scratchpad.py` DEFAULT gains `pending_findings: []` for the Step 7.5 fallback queue.

### Changed
- `bin/tier.py` `_NEVER_AUTONOMOUS` now includes `systemctl <verb>` (start/stop/restart/reload/enable/disable/mask/unmask, with `--user`/`--system` flag tolerance), `loginctl enable-linger` / `disable-linger`, `hostnamectl set-*`, `timedatectl set-*`, and `sysctl -w`. The Risk-Gate caught zero of three host-mutating systemctl invocations in the v1.1.0 test run; the agent had to manually judgment-override. These five regex additions move that work from agent vigilance to machine enforcement.
- `bin/tier.py` `_is_network()` downgrades loopback URLs (`127.0.0.1`, `localhost`, `[::1]`, `0.0.0.0`) and RFC1918 (`10.*`, `172.16-31.*`, `192.168.*`) to path-based tier classification. The packet never leaves the kernel; halting on `curl http://127.0.0.1/health` is pure friction. Variable URLs (`$VAR`) keep network tier — false-positive is the safe default.
- `bin/spec_evaluator.py` always emits a `tier3-unavailable` info finding when Tier 3 is unavailable for any recoverable reason. Three new reason markers in the message: `config-missing`, `disabled-in-config`, `no-api-key`. v0.3.0 silently dropped Tier 3 with no signal — sidecar showed `tiers_run=[1,2]` and that was it. v0.3.1 makes the skip visible in §6.4 output.
- `bin/spec_evaluator.py` `EVALUATOR_VERSION` `0.3.0` → `0.3.1`. `DEEPSEEK_MODEL` from non-existent `deepseek-v4-pro` to `deepseek-reasoner` (DeepSeek's actual reasoning model on the v1 API; reasoning > chat for adversarial spec critique).
- `bin/spec_ast.py` `_extract_paths_from_text` filters `/dev/null`, `/dev/stdout`, `/dev/stderr` (and their `/null`/`/stdout`/`/stderr` word-boundary artifacts after `2>/dev/null` redirects). The action-not-probed heuristic no longer false-positives on stream redirects.
- `skills/vision/SKILL.md` — new §6.3a wizard call before §6.4. §6.4 always passes `~/.spectre/reviewer.toml` (existence-check moved into the evaluator). Output format updated: one line per tier with PASS/SKIPPED + reason, so Tier 3 status is as visible as Tiers 1 and 2.
- `skills/implement/SKILL.md` — new `/implement auto` mode. Walks consecutive silent/repo-tier steps without re-prompting; halts at host/network/never-autonomous, queued resources, verification fail, drift, or completion. Same safety surface as per-step. Plain `/implement` still runs exactly one step.
- `skills/implement/SKILL.md` — new §Step 7.5 Spectre-finding capture. When Path B retry succeeds (the corrected action passes verification after the original failed), the skill prompts to file the finding. Default category is `spectre` (the trigger pattern reliably identifies a runtime-environment quirk, not a project design choice). Spectre-category findings auto-route to gh issue #1 thread; project-category writes a normal ADR. Fallback queues drafts in `pending_findings: []` if `gh` fails.
- `bin/findings.py` `KNOWN_KINDS` adds `runuser-no-cd` and `unsafe-heredoc`.

### Fixed
- Gap 1: Tier 3 silent skip — see Changed (visible findings + auto-provision wizard).
- Gap 2: Tier 1 path false-positive on `2>/dev/null` — see Changed (`_extract_paths_from_text` filter).
- Gap 3: DeepSeek model alias drift — see Changed (`DEEPSEEK_MODEL` standardized on `deepseek-reasoner`).
- Gap 4: spec-author traps with `runuser -l <user> -c '<cmd>'` and unsafe heredocs — Tier 1.5 lint catches both at lock-time.
- Gap 6: Risk-Gate not firing on `systemctl <verb>` / `loginctl enable-linger` / etc. — five new NEVER_AUTONOMOUS regex patterns.
- Gap 7: Spectre-itself ADRs evaporating with throwaway test repos — Step 7.5 auto-routes to upstream issue #1 thread, never to a hidden side-channel.
- Gap 8: `/implement` per-step friction on long specs — auto mode batches truly-low-tier steps.
- Gap 9: loopback `curl` over-classified as network tier — `_is_network()` parses URLs and downgrades.

### Tests
**500 passing** (439 v0.3.0 baseline + 61 v0.3.1 new across `test_tier`, `test_spec_evaluator`, `test_setup_wizard`, `test_spec_lint`, `test_spec_ast`, `test_scratchpad`). Stdlib-only. Pragma test-gaming guard satisfied.

### Deferred to v0.4
- Gap 5: per-spec Tier-Gate approval memoization for steps with many `chmod`s. Requires per-spec gate-approval cache; not in v0.3.1's scope.
- Drift checkpoint sliding window > 5 (currently fixed at 5).
- `paths_touched` retention beyond 200 entries (FIFO truncation when capped).
- Project-local NEVER_AUTONOMOUS verb override file.

### Architecture references
- All 9 gap descriptions and root-cause analysis live in https://github.com/Joncik91/Spectre/issues/1 (issue body + 5 comments).

## v0.3.0 — 2026-05-05

**Plan A — Pre-lock spec evaluator (CDLC Evaluate phase).**

### Added
- `bin/findings.py` — typed Finding dataclass with structured locations + dismissable flag + stable fingerprint (excludes message text so LLM nondeterminism doesn't break dismissals)
- `bin/spec_ast.py` — Tier 1 deterministic spec-AST classifier (pure parse/structure/tautology, NO `bin.tier`/`bin.resources` calls; AST-static import-isolation guards)
- `bin/coverage_gate.py` — Tier 2 default-on coverage gate: undeclared-resource (warn), undeclared-host-path (block), calibration-hard-violation (block, both never-touches AND mutates-subset halves), decision-without-adr (warn, deterministic rule)
- `bin/llm_judge.py` — Tier 3 DeepSeek v4 Pro adversarial reviewer (opt-in via `~/.spectre/reviewer.toml`); 3-prompt probing (context-gap, asserts-wrong, attacker-view); never raises (all errors → tier3-unavailable info sentinel)
- `bin/spec_evaluator.py` — review-bundle orchestrator with disk persistence keyed by draft SHA-256; dismissal filtering with stable fingerprints; `EvaluatorResult` carries `sidecar_payload` for §6.7 lock
- `bin/eval_metadata.py` — `.eval.json` lock-metadata sidecar + policy-hash + no-downgrade enforcement (config can raise severity, never lower)
- `specs/template.spec.md` — §8 Receiver Calibration (8.1 hard contract: `mutates`/`never-touches`/`decision-budget`/`reboot-survival`; 8.2 human-facing notes: `assumes`/`runtime-flavor`/`expected-author-skill`)
- `.spectre/reviewer.toml.example` — sample user config (committed for discoverability)
- `tests/test_dismiss_integration.py` — high-risk integration test for dismiss → re-run → skip flow
- `tests/test_bundle_handoff_integration.py` — high-risk integration test for §6.4→§6.7 bundle persistence pipeline
- `tests/test_btc_poller_regression.py` + `tests/fixtures/specs/btc_poller_v022.spec.md` — canonical regression: v0.2.2 BTC poller draft surfaces 4 of 5 failures pre-lock (success criterion #1)

### Changed
- `skills/vision/SKILL.md` — §6.4 evaluator gate inserted between draft confirmation (§6) and ADR generation (§6.5); §6.6 Resource inference reads from validated persisted bundle (no recomputation); §6.7 lock writes `.eval.json` sidecar and clears bundle
- `.claude-plugin/plugin.json` — version 1.0.2 → 1.1.0

### Tests
**439 passing** (261 v0.2.2 baseline + 178 v0.3 new). Stdlib only. Pragma test-gaming guard satisfied. Mocked HTTP for Tier 3 — no real DeepSeek calls in tests.

### Hardening rounds (review-driven, both Copilot/GPT-5.4 and ucai:reviewer)
- **findings:** fingerprint excluded `tier` (Tier 1 dismiss would silently suppress Tier 2 with same kind/location); `steps=[]` collapsed to `None` (truthiness bug); round-trip tests covered only 3/7 fields.
- **spec_ast:** `^echo\b` regex falsely flagged compound checks (`echo done && test -f /tmp/x`); mock targets in import-isolation tests patched namespaces module never imported (vacuous tests); CRLF line endings broke YAML fence regex.
- **coverage_gate:** `calibration-hard-violation` only checked `never-touches:`, missing the `not in mutates:` half (false pass for any path captured but undeclared); prefix-match boundary bug (`/etc` matched `/etcabc`); block-list `resources:` format silently produced empty set; `Optional[list[str]]` style inconsistency.
- **llm_judge:** redundant `socket.timeout`/`TimeoutError` alias (nit only).
- **eval_metadata:** unknown finding kinds in `severity_overrides` silently passed through; `validate_no_severity_downgrade` raised `KeyError` (not `ValueError`) on unknown severity.
- **spec_evaluator:** `load_persisted_bundle` reconstructed `draft_path` as bundle directory (broken — IsADirectoryError on read); `_apply_severity_overrides` accepted invalid severity values that crashed via `Finding.__post_init__`; silent config miss when path provided but file absent; `dismissed_t3_count` counted lines not actually-dismissed findings; vacuous lazy-import mock test.

### Architecture references
- v0.3 brief: `docs/superpowers/specs/2026-05-05-spectre-v0.3-spec-evaluator.md`
- Plan A: `docs/superpowers/plans/2026-05-05-v0.3-plan-a-spec-evaluator.md`
- Both reviewed by Copilot/GPT-5.4 before merge; all material findings adopted.

### Deferred
- Test-gaming defense at `/implement` test outputs → **v0.4** (Pragma-pattern integration with DeepSeek as reviewer; same `bin/llm_judge.py` infrastructure)
- Manual E2E in fresh `/vision` session → user-driven post-merge (Task 11's regression fixture covers the canonical failure-mode case automatically)
- Auto-fix from findings → v0.5 candidate
- Live host-state probing (port-collision detection) → ideas-doc #4
- Local LLM as Tier 3 → never (user policy: thermal risk on A8 documented 2026-04-11)

## v0.2.2 — 2026-05-05

**Plan C — Supervisor + Resource Locks + Multi-Track.**

### Added
- `bin/supervisor.py` — per-project Unix domain socket daemon. On-demand spawn from first `/implement <track>` call. Idle self-shutdown after 30 min. `/proc/<pid>/stat` actor fingerprinting for reboot-recovery. Single-threaded `select()` loop.
- `bin/resources.py` — Resource node parsing from graph manifest + heuristic extraction (`port:N` style) from action commands. Defenses against quoted-string false-positives, leading-zero ports, IP:port parsing, port range validation (1-65535).
- `bin/track.py` — client API: `acquire`, `release`, `status`, `heartbeat`, `ensure_supervisor_running`. Liveness probe + auto-respawn after SIGKILL'd supervisor leaves stale pid+sock on disk.
- `bin/migrate_scratchpad_v1_to_v2.py` — idempotent, atomic v1→v2 scratchpad migration. Preserves unknown user-authored v1 keys under `_v1_unknown`.
- `bin/_scratchpad.py` — `DEFAULT_V2`, `track_default()`, `load_track`, `save_track`, `expand_v1_to_v2` (single source of truth for v1→v2 promotion).
- `specs/template.spec.md` — optional `resources:` field per step.

### Changed
- `bin/hydrate.py` — SessionStart hook auto-migrates v1 scratchpad to v2. `state_line()` reads from `tracks.default` for v2, falls back to top-level for v1. Error signal now includes exception class for debuggability.
- `skills/implement/SKILL.md`
  - §0.5 — `/implement <track>` argument selects track in v2 scratchpad's `tracks:` map (default = `"default"`).
  - §3.6 — Resource lock acquire via supervisor before action execution. Halts with `RESOURCE QUEUED` if at capacity.
  - §6.7 — Resource lock release on terminal step state (advance OR halt).
- `skills/vision/SKILL.md`
  - §6.6 — auto-detects `port:N` Resource nodes from drafted actions. Adds Resource nodes to `specs/.graph.md` if missing, appends `resources:` to spec steps.
  - §6.7 — scratchpad reset uses v2 multi-track shape.
- `bin/graph.py` — already supported `resource` node type and `blocks` edge from Plan A; Task 8 adds round-trip + cascade-exclusion test coverage.
- `.claude-plugin/plugin.json` — version 1.0.1 → 1.0.2.

### Tests
261 passing (188 from v0.2.1 baseline + 20 resources + 6 scratchpad-v2 + 8 migration + 2 hydrate + 18 supervisor + 10 track + 3 graph + 6 fix-driven regression). Stdlib only. Pragma test-gaming guard satisfied.

### Hardening rounds (review-driven)
- **resources:** date false-positive (`2026-05:08` → port 08), missing port range validation, leading-zero acceptance.
- **scratchpad:** auto-expand silently dropped v1 in-flight state; null-tracks corruption; DRY violation between `_expand_v1_to_v2` and migrate.
- **supervisor:** missing `try/except OSError` around bind (race-loser crashes), blocking `recv()` halts entire daemon, pid file written before bind (race loser corrupts winner's pid file), reconcile non-idempotent (duplicates holders on second call), `_shutdown` sentinel leaked into JSON response, `granted_at` rewritten on every persist (lost original time), `_actor_alive` didn't catch `PermissionError`/`ProcessLookupError`/value parse errors.
- **track:** stale-socket connect raised `ConnectionRefusedError` instead of documented `RuntimeError`; missing liveness probe in `ensure_supervisor_running` meant SIGKILL'd supervisor wasn't re-spawned; absolute-path resolution before subprocess spawn (was binding to wrong dir when caller passed `Path('.')`).

### Smoke test
- Two-track contention on `port:8080`: A grants, B queues at position 1, release A promotes B. ✓
- SIGKILL supervisor → restart → reconcile reaps dead-actor lock. ✓

## v0.2.1 — 2026-05-05

**Plan B — Skill integration.**

### Added
- `bin/tier.py` — Persistence-tier classifier (silent/repo/host/network) with Never Autonomous list. Replaces v1 regex Risk-Gate.
- `bin/auditor.py` — Post-action State Auditor with PBT-lite checks (`type` / `schema` / `length` / `range`). Informational, not blocking.
- `bin/adr.py` — ADR file writer + graph supersedes-edge updater. ADRs live at `decisions/<NNNN>-<slug>.md`.
- `decisions/` directory — destination for Architecture Decision Records.
- `specs/template.spec.md` — optional `properties:` field per step for PBT-lite assertions.

### Changed
- `skills/implement/SKILL.md`
  - §3.5 — regex Risk-Gate replaced with `bin/tier.py` shell-out (the classifier is the sole source of truth for halt-vs-execute).
  - §5.5 — new informational State Auditor pass that runs after verification and writes verdicts to `state/scratchpad.json`.
- `skills/vision/SKILL.md`
  - §0 — Codebase Fingerprint runs before drafting, surfaces prior art in the Algorithm Audit (Delete) section.
  - §6 — Draft-to-disk replaces inline spec print. User reads in their editor and replies `yes / refine / cancel`.
  - §6.5 — ADR generation in confirm flow with optional supersedes detection.
  - §6.7 — Spec lock split out of §6 to make the draft → confirm → lock sequence explicit.
- `bin/_scratchpad.py` — `last_audit_kinds`, `last_audit_passed`, `last_audit_failures` added to `DEFAULT`.
- `.claude-plugin/plugin.json` — version 1.0.0 → 1.0.1.

### Tests
188 passing (108 from v0.2.0 + 36 tier + 21 ADR + 20 auditor + 3 scratchpad audit fields).

### Deferred to Plan C (v0.2.2)
- Supervisor process for parallel `/implement <track>`
- Resource locks (port, DB connection, external API quota)
- Multi-track scratchpad migration
- Cross-track dependency graph
- Reboot-recovery for Resource locks

### Deferred to v3
- TLA+ formal methods
- Linux capabilities sandboxing
- Cross-machine state sync (Raft consensus)
- Auto-generated PBT properties
- ADR semantic-contradiction detection beyond simple title/body match

## v0.2.0 — 2026-05-05

**Plan A — Graph foundation.** Pure infrastructure, no behavior change for v1 users.

- `bin/graph.py` — graph data model + manifest serializer/parser at `specs/.graph.md`.
- `bin/fingerprint.py` — codebase symbol-map walker writing `state/local-symbols.json`.
- 108 tests passing (45 v0.1.0 carry-over + 39 graph + 24 fingerprint).

## v0.1.0 — 2026-05-05

**Initial release.** Deterministic spec-driven Claude Code plugin with `/vision` and `/implement` skills, SessionStart hydrator, PostToolUse(Bash) compactor.
