# Spectre v2 — Graph Orchestrator Architecture

**Date:** 2026-05-05
**Status:** Architecture Draft (pre-implementation)
**Predecessor:** `2026-05-05-sdl-vision-engine-design.md` (v1, shipped)

## Why v2

v1 proved SDL works at the script-task scale. Real-world testing this session shipped a 3-step `hello-file-writer` and an 8-step BTC price logger. Both worked, but the BTC test exposed four scaling failures: manual click-through dominates real work, `/vision` reasons from training data only, the spec model bottoms out at 5-15 steps, and the Risk-Gate regex is partial-coverage.

Two rounds of external rubberduck review (terse, adversarial, no flattery) reframed the problem: linear specs are a script-writer; a State-Tree (Graph Orchestrator) is an autonomous engineer. v2 builds the graph.

## The Eight Locked Decisions

### 1. Hierarchy: Invariants > Interfaces > Implementations

Drop Epic/Story (human-management hierarchy). Replace with:

- **Invariant** — physical/logical contract that downstream nodes must satisfy (e.g. "UserObject has fields email, password_hash, created_at"). First-class citizen.
- **Interface** — connection point between components (e.g. "auth service exposes `POST /login` returning JWT"). Defined once, consumed by many Implementations.
- **Implementation** — current `.spec.md` shape. Inherits Invariants from parents, satisfies one or more Interfaces.

**Sleeper risk (round 2):** Invariant Bloat → Logic Deadlock. Mitigation: Invariants must be expressible as testable assertions (no prose-only invariants). Auditor verifies the assertion in code at every Implementation.

### 2. Persistence-Tier replaces Risk-Gate regex

Drop the regex set entirely. Compute tier from the action's path captures:

| Tier | Scope | Default behavior |
|---|---|---|
| **silent** | gitignored paths, `/tmp/*`, scratchpad | execute, no halt |
| **repo** | git-tracked files in project root | execute, no halt |
| **host** | `/etc`, `/usr/local/bin`, systemd, ufw | halt, require yes |
| **network** | curl/wget, external API call, dns mutation | halt, require yes |

**Sleeper risk (round 2):** side-effect leak — `curl | bash` only touches `/tmp` (silent) but mutates remote state. Mitigation: the **Never Autonomous** list (Decision 8) catches these by intent regardless of tier.

### 3. Codebase Fingerprint mandatory in `/vision`

Before drafting any spec, `/vision` MUST run a tree walk + header parse + symbol map. Result: `state/local-symbols.json` mapping `{symbol_name: file:line}`. `/vision` references it before proposing any new function. Implements the user's "never reinvent the wheel" rule by construction.

**Round 2 extension:** semantic indexing (not just symbol maps). Embeds module docstrings + function signatures so `/vision` can find conceptually similar prior art, not just exact-name matches.

### 4. Decisions = ADR markdown files, versioned + supersedable

Replace the `decisions.json` ledger sketch with `decisions/<NNNN>-<slug>.md` ADR files. Each ADR has frontmatter:

```yaml
---
id: 0042
title: "Use postgres 16 for primary store"
date: 2026-05-05
status: accepted | superseded
supersedes: null  # or 0017
---
```

When the user confirms a `/vision` draft that contains a `decision:` line, the skill writes a new ADR. If the new decision contradicts an earlier one, the new one's `supersedes:` points at the old; the graph propagates an `invalidates` edge to all Implementations downstream of the old ADR.

**Sleeper risk (round 2 caught it):** without supersedes-edges, ADRs become a "museum" out of sync with code.

### 5. Per-track scratchpad + Supervisor process

Multi-session parallel `/implement <track>`. Scratchpad reshape:

```json
{
  "active_mission": "specs/.mission",
  "tracks": {
    "auth": {"step": 5, "active_spec": "specs/auth-001.spec.md", "...": "..."},
    "payments": {"step": 12, "active_spec": "specs/payments-003.spec.md", "...": "..."}
  },
  "decisions_index": "decisions/",
  "graph_snapshot": "specs/.graph.md"
}
```

A separate Python helper (`bin/supervisor.py`, NOT a hook — long-running) acquires Resource node locks (ports, DB connections, external API quotas) on behalf of tracks. Tracks request a Resource via the supervisor; supervisor either grants or queues. Resource locks are part of the graph (Decision 6).

**Sleeper risk (round 2):** Environment Race. Two tracks competing for port 8080 with no shared filesystem overlap still deadlock. Resource nodes close this.

### 6. Post-execution State Auditor with Property-Based checks

After every action+verification passes, the auditor runs a **separate** structured check derived from the action's path captures:

- File created: schema-validate JSON, AST-parse Python, lint shell
- Service started: `systemctl is-active` AND a property check (response code, expected output shape)
- Resource locked: actual lock state matches graph state

This catches zero-exit zombie state. PBT (Hypothesis-style) runs only on Implementations that declare a `properties:` field listing invariant-style assertions; otherwise auditor falls back to type/schema checks.

**Round 2 extension:** PBT moves from v3-deferred to v2 because the auditor needs it to be useful, not because formal methods are required.

### 7. Graph data model & storage

