# Post-v0.2.2 follow-ups (parking lot)

**Date:** 2026-05-05
**Status:** Ideas — not yet plan-able. Promote to `plans/` only if scope grows beyond a single commit.

These three items came out of Plan C self-review. Each is worth fixing eventually but none on its own justifies a v0.2.3 plan.

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

## What's NOT here

These came up during review but are out of scope for any plausible Plan D:

- Cross-machine state sync (Raft) — defer to v3, requires a real Raft implementation.
- Lock priorities / SLA queues — premature.
- Token-cost telemetry per track — Plan C scope creep, not yet motivated.
- Spec versioning beyond ADR supersedes — ADRs cover the actual need.
