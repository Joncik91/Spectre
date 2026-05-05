# Changelog

All notable changes to the SDL Vision Engine plugin (Spectre).

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
