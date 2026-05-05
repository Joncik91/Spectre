# Post-v0.2.2 follow-ups (parking lot)

**Date:** 2026-05-05
**Status:** Ideas — not yet plan-able. Promote to `plans/` only if scope grows beyond a single commit.

These items came out of Plan C self-review and the v0.2.2 first-production E2E run. Each is worth fixing eventually but none on its own justifies a v0.2.3 plan unless explicitly noted.

**Plan D / v0.3 thesis (separate from this list):** the architectural move is a pre-lock spec evaluator (Pragma-pattern at the spec layer instead of the test layer). Three tiers — AST-classifier, action↔verification coverage, DeepSeek adversarial reviewer. Item #5 below is **superseded** by Plan D because the evaluator catches classifier holes at spec-author time, before they can mis-fire at /implement. Items #1-#4 remain orthogonal to Plan D.

## 1. Lock TTL enforcement

**Scope:** the supervisor defines `GRANT_TIMEOUT_SECONDS = 300` but never enforces it. A track that grabs `port:8080` and crashes silently (e.g. its calling Claude session is killed without sending a release) holds the lock until the next supervisor restart triggers reconciliation.

**Fix shape:** in `serve()`'s `select()` loop, every N seconds sweep `state._holders` and reap any holder whose `actor_pid` is no longer alive (`_actor_alive` returns False). Same logic as `reconcile()` but in-loop, not just on startup. Track-side: `bin/track.py` should send periodic `heartbeat` ops while a step's action is running, so even a frozen-but-alive track is distinguishable from a dead one.

**Why it's not a plan:** ~30 LOC + 2 tests. Single commit. The hard part is choosing the sweep interval (10s? 60s?) and whether heartbeat is required vs optional. That's a 5-min design call, not a planning round.

**Trigger to promote to plan:** if you also want lock priorities (high-priority tracks jump the queue) or per-Resource TTL overrides.

## 2. Auto-promotion notifications

**Scope:** when track A releases `port:8080`, the supervisor promotes queued track B. Today, B has no idea — the user must re-invoke `/implement <track-b>` for B to learn it now holds the lock and can proceed.

**Tension with the "no-manual-invocation-required" rule:** the current shape requires the user to remember to retry. That's exactly the kind of manual step the rule says to avoid.

**Possible designs (none locked):**
- **PostToolUse hook** that runs `track.status` after every Bash, prints `PROMOTED: <track>` if a promotion happened since last check. Zero new mechanisms.
- **Filesystem signal:** supervisor writes `state/<track>.promoted` on grant; a SessionStart-time check reads + clears them.
- **Push notification** (Telegram via existing `claude-notifier`) — works but only useful if you're watching the phone, not the terminal.
- **Long-poll inside `track.acquire`:** when queued, block for up to N seconds waiting for a grant before returning. Changes the API contract significantly.

**Why it's not a plan yet:** the right answer depends on whether you actually run two tracks in parallel often enough to hit this. The current single-user pattern is "one track at a time," in which case the queue is mostly cosmetic and the notification problem is low-priority.

**Trigger to promote to plan:** when a real two-track session has happened twice and the queue blocked you.

## 3. In-loop dead-actor sweep (overlaps with #1)

**Scope:** `LockState.reconcile()` only runs at supervisor startup. If a holding track's process dies during normal supervisor operation, the lock sits dead until either the next restart or a release op for that track lands (which won't, because the track is dead).

**Fix shape:** essentially a subset of #1. The TTL sweep is exactly this sweep, just with a heartbeat-based deadness criterion instead of a /proc-based one.

**Why separate from #1:** noting it because the bug exists even without TTL enforcement — `_actor_alive` is the cheap, always-correct deadness check. A 60s in-loop sweep that calls `_actor_alive` on every holder is sufficient. Heartbeat (#1) is only needed to catch *frozen* actors (alive PID, dead behavior), which is a less likely failure mode for short-lived `/implement` step actions.

