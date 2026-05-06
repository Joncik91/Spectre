<p align="center">
  <img src="logos/export/logo-512.png" alt="Spectre — three nested ghost silhouettes, light to dark" width="180">
</p>

# spectre

> SDL Vision Engine — a deterministic spec-driven Claude Code plugin. Vision → Spec → Evaluate → Lock → Implement → Verify, with three-tier pre-lock review and per-project resource locking.

[![tests](https://img.shields.io/badge/tests-664%20passing-brightgreen)](#tests) [![python](https://img.shields.io/badge/python-3.11%2B-blue)](#install) [![stdlib only](https://img.shields.io/badge/deps-stdlib%20only-blue)](#install) [![license](https://img.shields.io/badge/license-MIT-green)](LICENSE)

## Table of Contents

- [Background](#background)
- [Install](#install)
- [Usage](#usage)
- [API](#api)
- [Architecture](#architecture)
- [Tests](#tests)
- [Maintainers](#maintainers)
- [Contributing](#contributing)
- [License](#license)

## Background

Default Claude Code auto-memory drifts during long sessions: spec-level intent gets buried under terminal scroll-back, "what did I just change on disk" answers require re-reading logs that have already aged out of context, and the agent will happily power through a half-broken plan when nobody re-grounds it.

Spectre overrides this with a deterministic state machine that drives an unbroken **vision → spec → evaluate → lock → implement → verify** chain. Two hooks own the context plane, two skills own the agent plane, and ~26 stdlib-only Python modules own the state plane (v0.4 added the interrogation walker, observations log, personal-rules overrides, CDLC ledger, templates registry, and template-patcher).

**The four invariants:**

- **Spec is law.** `specs/.active` is an explicit instruction-pointer file. The hydrator re-injects exactly one spec on every session start — no mtime guessing, no scrollback archaeology.
- **Steps are atomic transactions.** Every step has `why:` (first-principles justification, printed before execution), `action:` (the command), and `verification:` (a separate command that must exit 0 to prove the side effect). Soft verifications (`true`, `echo done`) are forbidden by the evaluator.
- **Pre-lock review is mandatory.** Three tiers of validation run before a draft becomes the active spec: deterministic AST classifier (Tier 1, always), structural coverage gate (Tier 2, always), DeepSeek `deepseek-reasoner` adversarial reviewer (Tier 3, opt-in). Block-severity findings prevent lock. Tier 3 status is always surfaced — when it skips, the skip is visible (see "First-run setup" below).
- **Spec authorship is interrogation, not transcription.** v0.4 introduces an interrogation walker: the human supplies intent, the LLM walks the possibility-graph one concern at a time. The walker (`bin/walker.py`) refuses to prune branches biology lets humans skip and stops only when the author says so OR when adversarial review (Tier 3) stops finding new things. Output: a complete-enough spec authored in ~10 min instead of ~60 min.
- **Risky steps halt by default.** A persistence-tier classifier gates every action: `silent` and `repo` execute freely; `host` and `network` halt and ask. The Never Autonomous list (sudo, rm -rf, systemctl mask, …) is a hard halt regardless of tier.

Five named v1 failure modes — broad matcher, hydrator bloat, recursive failure, torn writes, log inflation — each have a code-level mitigation and a test. The v0.2.x and v0.3.0 releases added five more first-class concerns: drift detection, resource contention, ADR provenance, host-state coverage, and adversarial review.

## Install

Requires Python 3.11+ (PEP 604 / PEP 585 syntax). **Stdlib only** — no third-party imports in production code, no `pip install` in the install path.

**Recommended — via Claude Code marketplace:**

```text
/plugins
→ Browse Marketplaces
→ Add Marketplace: https://github.com/Joncik91/Spectre
→ Install: sdl-vision-engine
```

The repo ships its own `.claude-plugin/marketplace.json` so the GitHub URL is also the marketplace URL.

**Manual symlink (for local development):**

```bash
git clone https://github.com/Joncik91/Spectre.git
ln -s "$PWD/Spectre" ~/.claude/plugins/sdl-vision-engine
```

Restart Claude Code. SessionStart fires `bin/hydrate.py`; with no `.active` yet you'll see:

```
SIGNAL: No active spec. Run /vision to begin.
Available specs:
  - specs/template.spec.md
STATE: step=1 exit_code=0 last_command=None
```

### First-run setup — Tier 3 adversarial review (optional, ~$0.01/spec)

Tier 3 runs DeepSeek's `deepseek-reasoner` model as an adversarial spec reviewer before lock. It catches missing context, factual errors, and attacker-view concerns the deterministic Tiers 1+2 can't see. **It is opt-in.** Tiers 1+2 always run for free.

The first time you run `/vision`, the setup wizard fires automatically. It probes for a DeepSeek API key in this order:

1. The `DEEPSEEK_API_KEY` environment variable in your live shell.
2. `~/.spectre/secrets.env` — Spectre's canonical secrets file. `KEY=value` lines, mode 0600.
3. `$SPECTRE_SECRETS_FILE` — escape hatch for users who keep secrets elsewhere.

**If a key is found**, the wizard prompts once: enable Tier 3 now? `yes` → writes `~/.spectre/reviewer.toml` with `enabled=true`. `no` → writes the same file with `enabled=false` so subsequent runs don't re-prompt.

**If no key is found**, the wizard prints the setup instructions and asks `(retry / skip)`. Drop the key, type `retry`, and the wizard re-probes — no second `/vision` invocation needed.

To get a key: <https://platform.deepseek.com/api_keys>. Then:

```bash
mkdir -p ~/.spectre
echo 'DEEPSEEK_API_KEY=sk-...' > ~/.spectre/secrets.env
chmod 600 ~/.spectre/secrets.env
```

The key value is never copied into `reviewer.toml` — only the env-var name is stored. Each `/vision` draft with Tier 3 enabled makes ~3 API calls (~10–30s, ~$0.01–0.05). To re-enable after declining, edit `~/.spectre/reviewer.toml` and set `[tier3] enabled = true`.

### Personal rules — adoptive halt overrides (v0.4.1+)

`~/.spectre/personal-rules.toml` accumulates user-adopted rule overrides. Every TIER GATE halt in `/implement` records a fingerprint to `~/.spectre/observations.jsonl`. After a halt where you reply `yes` and the action verifies, the skill prompts: **"Adopt this halt-class as personal-rule-skip? (adopt / once-only / never-ask-again)"**.

- `adopt` writes to `personal-rules.toml`. Future runs of the same `(classifier_label, fingerprint)` skip the halt automatically.
- Sandbox-paradox brake: after 3 adoptions in one session, the prompt stops firing. The skill prints `BRAKE: edit ~/.spectre/personal-rules.toml to review`. Restarting resets the counter (counter is persisted per-track in `state/scratchpad.json`).
- **Removal is manual.** Open `personal-rules.toml` and delete the entry. There is no auto-removal prompt.
- **Project-locked §8.1 rules are immune.** A spec's `mutates:` / `never-touches:` block always overrides personal-rules — adoptions cannot weaken a project's hard contract.

The setup wizard provisions an empty `personal-rules.toml` at first run.

### Templates (v0.4.2+) — Distribute leg

`~/.spectre/templates/` holds reusable spec drafts and skills you can import into new projects.

```bash
# Export a project spec as a reusable template
python3 -c "from bin import templates; templates.export_template(source_path='specs/my-spec.spec.md', target_name='my-spec-base')"

# Import in a fresh project (also surfaced in /vision Step 0 if templates exist)
python3 -c "from bin import templates; templates.import_template(source_name='my-spec-base', target_name='my-new-spec')"
```

Imported specs land at `./specs/<target>.spec.md.draft` so the existing /vision interrogation walk still gates the lock. Imported skills land at `./skills/<target>.md`.

The setup wizard provisions `~/.spectre/templates/{specs,skills}/` + `~/.spectre/template-patches/{proposed,accepted,rejected}/` at first run. Local-only — no remote sync in v0.4.2.

### Template-patches (v0.4.2+) — Adapt's auto-proposals

When a TIER GATE halt fingerprint recurs ≥3 times across your projects without being adopted as a personal-rule, Spectre auto-proposes a markdown patch to your project's `specs/template.spec.md`. Patches land at `~/.spectre/template-patches/proposed/<slug>.md`. SessionStart surfaces the count.

Manual workflow: `cat` the proposed patch, decide. Move to `accepted/` to mark applied, `rejected/` to dismiss. Spectre never auto-merges.

## Usage

```text
# 1. Lock a spec.
/vision Build a real-time order sync between Shopify and our warehouse
# → Codebase fingerprint scan, then Feasibility Audit (silent).
# → Walker initialized with five seed concerns (1 assumption-surface + 4 §8.1
#   receiver-clarification: mutates / never-touches / decision-budget / reboot-survival).
# → Round 1: walker emits the next concern; skill phrases as a natural-language question.
# → User answers; walker records answer, queues dependent concerns per receiver.
# → Loop continues until: user types `stop`, OR Tier 3 yield-delta converges
#   (3 rounds with <2 new findings), OR max-rounds (30), OR per-receiver-exhausted.
# → After stop: skill renders the draft from accumulated answers.
# → Confirm: yes / refine "<change>" / cancel.
# → On yes: pre-lock evaluator runs Tier 1 (AST) + Tier 2 (coverage) + Tier 3 if configured.
#   Block findings halt; warn/info pass through.
# → ADRs auto-generated for each Decision marker; Resource nodes inferred for port:N etc.
# → Atomic flip: <slug>.spec.md.draft → <slug>.spec.md, .active updated, scratchpad reset,
#   .eval.json sidecar written with policy hash + tier metadata.
#   state/.walk.json retained as audit trail.

# 2. Run the active spec.
/implement
# → Reads .active + scratchpad. Pre-flight re-verifies prior step (catches root-state desync).
# → Tier classifier on action; halt on host/network/never-autonomous (yes/halt/skip).
# → Resource lock acquire via supervisor (queues if at capacity).
# → Prints WHY: <one-line first-principles justification> before executing.
# → Action runs. Verification gates advance. State Auditor PBT-lite checks land in scratchpad.
# → Pass: step advances, lock released. Fail: one Option-B retry with diagnosis, then halt.
# → Every 5 steps, drift checkpoint re-reads §1 and audits the next batch against it.

# 3. Verify-only (no execution).
/implement check
# → Re-runs the current step's verification. No execution, no scratchpad write.

# 4. Auto mode — walk consecutive low-tier steps without re-prompting.
/implement auto
# → Same safety surface as plain /implement but batches silent/repo-tier steps.
# → Halts at the first host/network/never-autonomous step, queued lock, verification
#   fail, or drift trigger. User then types /implement (or /implement auto) again.

# 5. Multi-track (parallel work in one project).
/implement payments       # acquires res-port-8080 for track "payments"
/implement notifications  # queues if "payments" hasn't released yet
```

The hydrator re-injects the same active spec and the scratchpad's `step` (per track) on every session start — you resume mid-mission across reboots and Claude restarts. To switch missions, run `/vision` again; the prior spec's history (ADRs, eval sidecar) stays on disk.

## API

### Hooks (registered by `.claude-plugin/plugin.json`)

| Event | Matcher | Command | Output |
|---|---|---|---|
| `SessionStart` | — | `python3 bin/hydrate.py` | Active spec body wrapped in `--- ACTIVE SPEC ---` markers + per-track `STATE:` line. Or `SIGNAL:` / `MIGRATED:` / `ERROR:` fallback. |
| `PostToolUse` | `Bash` | `python3 bin/compact.py` | JSON `{"additionalContext": "<Delta + Anchor block>"}`. Capped under ~500 chars. |

### Skills

| Skill | Trigger | Purpose |
|---|---|---|
| **vision** | `/vision <free-form text>` | Multi-turn inception. Codebase fingerprint → feasibility audit → First-Principles draft → 2–3 refinement Qs → step-by-step `why:/action:/verification:` triples → §8 Receiver Calibration → confirm → pre-lock evaluator (Tier 1+2 always, Tier 3 if configured) → ADR generation → atomic `.active` flip + scratchpad reset + `.eval.json` sidecar. Defined in `skills/vision/SKILL.md`. |
| **implement** | `/implement [<track>]` | Run the active spec's next step on the named track (default `default`). Pre-flight re-verify → tier classifier → resource lock → WHY emit → execute → verify → State Auditor → drift checkpoint every 5 steps. One Option-B retry with diagnosis on verification fail. Halts on missing-binary errors, spec gaps, root-state desync, or Tier=host/network without consent. Defined in `skills/implement/SKILL.md`. |
| **implement check** | `/implement check` | Re-run the current step's verification only. No execution, no advance. |

### Spec step schema (`specs/template.spec.md`)

Each step is an atomic transaction:

```yaml
- step: 1
  why: "Server must bind a known TCP port; lock prevents two tracks racing for it."
  action: "python3 -m http.server 8080"
  verification: "curl -sf http://127.0.0.1:8080 > /dev/null"
  resources:                # OPTIONAL — auto-inferred from action when port:N pattern matches
    - res-port-8080
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

Soft verifications (`echo done`, `true`, `: ; …`) are rejected by the Tier 1 AST classifier. Resource IDs must match a node in `specs/.graph.md`. Properties run after `verification:` passes — auditor verdicts are informational, never blocking.

### §8 Receiver Calibration (machine-enforced)

Every spec must declare a hard contract:

```yaml
mutates: /opt/btc-poller/, /etc/systemd/system/
never-touches: /home, /etc/passwd, /var/log
decision-budget: 1 paid API call per minute (CoinGecko free tier)
reboot-survival: required
```

The Tier 2 coverage gate cross-checks this against every action's path captures. A step that writes to `/var/log` while `never-touches` lists `/var/log` is a `block`-severity `calibration-hard-violation`. Severity overrides in `~/.spectre/reviewer.toml` can raise severities (warn → block) but never lower them.

### Scratchpad schema v2 (`state/scratchpad.json`)

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

### `.eval.json` sidecar (post-lock metadata)

Written next to every locked spec for reproducibility:

```json
{
  "evaluator_version": "0.3.0",
  "tiers_run": [1, 2, 3],
  "findings": [...],
  "dismissals": [...],
  "config_hash": "<sha256 of resolved config>",
  "deepseek_model_version": "deepseek-v4-pro",
  "policy_hash": "<sha256 of severity policy>"
}
```

`policy_hash` covers the resolved severity table — if a project tightens severities mid-flight, the next spec's sidecar diverges from the prior one, and the gap is auditable.

### Layout

```text
.claude-plugin/plugin.json     plugin manifest (sdl-vision-engine v1.1.0)
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
  llm_judge.py                  Tier 3 DeepSeek v4 Pro adversarial reviewer
  findings.py                   Finding dataclass + stable fingerprint
  eval_metadata.py              .eval.json sidecar + policy hash
  adr.py                        ADR writer + graph supersedes-edge update
  graph.py                      .graph.md manifest parser/serializer
  resources.py                  Resource node parser + heuristic extractor
  tier.py                       /implement §3.5 persistence-tier classifier
  auditor.py                    /implement §5.5 PBT-lite State Auditor
  supervisor.py                 per-project UDS daemon for resource locks
  track.py                      supervisor client (acquire/release/heartbeat)
skills/
  vision/SKILL.md               /vision protocol (Steps 0–7, ~350 lines)
  implement/SKILL.md            /implement protocol (Steps 0.5–7, ~320 lines)
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
  superpowers/                  design specs + implementation plans (archival)
tests/                          439 pytest tests, ~5s, stdlib + pytest only
```

## Architecture

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full breakdown: hook flow, skill protocols, evaluator pipeline, resource-lock supervisor, and the design rationale behind the three-tier defense.

## Tests

```bash
pytest tests/                  # 439 tests, ~5s, all stdlib + pytest
pytest tests/ -v               # verbose
pytest tests/test_spec_evaluator.py -v   # single module
```

Test discipline:

- Stdlib + pytest only. No mocks of `urllib.request` outside `test_llm_judge.py`. No mocks of network for any other module.
- Pragma test-gaming guard: tests with `rejects/raises/refuses/denies` in the name without `pytest.raises` are blocked at edit time.
- 1:1 module → test mapping for production code (every `bin/<x>.py` has a `tests/test_<x>.py`); plus four E2E suites covering bundle handoff, dismissal flow, BTC-poller regression, and full skill flow.

## Maintainers

[@Joncik91](https://github.com/Joncik91)

## Contributing

Issues and PRs welcome. See [`CONTRIBUTING.md`](CONTRIBUTING.md) for test discipline, the Pragma guard, the stdlib-only rule, and the review process. This README follows the [Standard-Readme](https://github.com/RichardLitt/standard-readme) spec.

## License

[MIT](./LICENSE) © Joncik91
