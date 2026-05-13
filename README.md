<p align="center">
  <img src="logos/export/logo-512.png" alt="Spectre — three nested ghost silhouettes, light to dark" width="180">
</p>

# spectre

> Spectre — a deterministic spec-driven Claude Code plugin. Vision → Spec → Evaluate → Lock → Implement → Verify, with three-tier pre-lock review and per-project resource locking.

[![tests](https://img.shields.io/badge/tests-1748%20passing-brightgreen)](#tests) [![python](https://img.shields.io/badge/python-3.11%2B-blue)](#install) [![stdlib only](https://img.shields.io/badge/deps-stdlib%20only-blue)](#install) [![license](https://img.shields.io/badge/license-MIT-green)](LICENSE)

## What is Spectre?

Spectre turns a vague idea into a locked, machine-verifiable specification, then drives an AI to execute it step-by-step. You stay in the loop at every gate — clarifying questions during the interview, confirming the locked spec, approving each step's verification.

Plain Claude Code lets you chat with the agent and hope it stays on-track. Spectre makes the spec the canonical artifact: every action ties back to a numbered step you can audit, every halt has a verification gate, and drift is detectable across reboots and session restarts.

## Who is this for?

- A **PM with a one-line idea** who wants a real spec without writing one from scratch.
- An **engineer who wants AI to execute** a spec step-by-step with verification gates at every step.
- A **team lead who wants traceability** — every decision, every step, every halt is captured as an immutable artifact (ADRs, sidecars, ledger).

## Quickstart

```
1. /vision <your idea>          start an interactive interview to lock a spec
2. (answer scope questions)      one per view (input/output/human/integrator/operator);
                                 each in-scope view cascades 3-5 follow-ups
3. (pick exemplars)              walker surfaces catalog options (e.g. help-text:curl)
4. lock the draft                confirm and Spectre seals it with an integrity hash
5. /implement                    Spectre drives the steps, verifying each
6. spectre glossary              browse plain-English meanings of every status code
7. SPECTRE_AUDIENCE=pm           set in your env for auto-rendered plain-English status lines
```

## Vocabulary

Spectre uses some engineer terms with specific meanings. If a status line is
unclear, two paths work:

- `spectre glossary` — list every status code and term, with plain-English explanations.
- `spectre explain <code>` — single-code lookup with context.
- `SPECTRE_AUDIENCE=pm` — environment variable; when set, every status line is
  followed by an indented plain-English sentence. Set it in your shell rc to make
  it permanent.

Full vocabulary registry: [docs/glossary.md](docs/glossary.md).

## Table of Contents

- [What it does](#what-it-does)
- [Background](#background)
- [Install](#install)
- [Usage](#usage)
- [Exemplars & Bindings](#exemplars--bindings)
- [Troubleshooting](#troubleshooting)
- [API](#api)
- [Architecture](#architecture)
- [Tests](#tests)
- [Maintainers](#maintainers)
- [Contributing](#contributing)
- [License](#license)

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

## Background

Default Claude Code auto-memory drifts during long sessions: spec-level intent gets buried under terminal scroll-back, "what did I just change on disk" answers require re-reading logs that have already aged out of context, and the agent will happily power through a half-broken plan when nobody re-grounds it. Worse: even when the implementing agent's view of the spec is complete, the **other receivers** of the product (the user typing input, the consumer reading output, the operator on call, the integrator wiring an API) end up under-served because nothing in the spec spoke to them directly.

Spectre overrides this with a deterministic state machine that drives an unbroken **vision → spec → evaluate → lock → implement → verify** chain. v1.0 closes the receiver gap: every spec is a **six-view family** — one perspective per receiver class — locked together, cross-consistent, calibrated against a curated metis catalog of exemplar tools.

Two hooks own the context plane, two skills own the agent plane, and stdlib-only Python modules own the state plane (the interview phase (`walker` internally), observations log, personal-rules overrides, CDLC ledger, templates registry, template-patcher, metis catalog loader). See [`CHANGELOG.md`](CHANGELOG.md) for the per-release log.

**The five invariants:**

- **Spec is law.** `specs/.active` is an explicit instruction-pointer file. The hydrator re-injects exactly one spec on every session start — no mtime guessing, no scrollback archaeology.
- **Specs are six-view families (v1.0).** Every locked spec carries `**Spec-version:** 1.0` frontmatter, §§1-7 calibrated to the implementing-agent receiver, a §8 family of substrate-calibration blocks (§§8.1-8.7, one per view), and §§9-13 view sections (Product-Input / Product-Output / Human-User / Integrator / Operator) declaring per-view contracts. Views that don't apply to a product are explicitly marked `not-applicable: <reason>`; the evaluator warns if more than two views are marked N/A.
- **Steps are atomic transactions.** Every step has `why:` (first-principles justification, printed before execution), `action:` (the command), and `verification:` (a separate command that must exit 0 to prove the side effect). Soft verifications (`true`, `echo done`) are forbidden by the evaluator.
- **Pre-lock review is mandatory.** Three tiers of validation run before a draft becomes the active spec: deterministic AST classifier (Tier 1, always — includes the v1.0 structural checks for §§8.3-8.7 and §§9-13), structural + cross-view consistency (Tier 2, always — `coverage_gate` plus the new `cross_view_gate` for v1.0 reference resolution + exemplar binding validation), DeepSeek `deepseek-v4-flash` adversarial reviewer (Tier 3, opt-in — v1.0 specs that bind exemplars get their conventions injected into the contradiction prompt). Block-severity findings prevent lock. Tier 3 status is always surfaced — when it skips, the skip is visible (see "First-run setup" below).
- **Spec authorship is interrogation, not transcription.** The interview phase (`walker` internally) treats authorship as a graph walk: the human supplies intent, the LLM walks the possibility-graph one concern at a time. In v1.0 the walker iterates per receiver — five new concern families (one per non-agent view) emit a scope-check concern first; in-scope views surface 3-5 follow-up concerns including exemplar selection from the catalog. Output: a complete-enough spec authored in ~10 min instead of ~60 min.
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

`~/.spectre/personal-rules.toml` accumulates user-adopted rule overrides. Every TIER GATE halt in `/implement` records a fingerprint (a stable hash of the halt class and action context) to `~/.spectre/observations.jsonl`. After a halt where you reply `yes` and the action verifies, the skill prompts: **"Adopt this halt-class as personal-rule-skip? (adopt / once-only / never-ask-again)"**.

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

When a TIER GATE halt fingerprint (a stable hash of the halt class and action context) recurs ≥3 times across your projects without being adopted as a personal-rule, Spectre auto-proposes a markdown patch to your project's `specs/template.spec.md`. Patches land at `~/.spectre/template-patches/proposed/<slug>.md`. SessionStart surfaces the count.

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

### Six-view at a glance

Every locked v1.0 spec has this shape. Sections marked `(v1.0+)` are new; §§1-8 already existed.

| § | Section | Receiver |
|---|---|---|
| 1-7 | Hard Problem / First Principles / Algorithm Audit / Speed-of-Light Limit / Physics Guardrails / Steps / Success Criteria | implementing-agent |
| 8.1 | Hard contract (mutates / never-touches / decision-budget / reboot-survival) | machine-enforced policy across all views |
| 8.2 | Cognitive-substrate contract | implementing-agent |
| 8.3 (v1.0+) | Product-input substrate | product-input |
| 8.4 (v1.0+) | Product-output substrate | product-output |
| 8.5 (v1.0+) | Human-user substrate | human-user |
| 8.6 (v1.0+) | Integrator substrate | integrator |
| 8.7 (v1.0+) | Operator substrate | operator |
| 9 (v1.0+) | Product-Input View — contracts (mechanical / coverage / exemplar-bindings) | product-input |
| 10 (v1.0+) | Product-Output View — contracts | product-output |
| 11 (v1.0+) | Human-User View — contracts (e.g. help-text style + error-text style + must-include lists) | human-user |
| 12 (v1.0+) | Integrator View — contracts | integrator |
| 13 (v1.0+) | Operator View — contracts (log format + metric names + observability style) | operator |

Views that don't apply to a product get marked `not-applicable: <reason>` in their §8.x block and §9-13 body — no penalty. More than two N/A views emits an `excessive-not-applicable` warn finding.

### Under the hood

#### /vision flow

`/vision` drives a multi-turn interview walk before writing a single line of spec:

- Codebase fingerprint scan, then Feasibility Audit (silent).
- The interview phase (`walker` internally) initialized with seed concerns covering §8.1 (mutates / never-touches / decision-budget / reboot-survival) plus the v1.0 view scope checks (one per non-agent view: product-input / product-output / human-user / integrator / operator).
- Per-view scope concerns ask "does this product have a <view> view?" — N/A short-circuits the family; in-scope answers cascade 3-5 follow-up concerns including exemplar selection (the skill fetches catalog entries via `spectre exemplars list --view-type <type>` and renders them with axis values so you see what you're choosing between).
- Round N: walker emits the next concern; skill phrases as a natural-language question.
- User answers; walker records answer, queues dependent concerns per receiver. The per-view substrate wizard (`run_per_view`) fires once per in-scope view to populate §§8.2-8.7.
- Loop continues until: user types `stop`, OR Tier 3 yield-delta converges (3 rounds with <2 new findings), OR max-rounds (30), OR per-receiver-exhausted (all v0.9 family flags AND all five v1.0 view flags satisfied).
- After stop: skill renders the draft from accumulated answers — including §§9-13 contracts (mechanical / coverage / exemplar-bindings).
- Confirm: yes / refine "\<change\>" / cancel.
- On yes: pre-lock evaluator runs Tier 1 (AST + v1.0 structural) + Tier 2 (coverage_gate + cross_view_gate) + Tier 3 if configured. Tier 2's `cross_view_gate` resolves cross-view string references (e.g. `<halt-hint from §8.2 ux-contract>`), validates every `exemplar:<view-type>:<slug>` binding against the catalog, enforces taxonomy-version match, and flags fingerprint↔hard-contract contradictions. Block findings halt; warn/info pass through.
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

## Exemplars & Bindings

v1.0's metis catalog lives at [`docs/exemplars/`](docs/exemplars/) — 17 seed exemplars across 5 view-types (help-text, error-text, log-format, api-shape, observability). Each exemplar names a real tool whose conventions are well-documented (curl, gh, rustc, git, systemd-journal, nginx, structlog-json, stripe-rest, github-graphql, kubernetes-api, prometheus, tmux-status, htop, postgres, rust-compiler).

In a §§9-13 view section, bind an exemplar with the form `<aspect>-style: exemplar:<view-type>:<slug>` — e.g. `help-text-style: exemplar:help-text:curl`. Tier 2's `cross_view_gate` validates the binding against the catalog at lock time; Tier 3 (if enabled) injects the bound exemplar's `conventions:` list into its contradiction prompt so DeepSeek can flag steps whose output would violate those conventions.

The catalog is operator-extensible: drop a markdown file at `~/.spectre/exemplars/<view-type>/<slug>.md` to add a private exemplar. User-overlay entries with the same key as a plugin entry **shadow** the plugin — `spectre exemplars validate` surfaces the shadow event so you can spot accidental overrides.

```bash
spectre exemplars list                        # all entries (plugin + overlay)
spectre exemplars list --view-type help-text  # filter by view-type
spectre exemplars show help-text:curl         # frontmatter + body for one entry
spectre exemplars axes help-text              # axis taxonomy for a view-type
spectre exemplars validate                    # conformance check (CI-friendly)
```

Full catalog reference + contribution guide: [`docs/exemplars/README.md`](docs/exemplars/README.md).

## Troubleshooting

The table below covers the most common halts in `/vision` and `/implement` happy paths. Each `remediation=` field is also emitted inline when the halt fires.

| Halt code | What it means | Remediation |
|---|---|---|
| `walker.open-questions-unresolved` | The interview detected open questions in your intent that are not yet answered or deferred. | answer each question or run 'spectre walker defer-open-question --id <oq-id> --adr <slug>' |
| `envelope.check status=tampered` | The locked spec or its sidecar was modified after the seal was generated. | run /vision and lock the spec to produce an envelope |
| `envelope.check status=missing` | `/implement` was invoked without a locked spec. | run /vision and lock the spec to produce an envelope |
| `unsupported-spec-version` | The spec lacks `**Spec-version:** 1.0` frontmatter or carries a different value. v1.0 is hard-cutover from v0.9. | re-run /vision to regenerate the spec at v1.0 |
| `missing-view-section` | One of §§9-13 is absent. Every view must be present (with content) or explicitly marked `not-applicable`. | add the missing section per the v1.0 template, or mark the view not-applicable in its §8.x substrate block |
| `missing-substrate-block` | One of §§8.3-8.7 is absent. | add the missing ### 8.x substrate block per the v1.0 template |
| `malformed-view-contract` | A view section declares no contracts (no Mechanical / Coverage / Exemplar bindings subsection). | add at least one contract subsection to the view, or mark it not-applicable |
| `cross-view-string-unresolved` | A view references a §8.x field that doesn't exist (typo or missing field). | add the named field to the referenced §8.x block, or correct the reference |
| `exemplar-not-found` | The spec binds `exemplar:<key>` and no entry by that key exists in the plugin catalog or user overlay. | run `spectre exemplars list` for valid slugs, or author a new exemplar at ~/.spectre/exemplars/<view-type>/<slug>.md |
| `exemplar-taxonomy-mismatch` | The bound exemplar's `taxonomy-version` differs from the version pinned in the spec. | run `spectre catalog upgrade-taxonomy --spec <slug> --to <version>`, or pick an exemplar at the pinned version |
| `view-fingerprint-contradicts-hard-contract` | A §8.x fingerprint contradicts §8.1 (e.g. §8.5 gui-only vs §8.1 mutates including stdout). | change the §8.x fingerprint OR remove the contradicting path from §8.1 mutates |
| `excessive-not-applicable` | More than two of the five non-agent views are marked not-applicable. | review each N/A: legitimately out-of-scope, or have you skipped a propagation event? |
| `track.queue` | Another parallel track holds the requested resource lock. | wait for the holding track to release or pass --skip-queue to bypass |
| `hydrate.stale_active` | `.active` points to a spec that no longer exists on disk. | run /vision to start a new spec or 'spectre _scratchpad reset' |

For any other code, `spectre explain <code>` gives the full glossary entry including its `user_action:` field.

## API

Full API reference — hooks, skills, spec step schema, sidecar format, and layout — lives at [`docs/API.md`](docs/API.md).

**v1.0 component versions** — plugin `1.0.0` (`.claude-plugin/marketplace.json`), `EVALUATOR_VERSION = "1.0.0"` (`bin/spec_evaluator.py`), `WALKER_VERSION = "1.0.0"` (`bin/walker.py`). Walker state files persisted under v0.9 are rejected on load; remove `state/.walk.json` and re-run `/vision` to migrate (hard cutover; no version-dispatch migration tool).

**v1.0 CLI surface** — top-level `spectre <subcommand>` covers:

- `spectre walker init-or-resume | peek-pending | answer-concern | get-state | yield-check | …` — interview state machine.
- `spectre substrate_wizard run | run --view <view>` — §§8.2-8.7 substrate calibration; per-view fingerprint + trust vocabularies.
- `spectre exemplars list | show | axes | validate` — metis catalog access (see [Exemplars & Bindings](#exemplars--bindings) above).
- `spectre glossary | explain <code>` — status-code + term registry.
- `spectre spec_evaluator | _glossary | _catalog | findings | …` — direct module CLIs (rarely invoked from prose; called by skills).

Tier-3 budget instrumentation emits one stderr line per `evaluate()` call: `INFO tier3.budget {"calls":1,"exemplars_injected":N,"dismissals_by_fp":{…}}`. JSON payload is harness-parseable (`json.loads(line.split(" ", 2)[2])`).

## Architecture

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full breakdown: hook flow, skill protocols, evaluator pipeline, resource-lock supervisor, and the design rationale behind the three-tier defense.

Skill invocations use the `spectre` shell wrapper (`bin/spectre`) — it resolves `${CLAUDE_PLUGIN_ROOT}`, exports `PYTHONPATH`, and delegates to `python3 -m bin.<subcommand>`. Skill prose shows `spectre walker init-or-resume …`; the `PYTHONPATH` plumbing never appears in runtime output.

CLI status lines follow a single grammar: `<LEVEL> <code> key=value …` where `LEVEL ∈ {ok, info, warn, halt, error, result, prompt}` and `code` is a stable dot-namespaced identifier (`walker.init`, `eval.summary`, `tier.classify`, …). See [`docs/API.md`](docs/API.md#cli-output-grammar) for the full vocabulary.

## Tests

```bash
pytest tests/                  # 1748 tests, all stdlib + pytest
pytest tests/ -v               # verbose
pytest tests/test_spec_evaluator.py -v   # single module
```

Test discipline:

- Stdlib + pytest only. No mocks of `urllib.request` outside `test_llm_judge.py`. No mocks of network for any other module.
- Pragma test-gaming guard: tests with `rejects/raises/refuses/denies` in the name without `pytest.raises` are blocked at edit time.
- 1:1 module → test mapping for production code (every `bin/<x>.py` has at least one `tests/test_<x>*.py`); plus four integration/E2E tests: bundle handoff (`test_bundle_handoff_integration.py`), dismissal flow (`test_dismiss_integration.py`), evaluator regression (`test_btc_poller_regression.py`, using a BTC-poller spec fixture), and a full hydrate→implement→compact cycle (`test_e2e.py`).
- Shared fixture builders live in `tests/fixtures/` (e.g. `stub_helpers.py`, `spec_template.py`) — used across multi-file test clusters for one module.

## Maintainers

[@Joncik91](https://github.com/Joncik91)

## Contributing

Issues and PRs welcome. See [`CONTRIBUTING.md`](CONTRIBUTING.md) for test discipline, the Pragma guard, the stdlib-only rule, and the review process. This README follows the [Standard-Readme](https://github.com/RichardLitt/standard-readme) spec.

## License

[MIT](./LICENSE) © Joncik91