**Recommended ordering if these get implemented:**
1. In-loop `_actor_alive` sweep (this item, ~15 LOC).
2. Heartbeat-based liveness on top (item #1, +15 LOC + protocol bump).
3. Notifications (item #2) — only after a real workflow demands it.

## 4. External-holder detection for port Resources

**Scope:** the supervisor grants `res-port-N` based on its own internal capacity tracking. It does not check whether port N is *actually free on the host*. Real failure observed during v0.2.2 E2E test (2026-05-05): the spec asked for port 8765, supervisor granted the lock, smoke test failed because `rule-router` daemon already owned 8765 — supervisor had no way to know.

**Fix shape:** when a Resource of `kind=port` is registered, `supervisor.register_resource` should attempt a non-blocking `bind()` probe on `127.0.0.1:<port>`. If the bind fails with `EADDRINUSE`, refuse to register (raise `ResourceConflict`) so the calling track halts before executing. Probe is cheap (~ms) and run-once-per-Resource per supervisor lifetime.

**Why it's not (just) a plan:** ~30 LOC. But it changes the lock semantics from "Spectre-internal mutex" to "Spectre-internal mutex + host-level reality check." That's a small contract bump. Worth its own commit + a `tests/test_supervisor.py` regression test that registers a port, opens an external bind on it, registers again, expects refusal.

**Trigger to promote to plan:** if you also want external-holder detection for non-port Resources (DB pool exhaustion, API quota burned externally) — those have no cheap probe.

## 5. ~~Tier classifier misses bare `systemctl` / `journalctl` / `udevadm`~~ — SUPERSEDED BY PLAN D

**Status:** retained for history. Plan D's pre-lock spec evaluator (DeepSeek adversarial reviewer + AST classifier) catches host-mutation actions at spec-author time, before the runtime tier classifier ever sees them. The runtime classifier becomes a fallback, not the primary gate. Patching `bin/tier.py` for `systemctl` / `journalctl` would help the fallback marginally — worth a 1-line follow-up if Plan D ships, but no longer urgent.

**Original observation (kept for record):** the v0.2.2 `bin/tier.py` classifies actions by path captures plus the Never Autonomous verb list. `systemctl daemon-reload` has no path → falls through to `silent`. Step 5 of the BTC poller spec hit this; Step 6 (`systemctl enable --now btc-poller.service`) was classified as `repo` because `btc-poller.service` looked like a project-relative file. Implementer overrode both via judgment (allowed: agents may add halts, never skip them).

## 6. Pre-lock spec evaluator — context completeness (Plan D / v0.3 thesis)

**Scope:** the gap between a draft spec and a *complete* spec is invisible to the spec author (your essay: spec authors have blind spots; the reviewer is the structural answer). v0.3 closes that gap with a pre-lock evaluator that fires between `/vision` draft and lock. Architecture is borrowed from `apps/Pragma/` (AST + structural gate + LLM judge), but the **target failure mode is different**: Pragma checks test→code coverage; Spectre v0.3 checks **spec→action completeness** — every action has a `why`, every host-touching action has a tier-correct declaration, every resource is declared, every decision generates an ADR, no soft verifications. This is CDLC's Evaluate phase, currently missing from Spectre. Real failures observed during v0.2.2 E2E that an evaluator would have caught at draft time:

- "Soft" verifications that don't actually probe what the action did (e.g. `verification: echo done`, `verification: true`).
- Action↔verification mismatch — verification grep for a string the action never emits.
- Resource declarations that don't match the action's actual binds (Step 2 in the BTC E2E missed `res-port-9100` until manual refine).
- Decision markers in §2 that don't generate ADRs because the regex is too narrow.

**Fix shape (becomes Plan D / v0.3 spec brief):**

- **Tier 1 — AST classifier.** Parse the spec's YAML steps, walk every `action`/`verification` pair, structurally check for tautologies (`echo done`, `true`, `[ 1 -eq 1 ]`), action-effect not probed by verification, undeclared host paths, undeclared ports. Always on, deterministic, ~10ms.
- **Tier 2 — coverage-of-action gate.** Dry-run-classify every action via `bin/tier.py` and `bin/resources.extract_resources_from_action`, then check the spec's `resources:` declarations cover the inferred set. Mismatch = finding. Opt-in.
- **Tier 3 — LLM judge via DeepSeek v4 Pro** (NEVER local — user policy: no local LLM when away from home, thermal risk). OpenAI-compatible API call. Three-prompt structured probing per the previous turn: (a) what the spec doesn't say, (b) what the spec asserts that's wrong, (c) attacker view. Output is structured JSON `findings: [{kind, severity, ref}]` — no narrative reviews reach the lock decision.

**Authorship discipline:** the evaluator's findings are not narrative — they're machine-checkable JSON. The pragma-test-gaming-guard pattern (typed findings, no prose review) is borrowed *as a defense against same-family LLM blind-spot collapse*: a Claude-authored spec reviewed by another Claude can't paper over weaknesses with co-narrative because the verdict is structured. DeepSeek as Tier 3 reviewer is the genuinely-different-distribution check.

**Why this becomes a real plan, not just an item:** ~600 LOC total, 3 new modules (`bin/spec_evaluator.py`, `bin/spec_ast.py`, `bin/llm_judge.py`), opt-in tier 2/3 config in `~/.spectre/reviewer.toml`, integration into `/vision` between draft and lock confirmation. That's a Plan D ship.

**Trigger to promote to plan:** already met — see `docs/superpowers/specs/2026-05-05-spectre-v0.3-spec-evaluator.md` (when written).

## What's NOT here

These came up during review but are out of scope for any plausible Plan D:

- Cross-machine state sync (Raft) — defer to v3, requires a real Raft implementation.
- Lock priorities / SLA queues — premature.
- Token-cost telemetry per track — Plan C scope creep, not yet motivated.
- Spec versioning beyond ADR supersedes — ADRs cover the actual need.
