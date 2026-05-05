# Changelog

All notable changes to the SDL Vision Engine plugin (Spectre).

## v0.3.0 — 2026-05-05

**Plan A — Pre-lock spec evaluator (CDLC Evaluate phase).**

### Added
- `bin/findings.py` — typed Finding dataclass with structured locations + dismissable flag + stable fingerprint
- `bin/spec_ast.py` — Tier 1 deterministic spec-AST classifier (parse/structure/tautology only)
- `bin/coverage_gate.py` — Tier 2 default-on action↔verification + resource-coverage + calibration cross-check
- `bin/llm_judge.py` — Tier 3 DeepSeek v4 Pro adversarial reviewer (opt-in)
- `bin/spec_evaluator.py` — review-bundle orchestrator with bundle persistence
- `bin/eval_metadata.py` — `.eval.json` lock-metadata sidecar + no-downgrade enforcement
- `specs/template.spec.md` — §8 Receiver Calibration (8.1 hard contract + 8.2 human notes)
- `.spectre/reviewer.toml.example` — sample user config (committed for discoverability)

### Changed
- `skills/vision/SKILL.md` — §6.4 evaluator gate inserted between draft-to-disk (§6) and ADR generation (§6.5); §6.6 Resource inference now reads from validated bundle
- `.claude-plugin/plugin.json` — version 1.0.2 → 1.1.0

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
