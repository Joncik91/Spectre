<p align="center">
  <img src="logos/export/logo-512.png" alt="Spectre — three nested ghost silhouettes, light to dark" width="180">
</p>

# spectre

> Spectre — a deterministic spec-driven Claude Code plugin. Vision → Spec → Evaluate → Lock → Implement → Verify, with three-tier pre-lock review and per-project resource locking.

[![tests](https://img.shields.io/badge/tests-1366%20passing-brightgreen)](#tests) [![python](https://img.shields.io/badge/python-3.11%2B-blue)](#install) [![stdlib only](https://img.shields.io/badge/deps-stdlib%20only-blue)](#install) [![license](https://img.shields.io/badge/license-MIT-green)](LICENSE)

## What it does

You type:

```
/vision Build a deterministic worker that polls Bitcoin prices and writes them to systemd
```

You get:

- A markdown spec with numbered steps (10–20 atomic transactions)
- Each step has `why:` / `action:` / `verification:` triples — purpose, command, and proof
- Three review tiers run automatically before lock: deterministic AST (Tier 1), coverage gate (Tier 2), and optionally a DeepSeek adversarial reviewer (Tier 3)
- Block-severity findings prevent lock until the spec is fixed

Then:

```
/implement
```

Runs the spec one step at a time: prints the `why:` before each action, gates on the `verification:` command, halts on risky actions, never silently fails.

Plain Claude Code lets you chat with the agent and hope it stays on-track. Spectre makes the spec the canonical artifact: every action ties back to a numbered step you can audit, every halt has a verification gate, and drift is detectable across reboots and session restarts.

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

Spectre overrides this with a deterministic state machine that drives an unbroken **vision → spec → evaluate → lock → implement → verify** chain.

Two hooks own the context plane, two skills own the agent plane, and stdlib-only Python modules own the state plane (interrogation walker, observations log, personal-rules overrides, CDLC ledger, templates registry, template-patcher). See [`CHANGELOG.md`](CHANGELOG.md) for the per-release log.

**The four invariants:**

- **Spec is law.** `specs/.active` is an explicit instruction-pointer file. The hydrator re-injects exactly one spec on every session start — no mtime guessing, no scrollback archaeology.
- **Steps are atomic transactions.** Every step has `why:` (first-principles justification, printed before execution), `action:` (the command), and `verification:` (a separate command that must exit 0 to prove the side effect). Soft verifications (`true`, `echo done`) are forbidden by the evaluator.
- **Pre-lock review is mandatory.** Three tiers of validation run before a draft becomes the active spec: deterministic AST classifier (Tier 1, always), structural coverage gate (Tier 2, always), DeepSeek `deepseek-v4-flash` adversarial reviewer (Tier 3, opt-in). Block-severity findings prevent lock. Tier 3 status is always surfaced — when it skips, the skip is visible (see "First-run setup" below).
- **Spec authorship is interrogation, not transcription.** The interrogation walker treats authorship as a graph walk: the human supplies intent, the LLM walks the possibility-graph one concern at a time. The walker (`bin/walker.py`) refuses to prune branches biology lets humans skip and stops only when the author says so OR when adversarial review (Tier 3) stops finding new things. Output: a complete-enough spec authored in ~10 min instead of ~60 min.
- **Risky steps halt by default.** A persistence-tier classifier gates every action: `silent` and `repo` execute freely; `host` and `network` halt and ask. The Never Autonomous list (sudo, rm -rf, systemctl mask, …) is a hard halt regardless of tier.

## Install

Requires Python 3.11+ (PEP 604 / PEP 585 syntax). **Stdlib only** — no third-party imports in production code, no `pip install` in the install path.

**Recommended — via Claude Code marketplace:**

```text
/plugins
→ Browse Marketplaces
→ Add Marketplace: https://github.com/Joncik91/Spectre
→ Install: spectre
```

The repo ships its own `.claude-plugin/marketplace.json` so the GitHub URL is also the marketplace URL.

**Manual symlink (for local development):**

```bash
git clone https://github.com/Joncik91/Spectre.git
ln -s "$PWD/Spectre" ~/.claude/plugins/spectre
```

Restart Claude Code. SessionStart fires `bin/hydrate.py`; with no `.active` yet you'll see:

```
SIGNAL: No active spec. Run /vision to begin.
Available specs:
  - specs/template.spec.md
STATE: step=1 exit_code=0 last_command=None
```

### First-run setup — Tier 3 adversarial review (optional, ~$0.01/spec)

Tier 3 runs DeepSeek's `deepseek-v4-flash` model as an adversarial spec reviewer before lock. It catches missing context, factual errors, and attacker-view concerns the deterministic Tiers 1+2 can't see. **It is opt-in.** Tiers 1+2 always run for free.

The first time you run `/vision`, the setup wizard fires automatically. It probes for a DeepSeek API key in this order:

1. The `DEEPSEEK_API_KEY` environment variable in your live shell.
2. `~/.spectre/secrets.env` — Spectre's canonical secrets file. `KEY=value` lines, mode 0600.
3. `$SPECTRE_SECRETS_FILE` — escape hatch for users who keep secrets elsewhere.

**If a key is found**, the wizard prompts once: enable Tier 3 now? `yes` → writes `~/.spectre/reviewer.toml` with `enabled=true`. `no` → writes the same file with `enabled=false` so subsequent runs don't re-prompt.

**If no key is found**, the wizard silently writes `enabled=false` and prints a one-line stderr breadcrumb pointing at `~/.spectre/secrets.env`. Tier 3 stays off until you drop the key and re-run `/vision`. No interactive prompts in the wizard — this keeps `/vision` safe in non-interactive contexts (subagents, scripts, paste-stdin).

To get a key: <https://platform.deepseek.com/api_keys>. Then:

```bash
mkdir -p ~/.spectre
echo 'DEEPSEEK_API_KEY=sk-...' > ~/.spectre/secrets.env
chmod 600 ~/.spectre/secrets.env
```

The key value is never copied into `reviewer.toml` — only the env-var name is stored. Each `/vision` draft with Tier 3 enabled makes 1 API call (contradiction-tuple protocol — single JSON-only prompt, ~10–30s, ~$0.01–0.05). To re-enable after declining, edit `~/.spectre/reviewer.toml` and set `[tier3] enabled = true`.

### Personal rules — adoptive halt overrides

`~/.spectre/personal-rules.toml` accumulates user-adopted rule overrides. Every TIER GATE halt in `/implement` records a fingerprint to `~/.spectre/observations.jsonl`. After a halt where you reply `yes` and the action verifies, the skill prompts: **"Adopt this halt-class as personal-rule-skip? (adopt / once-only / never-ask-again)"**.

- `adopt` writes to `personal-rules.toml`. Future runs of the same `(classifier_label, fingerprint)` skip the halt automatically.
- Sandbox-paradox brake: after 3 adoptions in one session, the prompt stops firing. The skill prints `BRAKE: edit ~/.spectre/personal-rules.toml to review`. Restarting resets the counter (counter is persisted per-track in `state/scratchpad.json`).
- **Removal is manual.** Open `personal-rules.toml` and delete the entry. There is no auto-removal prompt.
- **Project-locked §8.1 rules are immune.** A spec's `mutates:` / `never-touches:` block always overrides personal-rules — adoptions cannot weaken a project's hard contract.

The setup wizard provisions an empty `personal-rules.toml` at first run.

### Templates — Distribute leg

`~/.spectre/templates/` holds reusable spec drafts and skills you can import into new projects.

```bash
# Export a project spec as a reusable template
python3 -c "from bin import templates; templates.export_template(source_path='specs/my-spec.spec.md', target_name='my-spec-base')"

# Import in a fresh project (also surfaced in /vision Step 0 if templates exist)
python3 -c "from bin import templates; templates.import_template(source_name='my-spec-base', target_name='my-new-spec')"
```

Imported specs land at `./specs/<target>.spec.md.draft` so the existing /vision interrogation walk still gates the lock. Imported skills land at `./skills/<target>.md`.

The setup wizard provisions `~/.spectre/templates/{specs,skills}/` + `~/.spectre/template-patches/{proposed,accepted,rejected}/` at first run. Local-only — no remote sync.

### Template-patches — Adapt's auto-proposals

When a TIER GATE halt fingerprint recurs ≥3 times across your projects without being adopted as a personal-rule, Spectre auto-proposes a markdown patch to your project's `specs/template.spec.md`. Patches land at `~/.spectre/template-patches/proposed/<slug>.md`. SessionStart surfaces the count.

Manual workflow: `cat` the proposed patch, decide. Move to `accepted/` to mark applied, `rejected/` to dismiss. Spectre never auto-merges.

## Usage

Minimum viable sequence:

```bash
# 1. Lock a spec from a free-form vision
/vision Build a real-time order sync between Shopify and our warehouse

# 2. Run the active spec step by step
/implement

# 3. Verify-only re-check (no execution, no state advance)
/implement check
```

### Under the hood

#### /vision flow

`/vision` drives a multi-turn interrogation walk before writing a single line of spec:

- Codebase fingerprint scan, then Feasibility Audit (silent).
- Walker initialized with five seed concerns (1 assumption-surface + 4 §8.1 receiver-clarification: mutates / never-touches / decision-budget / reboot-survival).
- Round 1: walker emits the next concern; skill phrases as a natural-language question.
- User answers; walker records answer, queues dependent concerns per receiver.
- Loop continues until: user types `stop`, OR Tier 3 yield-delta converges (3 rounds with <2 new findings), OR max-rounds (30), OR per-receiver-exhausted.
- After stop: skill renders the draft from accumulated answers.
- Confirm: yes / refine "\<change\>" / cancel.
- On yes: pre-lock evaluator runs Tier 1 (AST) + Tier 2 (coverage) + Tier 3 if configured. Block findings halt; warn/info pass through.
- ADRs auto-generated for each Decision marker; Resource nodes inferred for port:N etc.
- Atomic flip: `<slug>.spec.md.draft` → `<slug>.spec.md`, `.active` updated, scratchpad reset, `.eval.json` sidecar written with policy hash + tier metadata. `state/.walk.json` retained as audit trail.

#### /implement flow

- Reads `.active` + scratchpad. Pre-flight re-verifies prior step (catches root-state desync).
- Tier classifier on action; halt on host/network/never-autonomous (yes/halt/skip).
- Resource lock acquire via supervisor (queues if at capacity).
- Prints `WHY: <one-line first-principles justification>` before executing.
- Action runs. Verification gates advance. State Auditor PBT-lite checks land in scratchpad.
- Pass: step advances, lock released. Fail: one Option-B retry with diagnosis, then halt.
- Every 5 steps, drift checkpoint re-reads §1 and audits the next batch against it.

#### Additional modes

```bash
# Auto mode — walk consecutive low-tier steps without re-prompting
/implement auto
# Halts at the first host/network/never-autonomous step, queued lock,
# verification fail, or drift trigger. Then /implement (or /implement auto) to continue.

# Multi-track (parallel work in one project)
/implement payments       # acquires res-port-8080 for track "payments"
/implement notifications  # queues if "payments" hasn't released yet
```

The hydrator re-injects the same active spec and the scratchpad's `step` (per track) on every session start — you resume mid-mission across reboots and Claude restarts. To switch missions, run `/vision` again; the prior spec's history (ADRs, eval sidecar) stays on disk.

## API

Full API reference — hooks, skills, spec step schema, sidecar format, and layout — lives at [`docs/API.md`](docs/API.md).

## Architecture

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full breakdown: hook flow, skill protocols, evaluator pipeline, resource-lock supervisor, and the design rationale behind the three-tier defense.

## Tests

```bash
pytest tests/                  # 1366 tests, all stdlib + pytest
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
