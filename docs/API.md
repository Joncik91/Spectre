# Spectre API Reference

Full reference for hooks, skills, spec step schema, sidecar format, scratchpad schema, and repository layout.

## Hooks

Registered by `.claude-plugin/plugin.json`.

| Event | Matcher | Command | Output |
|---|---|---|---|
| `SessionStart` | — | `python3 bin/hydrate.py` | `RESULT hydrate.spec_summary slug=… step=N exit_code=N last_command=…` — one line per active spec. `RESULT hydrate.signal reason=no-active-spec hint=…` if none. `OK hydrate.migrated` on v1→v2 upgrade. `WARN hydrate.stale_active` if `.active` pointer is broken. |
| `PostToolUse` | `Bash` | `python3 bin/compact.py` | JSON `{"additionalContext": "<Delta + Anchor block>"}`. Capped under ~500 chars. |

## CLI output grammar

Every Spectre CLI subcommand (under `bin/`) emits structured status lines on stdout following a single grammar:

```
<LEVEL> <code> [key=value ...]
```

**Levels** (seven, exhaustive):

| Level | Semantics |
|---|---|
| `ok` | Non-blocking confirmation — operation completed, no action required. |
| `info` | Contextual information — not a state change, purely informational. |
| `warn` | Soft problem — execution continues, user should be aware. |
| `halt` | Hard stop — the gate fired, no further execution until user responds. |
| `error` | Unrecoverable error — the CLI cannot complete the requested operation. |
| `result` | Structured output — the answer to a query (tier, fingerprint, eval summary, …). |
| `prompt` | Request for user input — the skill is waiting for a reply before proceeding. |

**Codes** are stable dot-namespaced identifiers: `<module>.<verb>`. A few canonical examples:

| Code | Level | Fields |
|---|---|---|
| `walker.init` | `ok` | `rounds=`, `pending=`, `open_questions=`, `stop=` |
| `walker.answer` | `ok` | `id=`, `round_count=` |
| `walker.yield` | `ok` | `new_t3=`, `history=` |
| `walker.coverage` | `result` | `answered=N`, `pending=M`, `deferred=K`, `undefined-invariants=L`, `recommended-stop=yes\|no`, `rounds=R` — full coverage snapshot emitted on stop, `coverage` subcommand, and per-round under `--verbose`. |
| `walker.recommend-stop` | `result` | `reason=coverage-complete` — emitted exactly once on the False→True transition; fires in both quiet and verbose modes. |
| `walker.open-questions-detected` | `result` | `count=N`, `ids=oq-1,oq-2,...` — emitted after `init-or-resume` when open questions are parsed from intent. |
| `walker.open-questions-unresolved` | `warn` | `count=K`, `ids=oq-1,...` — emitted when `author-arbitrated` stop is refused due to unresolved open questions. |
| `walker.open-question-deferred` | `ok` | `id=oq-N`, `adr=<adr-slug>` — emitted after `defer-open-question` succeeds. |
| `eval.summary` | `result` | `tier1=pass\|fail`, `tier2=pass\|fail`, `tier3=pass\|skip`, `block=N`, `warn=N` |
| `tier.classify` | `result` | `tier=silent\|repo\|host\|network`, `halt=true\|false` |
| `envelope.check` | `result` | `status=ok\|missing\|tampered`, `path=` |
| `hydrate.spec_summary` | `result` | `slug=`, `step=N`, `exit_code=N`, `last_command=` |
| `hydrate.signal` | `result` | `reason=no-active-spec`, `hint=` |
| `scratchpad.pending_prompt` | `result` | `fingerprint=`, `label=` |
| `personal_rules.brake` | `warn` | `session_count=N`, `max=N`, `remediation=` |
| `audit.summary` | `result` | `checks=N`, `passed=true\|false` |
| `wizard.setup` | `ok` | `result=enabled\|exists\|setup-skipped`, `target=` |

**Environment controls:**

| Variable | Effect |
|---|---|
| `SPECTRE_QUIET=1` | Suppresses `ok` and `info` lines. |
| `SPECTRE_VERBOSE=1` | Adds `expand=` field with multi-line context (e.g. spec body in hydrate output). |
| `SPECTRE_JSON=1` | Writes JSON records to stdout; text status moves to stderr. |

**Path display rule.** All paths emitted by CLIs are project-relative (`specs/foo.spec.md`, `state/scratchpad.json`). Absolute paths, `${CLAUDE_PLUGIN_ROOT}`, and `$HOME` literals never appear in user-facing output. The `bin/_path_display.py` helper enforces this at the emit boundary.

## Skills

