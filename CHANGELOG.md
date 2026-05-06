# Changelog

All notable changes to the SDL Vision Engine plugin (Spectre).

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
