<p align="center">
  <img src="logos/export/logo-512.png" alt="Spectre — three nested ghost silhouettes, light to dark" width="180">
</p>

# spectre

> Spectre — a deterministic spec-driven Claude Code plugin. Vision → Spec → Evaluate → Lock → Implement → Verify, with three-tier pre-lock review and per-project resource locking.

[![tests](https://img.shields.io/badge/tests-2003%20passing-brightgreen)](#tests) [![python](https://img.shields.io/badge/python-3.11%2B-blue)](#install) [![stdlib only](https://img.shields.io/badge/deps-stdlib%20only-blue)](#install) [![license](https://img.shields.io/badge/license-MIT-green)](LICENSE) [![version](https://img.shields.io/badge/version-1.3.0-blue)](CHANGELOG.md)

## Table of Contents

- [Background](#background)
- [Install](#install)
- [Usage](#usage)
- [API](#api)
- [Tests](#tests)
- [Maintainers](#maintainers)
- [Contributing](#contributing)
- [License](#license)

## Background

Spectre is a Claude Code plugin that turns a vague idea into a locked, machine-verifiable specification, then drives the agent to execute it step by step. Every spec is a **six-view family** — one perspective for the implementing agent, plus one each for the human user, integrator, operator, product input, and product output — locked together with cross-view consistency checks and calibrated against a catalog of real-world exemplars (curl, gh, systemd-journal, prometheus, …).

Three review tiers (deterministic AST, structural coverage, optional adversarial LLM) run before lock; block-severity findings prevent it. After lock, `/implement` walks the spec one atomic step at a time, gating each on a verification command, halting on risky actions, and persisting state across sessions and reboots.

Where plain Claude Code lets you chat with the agent and hope it stays on-track, Spectre makes the spec the canonical artifact: every action ties back to a numbered step you can audit, every halt has a verification gate, and drift is detectable across reboots. For the design rationale, the five invariants, and the full state machine, see [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Install

Requires Python 3.11+ (PEP 604 / PEP 585 syntax). **Stdlib only** — no third-party imports in production code.

**Via Claude Code marketplace (recommended):**

```text
/plugins
→ Browse Marketplaces
→ Add Marketplace: https://github.com/Joncik91/Spectre
→ Install: spectre
```

The repo ships its own `.claude-plugin/marketplace.json`, so the GitHub URL is also the marketplace URL.

**Manual symlink (for local development):**

```bash
git clone https://github.com/Joncik91/Spectre.git
ln -s "$PWD/Spectre" ~/.claude/plugins/spectre
```

Restart Claude Code. SessionStart fires `bin/hydrate.py`; with no active spec yet you'll see `SIGNAL: No active spec. Run /vision to begin.`

### First-run setup — Tier 3 review (optional)

Tier 3 runs an adversarial LLM reviewer (`deepseek-v4-flash`) before lock — catches missing context, factual errors, and attacker-view concerns the deterministic Tiers 1+2 can't. **It is opt-in; Tiers 1+2 always run for free.**

The first `/vision` run probes for `DEEPSEEK_API_KEY` (env var → `~/.spectre/secrets.env` → `$SPECTRE_SECRETS_FILE`) and writes `~/.spectre/reviewer.toml` recording your choice. Cost is ~$0.01–0.05 per spec. Full setup flow including secrets file, personal-rules, templates, and template-patches: [`docs/API.md`](docs/API.md).

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

You stay in the loop: clarifying questions during the interview, confirming the locked spec, approving each halt. Block findings prevent lock until fixed.

### Additional modes

```bash
# Auto mode — walk consecutive low-tier steps without re-prompting
/implement auto

# Multi-track (parallel work in one project)
/implement payments       # acquires res-port-8080 for track "payments"
/implement notifications  # queues if "payments" hasn't released yet
```

The hydrator re-injects the active spec and per-track scratchpad on every session start — resume mid-mission across reboots and Claude restarts. Switch missions: run `/vision` again; prior history (ADRs, eval sidecar) stays on disk.

### Six-view at a glance

Every locked spec since v1.0 carries this shape:

| § | Section | Receiver |
|---|---|---|
| 1–7 | First Principles → Algorithm Audit → Speed-of-Light Limit → Physics Guardrails → Steps → Success Criteria | implementing-agent |
| 8.1 | Hard contract — `mutates:` / `never-touches:` / `decision-budget:` / `reboot-survival:` | machine-enforced policy across all views |
| 8.2–8.7 | Cognitive-substrate calibration, one block per view | implementing-agent + 5 product-side views |
| 9–13 | View sections — mechanical / coverage / exemplar-binding contracts | product-input, product-output, human-user, integrator, operator |

Views that don't apply to a product are marked `not-applicable: <reason>` (no penalty). The evaluator warns past two N/A views. The catalog of exemplar tools used in §§9–13 lives at [`docs/exemplars/`](docs/exemplars/) — see [`docs/exemplars/README.md`](docs/exemplars/README.md) for the catalog guide and contribution process.

### When something halts

Every halt emits a stable status code (e.g. `walker.open-questions-unresolved`, `envelope.check status=tampered`, `view-fingerprint-contradicts-exemplar-binding`). Two ways to resolve:

```bash
spectre explain <code>        # full glossary entry: what it means + user_action
spectre glossary              # full registry of every code and term
SPECTRE_AUDIENCE=pm           # env var: every status line gets a plain-English follow-up
```

Full vocabulary registry: [`docs/glossary.md`](docs/glossary.md) (75+ status codes and terms, every finding kind documented with developer + plain-English explanations).

## API

Full reference — hooks, skills, spec step schema, sidecar format, layout, finding-kind taxonomy: [`docs/API.md`](docs/API.md).

**v1.3 components** — plugin `1.3.0` ([`.claude-plugin/marketplace.json`](.claude-plugin/marketplace.json)), `EVALUATOR_VERSION = "1.0.0"` ([`bin/spec_evaluator.py`](bin/spec_evaluator.py)), `WALKER_VERSION = "1.0.0"` ([`bin/walker.py`](bin/walker.py)). Walker state files persisted under v0.9 are rejected on load; remove `state/.walk.json` and re-run `/vision` to migrate (hard cutover from v0.9; no migration tool).

**`spectre` CLI surface** — top-level wrapper resolves `${CLAUDE_PLUGIN_ROOT}`, exports `PYTHONPATH`, dispatches to `python3 -m bin.<subcommand>`:

- `spectre walker …` — interview state machine (init-or-resume, peek-pending, answer-concern, …).
- `spectre substrate_wizard run | run-per-view` — §§8.2 and §§8.3–8.7 substrate calibration; per-view fingerprint + trust vocabularies.
- `spectre exemplars list | show | axes | validate` — metis catalog access (plugin + `~/.spectre/exemplars/` overlay).
- `spectre glossary | explain <code>` — status-code + term registry.
- `spectre <module>` — direct module CLIs (rarely invoked from prose; called by skills).

**Environment variables** — `SPECTRE_AUDIENCE=pm` (dual-channel plain-English status), `SPECTRE_QUIET=1` (suppress `ok`/`info` emissions including the per-call Tier-3 budget line), `DEEPSEEK_API_KEY` (Tier 3 opt-in), `SPECTRE_SECRETS_FILE` (escape hatch for non-default secrets location).

**Status grammar** — `<LEVEL> <code> key=value …` where `LEVEL ∈ {ok, info, warn, halt, error, result, prompt}`. See [`docs/API.md#cli-output-grammar`](docs/API.md).

## Tests

```bash
pytest tests/                  # 2003 tests, stdlib + pytest
pytest tests/ -v               # verbose
pytest tests/test_spec_evaluator.py -v   # single module
```

Test discipline: stdlib + pytest only, no network mocks outside `test_llm_judge.py`, Pragma test-gaming guard blocks `rejects/raises/refuses/denies`-named tests without `pytest.raises`. 1:1 module → test mapping for `bin/*.py`, plus four integration/E2E tests including a `test_v1_1_e2e.py` v1.1 acceptance test and `test_bin_direct_invocation.py` import-bootstrap coverage for direct `python3 bin/<module>.py` invocation. See [`CONTRIBUTING.md`](CONTRIBUTING.md) for full discipline and the review process.

## Maintainers

[@Joncik91](https://github.com/Joncik91)

## Contributing

Issues and PRs welcome. See [`CONTRIBUTING.md`](CONTRIBUTING.md) for test discipline, the Pragma guard, the stdlib-only rule, and the review process. This README follows the [Standard-Readme](https://github.com/RichardLitt/standard-readme) spec.

## License

[MIT](./LICENSE) © Joncik91