| Skill | Trigger | Purpose |
|---|---|---|
| **vision** | `/vision <free-form text>` | Interrogates the user step-by-step, drafts a spec from first principles, runs three review tiers, and atomically locks the spec as the active mission. Full flow in `skills/vision/SKILL.md`. |
| **implement** | `/implement [check \| auto] [<track>]` | Runs the active spec's next step: tier-classifies the action, acquires the resource lock, prints the justification, executes, and gates on the verification command. Halts on missing-binary errors, spec gaps, root-state desync, or elevated tier without consent. Full flow in `skills/implement/SKILL.md`. |
| **implement check** | `/implement check [<track>]` | Re-runs the current step's verification only — no execution, no state advance. |
| **implement auto** | `/implement auto [<track>]` | Walks consecutive silent/repo-tier steps without re-prompting; halts at the first elevated-tier step, queued lock, verification fail, or drift trigger. |

## Spec step schema

From `specs/template.spec.md`. Each step is a self-contained transaction. Spectre verifies that the action did what it claims to do (via the separate `verification:` command) before allowing the next step to execute. The schema:

```yaml
- step: 1
  why: "Server must bind a known TCP port; lock prevents two tracks racing for it."
  action: "python3 -m http.server 8080"
  verification: "curl -sf http://127.0.0.1:8080 > /dev/null"
  resources:                # OPTIONAL — auto-inferred from action when port:N pattern matches
    - res-port-8080
  produces:                 # OPTIONAL — explicit step contracts
    - file:/opt/myapp/server.py
    - package:myapp
  requires:                 # OPTIONAL — Tier 1 cross-validates against prior produces:
    - package:myapp
  negative-paths:           # OPTIONAL — Tier 1 warn/block on missing hazard handlers
    - trigger: "port already bound"
      handler: "kill existing occupant or fail fast"
  properties:               # OPTIONAL — State Auditor PBT-lite checks
    - kind: type
      target: "/path/to/output.json"
      expected: dict
    - kind: length
      target: "/path/to/output.json"
      target_field: "rows"
      min: 1
      max: 10
```

Soft verifications (`echo done`, `true`, `: ; …`) are rejected by the Tier 1 AST classifier. Resource IDs must match a node in `specs/.graph.md`. Properties run after `verification:` passes — auditor verdicts are informational, never blocking. `produces:`/`requires:` support 8 contract types: `file:`, `package:`, `console-script:`, `route:`, `module:`, `binary:`, `db-table:`, `db-column:`. Mismatch → block-severity `unowned-requirement`.

## §8 Receiver Calibration

Every spec declares two contracts: §8.1 hard-contract (what the technical implementer is allowed to touch) and §8.2 cognitive-substrate contract (who the spec is for, what it implies about trust and judgment, and what assumptions were killed).

The Tier 2 coverage gate and Tier 1 substrate AST enforce these contracts before lock. A step that writes to a `never-touches` path is a block-severity `calibration-hard-violation`; a missing trust annotation or untrusted-input-to-sink flow without `sanitizes:` is caught by the substrate checker. The schema:

```yaml
# §8.1 — hard contract
mutates: /opt/btc-poller/, /etc/systemd/system/
never-touches: /home, /etc/passwd, /var/log
decision-budget: 1 paid API call per minute (CoinGecko free tier)
reboot-survival: required

# §8.2 — cognitive-substrate contract (auto-prompted at /vision Step 0.5)
receiver-fingerprint: claude-code+human
trust-profile: handles-secrets, touches-network
contextual-binding: <one-line product hypothesis>
provenance: { kind: none }
ux-contract: { on-success, on-failure, log-target }
assumptions-killed: [<rejected alternatives + why>]
requires-situated-judgment: [<step numbers>]
roi-budget: <when this spec's payoff goes positive>
```

Severity overrides in `~/.spectre/reviewer.toml` can raise severities (warn → block) but never lower them.

## Scratchpad schema

Version 2 — `state/scratchpad.json`:

```json
{
  "version": 2,
  "active_mission": "specs/btc-poller.spec.md",
  "tracks": {
    "default": {
      "active_spec": "specs/btc-poller.spec.md",
      "step": 3,
      "last_command": "pip install requests",
      "exit_code": 0,
      "delta": "pip install",
      "timestamp": "2026-05-05T14:22:01+00:00",
      "failed_hypotheses": [],
      "paths_touched": ["/opt/btc-poller/poll.py"],
      "last_drift_check_step": 0,
      "last_audit_kinds": ["type"],
      "last_audit_passed": true,
      "last_audit_failures": []
    }
  },
  "decisions_index": "decisions/",
  "graph_snapshot": "specs/.graph.md"
}
```

The hydrator auto-migrates v1 scratchpads on first session after upgrade (in-flight state preserved under `tracks.default`). `step` is user-driven — `compact.py` reports state but never advances it.

