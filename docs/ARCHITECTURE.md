# Architecture

This document describes how Spectre's pieces fit together. The user-facing surface (`/vision`, `/implement`, the hooks) is documented in [`README.md`](../README.md); this is the internals view.

## Layers

```
┌────────────────────────────────────────────────────────────┐
│  CONTEXT PLANE  (hooks — own what Claude Code "sees")      │
│    SessionStart    → bin/hydrate.py                        │
│    PostToolUse(Bash) → bin/compact.py                      │
└────────────────────────────────────────────────────────────┘
┌────────────────────────────────────────────────────────────┐
│  AGENT PLANE  (skills — own the multi-turn protocol)       │
│    /vision        → skills/vision/SKILL.md                 │
│    /implement     → skills/implement/SKILL.md              │
└────────────────────────────────────────────────────────────┘
┌────────────────────────────────────────────────────────────┐
│  STATE PLANE  (bin/ — own all on-disk truth)               │
│    Specs:        specs/.active, specs/<slug>.spec.md       │
│    Graph:        specs/.graph.md                           │
│    Scratchpad:   state/scratchpad.json (v2, per-track)     │
│    Bundle:       state/.eval-bundle.json (transient)       │
│    Sidecar:      <spec>.eval.json (post-lock)              │
│    ADRs:         decisions/<NNNN>-<slug>.md                │
│    Locks:        runtime/supervisor.{sock,pid}             │
└────────────────────────────────────────────────────────────┘
```

The strict separation matters. Hooks must finish in <10s and emit only `additionalContext`; they never block, never prompt, never write specs. Skills are multi-turn, prompt for confirmation, and are the only writers of `.active`. Modules under `bin/` are pure functions over disk state — they have no opinion about what Claude Code shows the user.

## Hook flow

### SessionStart → `bin/hydrate.py`

1. Detect v1 scratchpad and migrate to v2 in place (idempotent — `migrate_scratchpad_v1_to_v2.py`).
2. Read `specs/.active`. If absent: emit `SIGNAL: No active spec. Run /vision to begin.` plus the list of available specs.
3. If present: read the spec body and emit it wrapped in `--- ACTIVE SPEC ---` markers, followed by a per-track `STATE: step=N exit_code=X last_command=…` line.
4. Stale pointer (file referenced by `.active` no longer exists): emit `ERROR: stale .active pointer …`.

### PostToolUse(Bash) → `bin/compact.py`

1. Parse the Bash result into a Delta string via `parse_delta_with_paths(cmd)` — regex-driven, captures both the human-readable delta (`pip install`, `mkdir foo`) and the affected paths.
2. Update `state/scratchpad.json`:
   - `last_command`, `exit_code`, `delta`, `timestamp` always overwritten.
   - On success (`exit_code == 0`): dedupe-append the captured paths to `paths_touched` (capped at 200 FIFO).
   - On failure: append a `failed_hypotheses[]` entry with the first matching error line. Never softened.
3. Emit `additionalContext` containing `COMMAND_RESULT:`, `STATE_DELTA:`, `ANCHOR: Active Spec is '<path>'. Step <N>.`, and `NEXT:` lines. Total payload capped under ~500 chars for typical commands.

The hooks **never read or write** the active spec body itself — only the pointer and the scratchpad. This is what makes them safe to run on every session and every Bash call.

## Skill protocols

### `/vision <text>` (`skills/vision/SKILL.md`, ~410 lines)