**Node types:** `Invariant`, `Interface`, `Implementation`, `Resource`
**Edge types:** `constrains` (Invariant → Implementation), `satisfies` (Implementation → Interface), `blocks` (Resource → Implementation), `invalidates` (event → node), `supersedes` (ADR → ADR)
**Storage:** markdown + frontmatter, parsed at session start into in-memory `dict[node_id, Node]` + adjacency list. Manifest file at `specs/.graph.md` (git-diffable, human-readable). Stdlib only.
**Query model:** `/implement` asks at step start:
- "List unverified `constrains` edges for this node."
- "Is the `Resource` node for port 8080 currently locked by another Actor?"
- "Are any upstream Invariants `STALE`?"

If any answer is "yes," halt with the graph excerpt as context.

### 8. Never Autonomous list + Atomic Rollback Unit

**Never Autonomous (always halt regardless of tier):**

1. Top-level dependency addition (new package, library, service)
2. Schema mutation (`ALTER TABLE`, destructive migration, drop column)
3. Permission/security change (`chmod`, `chown`, `iptables`, `ufw`) — even in gitignored paths
4. Paid API call (Stripe, OpenAI, AWS spend, etc.)
5. External-state network mutation (DNS, webhook registration, public push)

**Atomic Rollback Unit = Implementation node (one spec).** When a step fails both attempts in `/implement`:
- Revert all `paths_touched` changes for this Implementation.
- Mark Implementation node `STALE`.
- Do NOT touch upstream/downstream nodes (graph isolation).
- Track-level scratchpad logs the failure but is not reset.

**Ship of Theseus rule (Decision D from round 2):** When an upstream Invariant or ADR changes, all downstream Implementations are marked `STALE`. `/implement` refuses to run on `STALE` nodes until `/reverify <node>` re-runs only the verification blocks and passes.

## v1 carry-overs (unchanged in v2)

- `/vision` multi-turn protocol (Feasibility Audit, First Principles, Refinement Questions)
- `why:` per step (mandatory)
- Option B retry (one diagnose + corrected action, then halt)
- Pre-flight re-verify of step N-1
- Drift checkpoint every 5 successful steps
- SessionStart hydrator (extends to graph state injection in v2)
- PostToolUse(Bash) compactor (extends to graph state writes in v2)
- Atomic JSON via `tempfile.mkstemp + os.replace`

## v1 changes ABSORBED into v2 (no separate v1.1 patch)

- **Draft-to-disk in `/vision`:** Step 5 of the skill no longer prints the full draft inline. Writes `specs/<slug>.spec.md.draft` immediately, outputs one line `DRAFT: <path> (N steps). yes / refine "<change>" / cancel`. User reads in editor. On `yes`: atomic rename to `.spec.md` + flip `.active`. On `refine`: targeted edit on disk, re-emit one-line. Closes the double-token-output friction surfaced in this session.

## Deferred to v3 (with dependencies)

- **TLA+ formal methods** — depends on stable v2 graph model
- **Linux capabilities sandboxing** — depends on container shell (Docker/Podman); out of v2 bare-metal scope
- **Cross-machine state sync** — depends on supervisor consensus protocol (Raft)
- **Token cost telemetry & per-track budget kill** — moved into v2 Decision 5 (supervisor monitors, hibernates runaway tracks)

## Open questions before implementation

1. **Where does the supervisor process live?** A8 host? Per-project daemon? On-demand spawn at first multi-track `/implement`?
2. **How does the supervisor recover after host reboot?** Resource locks must be re-acquired without losing graph state. Likely: persisted lock log + read-on-startup reconciliation.
3. **What's the graph manifest's exact markdown shape?** Frontmatter-only, or Mermaid diagram alongside? Diffable in git is the constraint; readability is the bonus.
4. **PBT library — Hypothesis or roll our own?** Hypothesis violates stdlib-only. Roll-our-own gets us minimal property checks (type, schema, length, range) without dependency. Decide before auditor implementation.

## Required reading (rubberduck round 2 prescriptions)

- *Data and Reality* — William Kent. Information modeling fundamentals.
- *Raft Consensus Algorithm* — for supervisor parallel-state-update semantics.
- adr-tools repo (npryce/adr-tools) — ADR conventions, supersedes shape.
- Sourcegraph Cody context engine — local symbol map vs global embeddings prior art.
- TLA+ Hyperbook (Lamport) — for v3 prep, not v2.

## Build order (proposed, not locked)

1. Graph data model + parser/serializer (`specs/.graph.md` round-trip)
2. Codebase fingerprinter (`bin/fingerprint.py`)
3. ADR generation in `/vision` confirmation flow
4. Persistence-Tier classifier (replaces Risk-Gate regex in compactor)
5. State Auditor (PBT-lite stdlib implementation)
6. Supervisor + Resource locks (most complex, last)
7. Multi-track scratchpad migration (one-time data shape change)

Each phase ships behind a feature flag in `plugin.json` so v1 keeps working until v2 is end-to-end stable.

## Success criteria (binary)

1. New session resumes at Track A Step 180 and cites parent Invariants by name without reading scratchpad history.
2. `/vision` for "build a BTC logger" surfaces an existing `requests`-based fetch helper from elsewhere in the repo before drafting.
3. Two parallel `/implement` tracks competing for port 8080 serialize cleanly via supervisor.
4. Editing an ADR cascades `STALE` markers to all downstream Implementations.
5. `/implement` never autonomously runs `chmod 644 /etc/...` even though the regex doesn't match.

## Out of scope for v2 (explicit)

- UI / web dashboard for graph state
- Cost telemetry beyond per-track token kill
- Multi-user / multi-machine concurrent edit
- Spec versioning beyond ADR supersedes
- Auto-generated PBT properties (user must declare)
