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

### `/vision <text>` (`skills/vision/SKILL.md`, ~350 lines)

```
Step 0   Codebase fingerprint        → state/local-symbols.json
Step 1   Receive Spark               (user input)
Step 2   Feasibility Audit (silent)  refuse if physically impossible
Step 3   First-Principles draft + 2–3 refinement Qs (multi-turn)
Step 4   Draft steps with why/action/verification (5–15 steps)
Step 5   Confirm: yes / refine "<change>" / cancel
Step 6   Draft to disk: <slug>.spec.md.draft (atomic write)
Step 6.4 Pre-lock Evaluator           ── see "Evaluator pipeline" below ──
         Tier 1 spec_ast (AST)
         Tier 2 coverage_gate (structural)
         Tier 3 llm_judge (DeepSeek, opt-in)
         Halt on any block-severity finding.
Step 6.5 ADR generation               decisions/<NNNN>-<slug>.md per Decision marker
Step 6.6 Resource node inference      auto-detect port:N → res-port-<N> in .graph.md
Step 6.7 Lock                         atomic rename .draft → .spec.md
                                      flip specs/.active
                                      reset state/scratchpad.json (v2 shape)
                                      write <slug>.spec.md.eval.json sidecar
                                      clear state/.eval-bundle.json
Step 7   Print VISION LOCKED transition signal
```

Two architectural commitments shape the protocol:

- **Draft → confirm → lock is explicit.** No silent locks. The user reads the draft on disk in their own editor before saying yes.
- **The evaluator's bundle is materialized once.** §6.4 builds a `ReviewBundle` containing preview ADRs, preview Resources, and tier classifications, persists it to `state/.eval-bundle.json` keyed by the draft's SHA-256, and §6.5/§6.6/§6.7 read from it. No recomputation; if the draft changes between steps, the SHA mismatch forces a re-run.

### `/implement [<track>]` (`skills/implement/SKILL.md`, ~320 lines)

```
Step 0.5  Track selection             default = "default"
Step 1    Read context                .active + scratchpad[track]
                                      Halt: SPEC COMPLETE if all steps verified
Step 2    Pre-flight re-verify        re-run prior step's verification
                                      Halt: ROOT-STATE DESYNC on fail
Step 3    /implement check branch     verify-only, no scratchpad write
Step 3.5  Persistence-tier classifier  bin/tier.py — silent/repo/host/network/NA
                                      Halt+ask on host, network, or never-autonomous
Step 3.6  Resource lock acquire        bin/track.acquire() via UDS to supervisor
                                      Halt: RESOURCE QUEUED if at capacity
Step 3.7  Reasoning-in-Public          print "WHY: <why text>"
Step 4    Execute action               Bash → PostToolUse hook fires compact.py
Step 5    Verification gate            run verification:; halt on non-zero
Step 5.5  State Auditor                bin/auditor.py PBT-lite checks (informational)
Step 6    Branch on result
          Path A (pass):  advance step, release locks
          Path B (fail):  one Option-B retry with diagnosis, then halt
Step 6.5  Drift checkpoint             every 5 successful steps
                                       re-read §1, audit next batch
                                       Halt: DRIFT DETECTED on concern
Step 6.7  Release locks                bin/track.release() on terminal step state
Step 7    Failure logging              append to scratchpad.failed_hypotheses[]
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
                Three prompts to DeepSeek v4 Pro:
                  tier3-context-gap, tier3-spec-asserts-wrong,
                  tier3-attacker-view.
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