```
Step 0    Codebase fingerprint        → state/local-symbols.json + template surfacing
Step 0.5  Cognitive-substrate wizard  4 mandatory §8.2 questions; cached by author-spec-hash
Step 1    Receive intent              (user input)
Step 2    Feasibility Audit (silent)  refuse if physically impossible
Step 3    Initialize the walker       init-or-resume state/.walk.json
Step 4    Walk loop (interrogation)   peek-pending → question → answer-concern → yield-check
                                      Loop until: stop / Tier 3 yield-delta converged /
                                      max-rounds / per-receiver exhausted
Step 5    Materialize draft + confirm render from state.answered → .spec.md.draft
                                      Confirm: yes / refine "<change>" / cancel
Step 6    Draft-to-disk               atomic write <slug>.spec.md.draft
Step 6.3a First-run setup wizard      ensure ~/.spectre/reviewer.toml exists
Step 6.4  Pre-lock Evaluator          ── see "Evaluator pipeline" below ──
          Tier 1 spec_ast (AST)
          Tier 2 coverage_gate (structural)
          Tier 3 llm_judge (DeepSeek, opt-in)
          Halt on any block-severity finding.
Step 6.5  ADR generation              decisions/<NNNN>-<slug>.md per Decision marker
Step 6.6  Resource node inference     auto-detect port:N → res-port-<N> in .graph.md
Step 6.7  Lock                        atomic rename .draft → .spec.md
                                      flip specs/.active
                                      reset state/scratchpad.json (v2 shape)
                                      write <slug>.spec.md.eval.json sidecar
                                      clear state/.eval-bundle.json
                                      write <slug>.envelope.json handoff envelope
Step 7    Print VISION LOCKED transition signal
```

Two architectural commitments shape the protocol:

- **Draft → confirm → lock is explicit.** No silent locks. The user reads the draft on disk in their own editor before saying yes.
- **The evaluator's bundle is materialized once.** §6.4 builds a `ReviewBundle` containing preview ADRs, preview Resources, and tier classifications, persists it to `state/.eval-bundle.json` keyed by the draft's SHA-256, and §6.5/§6.6/§6.7 read from it. No recomputation; if the draft changes between steps, the SHA mismatch forces a re-run.

### `/implement [check | auto] [<track>]` (`skills/implement/SKILL.md`, ~520 lines)

```
Step 0    Mode routing                parse check / auto / track args
Step 0.5  Track selection             default = "default"
Step 0.7  Tier 0 handoff integrity    validate <slug>.envelope.json before reading spec
                                      Halt: ENVELOPE TAMPERED / schema violation
Step 1    Read context                .active + scratchpad[track]
                                      Halt: SPEC COMPLETE if all steps verified
Step 1.5  Environment setup           ensure_venv + normalize_action rewrites
                                      Halt: VENV CREATION FAILED (no fallback)
Step 2    Pre-flight re-verify        re-run prior step's verification
                                      Halt: ROOT-STATE DESYNC on fail
Step 3    /implement check branch     verify-only, no scratchpad write
Step 3.5  Persistence-tier classifier  bin/tier.py — silent/repo/host/network/NA
                                      Halt+ask on host, network, or never-autonomous
Step 3.5b Post-halt-success prompt    adopt / once-only / never-ask-again (v0.4.1+)
                                      sandbox-paradox brake at 3 adoptions/session
Step 3.6  Resource lock acquire        bin/track.acquire() via UDS to supervisor
                                      Halt: RESOURCE QUEUED if at capacity
Step 3.7  Reasoning-in-Public          print "WHY: <why text>"
Step 4    Execute action               Bash → PostToolUse hook fires compact.py
Step 5    Verification gate            run verification:; halt on non-zero
Step 5.5  State Auditor                bin/auditor.py PBT-lite checks (informational)
Step 6    Branch on result
          Path A (pass):  advance step, CDLC ledger implement entry
          Path B (fail):  one Option-B retry with diagnosis, then halt
Step 6.5  Drift checkpoint             every 5 successful steps
                                       re-read §1, audit next batch
                                       Halt: DRIFT DETECTED on concern
Step 6.7  Release locks                bin/track.release() on terminal step state
Step 7    Failure logging              append to scratchpad.failed_hypotheses[]
Step 7.5  Spectre-finding capture      Path B retry succeeded → prompt project/spectre
```

The persistence-tier gate (§3.5) is the single source of truth for halt-vs-execute. v1 used a regex risk-gate inline in the skill prose; v0.2.1 replaced it with `bin/tier.py` so the rule set is testable and project-overridable.

