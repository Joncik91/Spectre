# Changelog

All notable changes to the SDL Vision Engine plugin (Spectre).

## [0.2.2] - 2026-05-05

### Added
- Supervisor process for parallel `/implement <track>` execution
- Resource locks (ports, DB connections, paid-API quotas) with reboot recovery
- Multi-track scratchpad shape (auto-migrated from v1)
- Cross-track dependency graph (Resource nodes + `blocks` edges)

### Changed
- Scratchpad is now per-track. v1 single-track scratchpad auto-migrated on first SessionStart.

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