## .eval.json sidecar

Written next to every locked spec for reproducibility:

```json
{
  "evaluator_version": "<x.y.z>",
  "tiers_run": [1, 2, 3],
  "findings": [...],
  "dismissals": [...],
  "config_hash": "<sha256 of resolved config>",
  "deepseek_model_version": "deepseek-v4-flash",
  "policy_hash": "<sha256 of severity policy>",
  "spec_sha256": "<sha256 of locked spec body>",
  "sidecar_sha256": "<sha256 of this sidecar>",
  "substrate_resolution": { ... },
  "contract_resolution": {
    "step-2-requires-package-foo": "step-1-produces-package-foo"
  }
}
```

`policy_hash` covers the resolved severity table — if a project tightens severities mid-flight, the next spec's sidecar diverges from the prior one, and the gap is auditable. `spec_sha256` and `sidecar_sha256` are the bytewise integrity anchors checked by the handoff envelope at `/implement` start. `contract_resolution` records how each `requires:` entry resolved to a prior step's `produces:` declaration. `substrate_resolution` summarizes how the cognitive-substrate contract (§8.2 — receiver fingerprint, trust profile, taint outcome, provenance chain, axis completeness) resolved at lock time.

## Layout

```text
.claude-plugin/plugin.json     plugin manifest
.claude-plugin/marketplace.json self-hosted marketplace manifest
.spectre/reviewer.toml.example  Tier 3 + severity-overrides config sample
hooks/hooks.json                hook bindings (uses ${CLAUDE_PLUGIN_ROOT})
bin/
  hydrate.py                    SessionStart hook (active spec + STATE line)
  compact.py                    PostToolUse(Bash) hook (Delta + Anchor)
  _scratchpad.py                atomic JSON helpers + v1/v2 schemas
  migrate_scratchpad_v1_to_v2.py one-shot, idempotent migration
  fingerprint.py                /vision Step 0 codebase symbol walker
  spec_evaluator.py             /vision §6.4 review-bundle orchestrator
  spec_ast.py                   Tier 1 deterministic AST classifier
  coverage_gate.py              Tier 2 structural coverage gate
  llm_judge.py                  Tier 3 DeepSeek deepseek-v4-flash adversarial reviewer — contradiction-tuple protocol (single API call, 10 kinds + unrecognized fallback) + CoT faithfulness cite-and-verify pass + adversarial-pathway rubric
  findings.py                   Finding dataclass + stable fingerprint
  eval_metadata.py              .eval.json sidecar + policy hash + substrate_resolution
  adr.py                        ADR writer + graph supersedes-edge update
  graph.py                      .graph.md manifest parser/serializer
  resources.py                  Resource node parser + heuristic extractor
  tier.py                       /implement §3.5 persistence-tier classifier
  auditor.py                    /implement §5.5 PBT-lite State Auditor
  supervisor.py                 per-project UDS daemon for resource locks
  track.py                      supervisor client (acquire/release/heartbeat)
  managed_venv.py               executor-owned Python venv + normalize_action rewriter
  observations.py               TIER GATE halt recorder + recurrence finder
  personal_rules.py             per-user halt-override TOML store + sandbox-paradox brake
  cdlc_ledger.py                per-project CDLC transition log
  templates.py                  template store import/export + list CLI
  walker.py                     interrogation-walk state machine + yield countdown + negative-path concerns
  substrate_wizard.py           §8.2 cognitive-substrate wizard (auto-fires at /vision Step 0.5)
  substrate_ast.py              Tier 1 substrate-completeness + per-step taint flow classifier
  handoff_envelope.py           JSON-Schema-validated vision→implement handoff with bytewise integrity
  handoff_validator.py          Tier 0 envelope check on implement start
skills/
  vision/SKILL.md               /vision protocol (phase-named: Fingerprint → Wizard → Intent → Feasibility → Walker loop → Draft → Evaluator gate → Lock → Transition)
  implement/SKILL.md            /implement protocol (phase-named: Mode routing → Track → Tier 0 envelope → Context read → … → Finding capture)
specs/
  template.spec.md              canonical spec structure (§1–§8.2)
  .active                       instruction pointer (atomic-flipped)
  .graph.md                     decision/resource graph manifest
state/
  scratchpad.json               per-track step state (v2 schema)
  .eval-bundle.json             transient pre-lock review bundle
decisions/                      ADR landing zone (NNNN-<slug>.md)
docs/
  ARCHITECTURE.md               internal architecture overview
  API.md                        this file — hooks, skills, schemas, layout
  superpowers/                  design specs + implementation plans (archival)
tests/                          1555 pytest tests, stdlib + pytest only
```