**v0.3.1 NEVER_AUTONOMOUS additions** (closes [#1](https://github.com/Joncik91/Spectre/issues/1) gap 6): `systemctl <verb>` (start/stop/restart/reload/enable/disable/mask/unmask, with `--user`/`--system` flag tolerance), `loginctl enable-linger` / `disable-linger`, `hostnamectl set-*`, `timedatectl set-*`, `sysctl -w`. v0.3.0 missed these because the verb regex only checked the binary name; the v1.1.0 BTC proxy test run hit three host-state-mutating systemctl invocations that the classifier treated as `silent` until the agent applied judgment-override.

**v0.3.1 loopback downgrade** (closes [#1](https://github.com/Joncik91/Spectre/issues/1) gap 9): `_is_network()` now parses URLs in argv. `127.0.0.1`, `localhost`, `[::1]`, `0.0.0.0`, and RFC1918 (`10.*`, `172.16-31.*`, `192.168.*`) downgrade `curl`/`wget` to path-tier classification on the output file. The packet never leaves the kernel; halting is pure friction. Variable URLs (`$VAR`) keep network tier — false-positive is the safe default.

## Evaluator pipeline (v0.3.0)

```
draft.spec.md.draft
        │
        ▼
   build_bundle()                     ← spec_evaluator.py
        │
        ├──→ Tier 1: spec_ast.classify(draft_path)
        │       Pure parse/structure/tautology checks.
        │       Imports NOTHING from bin/tier or bin/resources.
        │       Findings: missing-why, soft-verification,
        │                 action-not-probed, missing-receiver-calibration.
        │
        ├──→ Tier 2: coverage_gate.classify(draft_path,
        │                                   preview_adrs=preview_adrs)
        │       Cross-checks §8.1 calibration vs action path captures.
        │       Findings: undeclared-resource (warn),
        │                 undeclared-host-path (block),
        │                 calibration-hard-violation (block),
        │                 decision-without-adr (warn, deterministic).
        │
        └──→ Tier 3: llm_judge.evaluate(spec_text, config=…)
                Single JSON-only API call to DeepSeek deepseek-v4-flash.
                Contradiction-tuple protocol — 10 kinds + unrecognized fallback.
                CoT faithfulness cite-and-verify pass (zero extra API calls
                  when no block tuples exist).
                Never raises. All failures become a single
                tier3-unavailable info-severity sentinel finding.
        │
        ▼
   ReviewBundle                       persisted at state/.eval-bundle.json
        │                              keyed by draft SHA-256
        ▼
   evaluate(draft, config_path, persist_dir) → EvaluatorResult
        │   - apply severity overrides (one-way: raise only)
        │   - filter dismissals by stable fingerprint
        │   - return findings + sidecar_payload
        ▼
   /vision §6.4 halts on block-severity findings; otherwise continues to §6.5.
```

**Why three tiers?**

- Tier 1 is **deterministic and free**. Catches the cheapest mistakes (missing `why:`, soft verifications) before any LLM call.
- Tier 2 is **structural and free**. Cross-checks the §8.1 hard contract against actions' path captures. This is where most real bugs hide — a step that mutates `/etc/systemd/system/` while the spec only declares `mutates: /opt/btc-poller/` is a calibration gap that no syntax checker would notice.
- Tier 3 is **semantic and paid**. DeepSeek is structurally other-than-Claude — different training distribution, different blind spots, different priors. The adversarial-reviewer principle: same-family review has correlated blind spots; different-family review breaks the correlation. Costs are capped (`budget_tokens_per_spec`) and opt-in (`enabled = false` by default).

**Stable fingerprints, dismissable findings.** Every finding has a SHA-256 fingerprint over `{tier, kind, scope, step, steps, ref}` — message text is deliberately excluded so LLM nondeterminism doesn't break dismissals. A user dismisses a Tier 3 finding by appending `# tier3-dismissed: <fingerprint> "<reason>"` to the spec; the next evaluator run skips that finding. Tier 1 and Tier 2 findings are `dismissable=False` — structural rules don't get to be argued away.

## Interrogation walker (v0.4.0)

`bin/walker.py` is the strict-hybrid state machine that drives `/vision` Steps 1–5. It owns walk state, branching, dependency-tracked invalidation, and stop conditions. The skill phrases the walker's structured Concerns into natural-language questions; the walker is canonical, the rendered question is best-effort.

Stop conditions (any triggers halt; evaluated in this deterministic order):

1. Author types `stop` → `stop_reason = "author-arbitrated"`.
2. Tier 3 yield-delta converged (3 consecutive rounds <2 new findings).
3. Max-rounds hit (default 30, configurable in `~/.spectre/walker.toml`).
4. Per-receiver exhaustion (no non-stale pending concerns remain).

State persists at `state/.walk.json` (atomic JSON write — same pattern as `bin/_scratchpad.atomic_write`). A walk in progress survives session interruption. Revising an earlier answer marks all transitively-dependent concerns `stale`; the walker skips stale concerns in `next_concern`. The author sees the invalidated set as a diff and chooses re-walk or accept-stale.

`init_walk` seeds five concerns: one `assumption-surface` (round 1: surface unstated assumptions in the intent) plus four `receiver-clarification` concerns covering the §8.1 hard contract (mutates, never-touches, decision-budget, reboot-survival). The downstream evaluator (§6.4) requires these fields; seeding them at walk-init guarantees they're answered before draft materialization.

Reference:
- Design: `docs/superpowers/specs/2026-05-06-spectre-v0.4-cdlc-closure.md`
- Plan: `docs/superpowers/plans/2026-05-06-v0.4.0-walker.md`

## Observe + Adapt (v0.4.1)

`bin/observations.py` and `bin/personal_rules.py` close two of the three remaining CDLC legs (Distribute is v0.4.2).

**Observe.** Every TIER GATE halt in `/implement` records a structured row to `~/.spectre/observations.jsonl`: timestamp, fingerprint, classifier_label, project_path, spec_slug, action. The log is append-only and per-user (not per-project) so recurring halt patterns surface across all the user's Spectre projects. `find_recurrences(threshold=N)` returns fingerprints recurring ≥N times — consumed by v0.4.2's Adapt template-patch flow.

**Adapt.** `~/.spectre/personal-rules.toml` is the per-user TOML override store. The `/implement` post-halt-success prompt (§3.5b) is the only sanctioned writer. `bin/tier.should_halt()` consults `personal_rules.is_classifier_halt_overridden()` for every host/network-tier halt:

1. `never_autonomous_match` is non-overridable — those rules are never downgraded.
2. If the action's classifier reasons reference any path in the active spec's §8.1 hard contract (`spec_locked_paths`, parsed via `bin/coverage_gate.parse_81_block`), the personal-rule cannot override — spec rules are immune.
3. Otherwise, if the `(classifier_label, fingerprint)` pair has an entry in personal-rules.toml, the halt is downgraded.

**Sandbox-paradox brake.** Per `research/developing-a-safe.md` (vault), HITL approval gates create permission-fatigue (users rage-bypass safety). v0.4.1 caps adoptions at 3 per session before the post-halt prompt stops firing, requiring the user to manually review `personal-rules.toml`. The counter is **persisted per-track** in `state/scratchpad.json["tracks"][<track>]["session_adoption_count"]` — surviving the per-heredoc Python subprocess fork that would otherwise reset module-state. Reset only by manually clearing the field or via the test helper `personal_rules.reset_session_adoption_count_persistent()`.

Reference:
- Design: `docs/superpowers/specs/2026-05-06-spectre-v0.4-cdlc-closure.md` §6.3, §6.4
- Plan: `docs/superpowers/plans/2026-05-06-v0.4.1-observe-adapt.md`

## CDLC Ledger + Distribute + Adapt-Patches (v0.4.2)

`bin/cdlc_ledger.py`, `bin/templates.py`, and `bin/template_patcher.py` close the third leg of the CDLC.

**Ledger.** Every Generate→Test→Lock→Implement→Halt→Adapt transition is appended to per-project `state/cdlc-ledger.json` via atomic write. Read-only audit surface — no user-facing command. Call sites: `/vision` §6.7 (lock=generate), `/implement` §6 Path A (implement) and §3.5 (halt), `bin/observations.record_halt` (halt), `bin/personal_rules.append_adoption` (adapt).

**Distribute.** `~/.spectre/templates/{specs,skills}/` is the per-user template store. `bin/templates.import_template` copies a stored template into a new project (specs land at `./specs/<name>.spec.md.draft` so the /vision flow still gates the lock; skills land at `./skills/<name>.md`). `bin/templates.export_template` is the reverse. Local-only — remote sync is still deferred (not in v0.5 or v0.6; tentatively v0.7+).

**Adapt-patches.** When `observations.find_recurrences(threshold=3)` returns recurring halt fingerprints AND those fingerprints aren't already covered by `personal_rules`, `bin/template_patcher.detect_patch_candidates` lists them and `template_patcher.propose_patch` writes a markdown patch to `~/.spectre/template-patches/proposed/<slug>.md`. SessionStart's `bin/hydrate.surface_pending_template_patches` reports the count; `bin/hydrate.detect_and_propose_patches` writes new proposals at session start. Manual accept/reject only.

**Deferred-prompt durability.** `bin/_scratchpad.track_default()` gains `pending_adoption_prompt: dict | None`. /implement §3.5 writes this on TIER GATE halt + user=yes; §3.5b reads it post-Path-A and clears FIRST (before adopt-write) so an adopt-write failure does not strand the prompt for replay next session.

Reference:
- Design: `docs/superpowers/specs/2026-05-06-spectre-v0.4-cdlc-closure.md` §6.5, §6.6
- Plan: `docs/superpowers/plans/2026-05-06-v0.4.2-cdlc-distribute.md`

## Resource-lock supervisor (v0.2.2)

For multi-track projects (`/implement payments`, `/implement notifications`), Spectre runs a per-project Unix domain socket daemon at `runtime/supervisor.sock`:

- **Spawn-on-demand.** First `/implement <track>` call detects no live supervisor, double-forks one, waits for the socket, then dials in.
- **Idle self-shutdown.** No requests for 30 minutes → daemon exits.
- **Reboot recovery.** PID-file + `/proc/<pid>/stat` actor fingerprinting reaps stale locks left by SIGKILL'd or rebooted-out actors. Reconcile is idempotent.
- **Single-threaded `select()` loop.** No concurrency primitives, no thread pools, no race conditions to debug. Stdlib only.

Resource nodes live in `specs/.graph.md`:

```yaml
---
id: res-port-8080
type: resource
title: HTTP server bound to TCP 8080
status: active
edges: []
---
```

Steps reference them via `resources: [res-port-8080]`. The supervisor grants the lock (or queues the requester) before §3.7 fires the WHY emit and the action runs. Released after §6 verification passes — or on terminal halt.

## Spec template anatomy (`specs/template.spec.md`)

```
§1  Hard Problem            one-paragraph non-obvious challenge
§2  First Principles        3–7 bullets (physics/logic, no analogies)
§3  Algorithm Audit         Delete / Simplify / Accelerate
§4  Speed-of-Light Limit    one paragraph: the physical ceiling
§5  Physics Guardrails      system invariants
§6  Steps                   YAML list: why/action/verification (+ properties, resources)
§7  Success Criteria        binary checklist
§8  Receiver Calibration    8.1 hard contract (machine-enforced)
                            8.2 human notes (informational)
```

§8.1 is the load-bearing addition from v0.3.0. The four required fields — `mutates`, `never-touches`, `decision-budget`, `reboot-survival` — are cross-checked by Tier 2 against every action's path captures. This is what catches "the spec said it would only touch `/opt/foo/` but step 7 writes to `/etc/`" before any code runs.

## Failure modes and mitigations

| Failure | Mitigation | Test |
|---|---|---|
| Broad PostToolUse matcher fires on every tool | matcher: `"Bash"` exact; not regex | `test_compact.py` |
| Hydrator dumps full scrollback into context | hydrator emits only spec body + STATE line | `test_hydrate.py` |
| Verification fail loops forever | one Option-B retry, then hard halt | `test_e2e.py` |
| Concurrent writes to scratchpad corrupt JSON | atomic write via mkstemp + os.replace | `test_scratchpad.py` |
| `additionalContext` payload bloats | length-cap + path FIFO at 200 entries | `test_compact.py` |
| Stale lock from SIGKILL'd actor blocks track | `/proc/<pid>/stat` fingerprint reconcile | `test_supervisor.py` |
| Drift across 20+ step specs | every-5-steps drift checkpoint re-reads §1 | `test_e2e.py` |
| LLM finding dismissals broken by nondeterminism | fingerprint excludes message text | `test_findings.py`, `test_dismiss_integration.py` |
| Severity downgrade in user config | `validate_no_severity_downgrade` raises ValueError | `test_eval_metadata.py` |
| Tier 3 outage crashes evaluator | all errors → tier3-unavailable info sentinel | `test_llm_judge.py` |

## Design rationale

Three principles drive every choice:

1. **Determinism first.** Anything that can be a deterministic check (Tier 1, Tier 2, the persistence-tier classifier, atomic file ops) is one. LLM calls happen at one well-defined gate, not scattered through the protocol.
2. **Atomic transitions.** Every state change is `mkstemp + os.replace` or equivalent. There is no torn-write window where the active spec is half-flipped or the scratchpad is half-updated.
3. **Adversarial review at the spec layer.** Code review catches code bugs; spec review catches spec bugs. v0.3.0 ships the spec-review layer because the cost of a wrong spec is N steps of wrong implementation, and the cheapest place to halt is before lock.

For the historical context behind specific decisions, see `docs/superpowers/specs/` (architecture briefs) and `docs/superpowers/plans/` (implementation plans). Both directories are archival — they record what was built and why, not what to do next.

## CLI surface + heredoc elimination (v0.5.0)

**Hard problem:** skill prose contained 20 `python3 - <<'PY' ... PY` heredoc blocks that forked fresh interpreter processes, bypassed argparse schemas, and let slug substitutions, path drift, and inline `Path(...)` constructions silently diverge from the underlying `bin/` functions they called. Any bug in the heredoc was invisible to the test suite.

**Design decision:** Every heredoc becomes a `python3 -m bin.<module> <subcommand>` invocation against a versioned CLI surface. No new business logic — only `__main__` entry points wrapping existing public functions. The CLIs ship in PRs #18 (Phase 2A), #19 (Phase 2B), #20 (Phase 2C), and #33's predecessor (Phase 2D).

**Load-bearing files:**

- `bin/cdlc_ledger.py`, `bin/observations.py`, `bin/_scratchpad.py`, `bin/personal_rules.py`, `bin/track.py`, `bin/adr.py`, `bin/templates.py`, `bin/setup_wizard.py`, `bin/walker.py` — all gained `__main__` entry points in v0.5.0.
- `tests/test_skill_prose_no_heredoc_python.py` — drift-prevention guard; per-file ceilings tightened to zero. Any future `python3 - <<'PY'` in `skills/**/SKILL.md` breaks CI immediately.

**Cumulative effect:** 20 heredocs gone, ~192 LOC removed from skill prose, 928 tests at release.

References: Issue #13 (closed), `docs/superpowers/audits/2026-05-06-issue-13-heredoc-audit.md`.

## Deterministic gap-closers + executor-owned venv (v0.5.2)

**Hard problem:** the v0.5.1 live test of yt-readable surfaced five gap classes (A–E) where the pre-lock evaluator returned `PASS` but `/implement auto` halted on bugs the evaluator should have caught: uncreated artifacts (Gap A), import-before-install (Gap B), scaffold-without-implementation (Gap C), unparseable Python in verifications (Gap D), and PEP 668 / venv isolation (Gap E). Per Copilot/GPT-5.4 peer review (#32): the fix is deterministic contracts + executor-owned environment + hard gating, not prose-inferred graphs.

**Design decisions:**

1. **Executor-owned venv** (`bin/managed_venv.py`). The implementor creates and owns `state/.venv/` (mode 0700) rather than relying on the system Python. `normalize_action` rewrites action head-tokens to use the venv Python, preserving shell operators byte-identical. Stale `pyvenv.cfg` (e.g. after Python upgrade) triggers HALT rather than silent misbehavior.

2. **Explicit step contracts** (`produces:` / `requires:`). Eight contract types: `file:`, `package:`, `console-script:`, `route:`, `module:`, `binary:`, `db-table:`, `db-column:`. Tier 1 cross-validates `requires:` against prior `produces:`. Mismatch → block `unowned-requirement`. Steps with no contracts → warn `missing-contract` (backward-compatible). `contract_resolution` block added to `.eval.json` sidecar.

3. **Tier 1 deterministic gap-closers.** `verification-syntax-error` (block) — every `python3 -c "<body>"` compile-checked at lock time. `action-invokes-uncreated-artifact` (block) — absolute paths under `mutates:` with no prior authoring step. `unowned-requirement-heuristic` (block) — curl routes, HTML tags, SQL columns, Python imports with no prior owner. Allowlists for universal probes and `produces:` declarations shadow heuristics.

4. **Tier 3 contradiction-tuple protocol.** DeepSeek system prompt rewritten (~540 tokens) to force JSON-only output. Ten contradiction kinds + `unrecognized` fallback. Single API call replaces the prior three-prompt prose loop. `DEEPSEEK_MODEL` default changed from `deepseek-reasoner` → `deepseek-v4-flash` — structured I/O protocol doesn't need reasoner-style prose output.

**Load-bearing files:** `bin/managed_venv.py` (new), `bin/spec_ast.py` (contracts + gap-closers), `bin/llm_judge.py` (tuple protocol), `bin/eval_metadata.py` (contract_resolution in sidecar), `bin/spec_evaluator.py` (DEEPSEEK_MODEL default).

References: Issues #31 (gap classes), #32 (design brief + Copilot/GPT-5.4 review), PR #33.

## Handoff envelope + negative paths + CoT faithfulness (v0.6.0)

**Hard problem:** five vault concept pages mapped onto Spectre's weak points after v0.5.2 identified that the bytewise integrity of the vision→implement handoff was not enforced: the sidecar could be tampered or the spec body replaced without the executor noticing (Gap E from the v0.5.2 essay-followup).

**Design decisions:**

1. **Handoff envelope** (`bin/handoff_envelope.py` + `bin/handoff_validator.py`). A JSON-Schema-validated envelope wraps the vision→implement handoff. Schema: `protocol_version`, `receiver`, `spec_path`, `sidecar_path`, `policy_hash`, `spec_sha256`, `sidecar_sha256`, `contract_resolution`, `walker_yield_history`, `walker_stop_reason`, `decisions_indexed`, `integrity_hash`, `created_at`. The integrity hash covers the actual artifact bytes (spec.md + sidecar.eval.json), not just envelope metadata.

   Step 0.7 in `/implement` (`skills/implement/SKILL.md`) is the new Tier 0 check, inserted between Step 0.5 (track selection) and Step 1 (read context). Four outcomes: `envelope-missing` (warn — pre-v0.6 spec, allow), `envelope-tampered` (block — content modified after lock), `envelope-malformed` (block — schema violation), clean (proceed).

2. **Walker yield countdown.** `bin/walker.py` emits prediction-ready status lines: `"YIELD: round N added M new T3 findings; stopping when last K rounds all <T (currently: [a,b,c])"` instead of raw delta numbers. New `negative-path` concern kind + `generate_negative_path_concerns` with idempotency guard.

3. **Negative-path Tier 1 enforcement** (`bin/spec_ast.py`). New optional `negative-paths:` block per step (list of `{trigger, handler}` dicts). Tier 1 warns `missing-negative-path` when `produces:` is non-empty and `negative-paths:` is absent. Blocks when `reboot-survival: required` (data-loss hazard). Malformed-only entries under `reboot-survival: required` also escalate to block.

4. **Tier 3 CoT faithfulness** (`bin/llm_judge.py`). A single batched cite-and-verify pass runs after the primary contradiction tuples. Block-severity tuples (`missing-producer`, `shallow-ownership`) are demoted to warn `tier3-unfaithful-contradiction` if DeepSeek can't cite supporting spec text (case-insensitive substring). Parse failure → conservative: keep block, append `tier3-faithfulness-malformed` warn. Zero extra API calls when no block tuples exist.

**Load-bearing files:** `bin/handoff_envelope.py` (new), `bin/handoff_validator.py` (new), `bin/eval_metadata.py` (`write_envelope_alongside_sidecar()`), `bin/walker.py` (yield countdown + negative-path concerns), `bin/spec_ast.py` (negative-paths enforcement), `bin/llm_judge.py` (faithfulness pass), `skills/vision/SKILL.md` (Step 6.7 envelope write), `skills/implement/SKILL.md` (Step 0.7 Tier 0 check).

References: vault pages `concepts/context-as-cognitive-substrate.md`, `entities/standardized-handoff-envelope.md`, `entities/context-sled.md`, `entities/handoff-validator.md`, `entities/planner-generator-evaluator-triad.md`, `research/cot-monitorability.md`.

## PYTHONPATH consistency (v0.6.1)

**Hard problem:** skill prose's `python3 -m bin.X` invocations are run from the user's project cwd, where `bin/` may not be on `sys.path`. Without an explicit `PYTHONPATH="${CLAUDE_PLUGIN_ROOT}"` prefix, plugin-internal module resolution silently fails at runtime in any project that doesn't happen to have a `bin/` directory at cwd (issue #30).

**Fix:** every `python3 -m bin.X` invocation in `skills/vision/SKILL.md` and `skills/implement/SKILL.md` now carries the `PYTHONPATH="${CLAUDE_PLUGIN_ROOT}"` prefix. A PYTHONPATH note section at the top of both skill files explains the requirement. CI sentinel `tests/test_skill_pythonpath_consistency.py` scans all `skills/**/SKILL.md` bash code blocks and asserts every `python3 -m bin.X` line carries the prefix.

References: Issue #30 (closed).

## Contract-shadow precision + Tier 3 silent-fail recovery (v0.6.2)

**Hard problem:** the v0.6.1 retest of an activity-ingestion-daemon spec surfaced two bugs that defeated whole evaluator subsystems silently. (1) Tier 1's heuristic shadow couldn't suppress an `unowned-requirement-heuristic` block when a step verified `from spectre_daemon.blocklist import is_blocked` because `_PYTHON_IMPORT_ALT_RE` was matching the SYMBOL `is_blocked` as a module name — unmatched against `declared_modules`, fired anyway. (2) Tier 3 silently degraded for any user whose `~/.spectre/reviewer.toml` predated v0.5.1: stale `model = "deepseek-reasoner"` returned HTTP 401 against the user's plan, and `llm_judge` reported it as `socket-timeout — DeepSeek unreachable`, sending debug effort toward network instead of credentials.

**Fixes (issues #36, #37):**

1. **Contract-shadow precision.** `bin/spec_ast.py` now skips `_PYTHON_IMPORT_ALT_RE` matches whose start lies inside a span already matched by `_PYTHON_IMPORT_RE` (the `from X import Y` form). Parent-prefix match is added to both contract resolution (`unowned-requirement` block check on declared `requires:` entries) and the heuristic shadow: `package:foo` satisfies `module:foo.bar`; `module:foo.bar` satisfies `module:foo.bar.baz`. Three regression tests in `test_spec_ast_v052_gaps.py`.
2. **Stale reviewer.toml auto-migration.** `bin/setup_wizard.maybe_provision()` no longer treats every existing config as authoritative. It detects (a) `model in {deepseek-reasoner, deepseek-chat}`, (b) missing `chunk_timeout_s`, (c) missing `total_timeout_s`. Any one trips migration: backup written to `reviewer.toml.bak-<timestamp>` (mode 0600), config rewritten with current defaults (`deepseek-v4-flash` + chunk/total split timeouts), preserving the user's `enabled` flag and `api_key_env`. Returns new outcome `"migrated"`. Stderr breadcrumb points at the backup. Five regression tests in `test_setup_wizard.py`.
3. **Tier 3 error-class disambiguation.** `bin/llm_judge.evaluate()` now classifies `urllib.error.HTTPError` exceptions: `401`/`403` → `"auth failure (HTTP NNN — check ~/.spectre/secrets.env or DEEPSEEK_API_KEY)"`, `400` → `"bad request (model X may be unavailable on your plan)"`, `5xx` → `"provider error (HTTP NNN)"`, anything else → `"http-NNN"`. Network/timeout paths unchanged. Four regression tests in `test_llm_judge.py`.
4. **Auth-failure prominence.** `skills/vision/SKILL.md` Step 6.4 now requires a `⚠ Tier 3 unavailable due to auth — fix ~/.spectre/secrets.env or DEEPSEEK_API_KEY then re-run /vision.` banner ABOVE the `tier 1/2/3` status block whenever the `tier3-unavailable` finding's message contains the substring `auth failure`. The banner makes credential issues actionable without scanning the findings list.

`EVALUATOR_VERSION = "0.6.2"`. 1364 tests pass.

References: Issues #36, #37 (closed). PR #39, release v0.6.2.
