# <Title>

**Generated:** <ISO date>
**Slug:** <slug>

## 1. Hard Problem
<One paragraph. The non-obvious thing that makes this hard.>

## 2. First Principles
<Bullet list. Physical/logical constraints, not analogies.>

## 3. Algorithm Audit
- **Delete:** <what we are NOT doing and why>
- **Simplify:** <what collapses to one primitive>
- **Accelerate:** <what gets faster after this>

## 4. Speed-of-Light Limit
<One paragraph. The fastest/most efficient version this tool could possibly be — the physical ceiling.>

## 5. Physics Guardrails
<Bullet list. System invariants that must remain true (filesystem state, root-level constraints, network reachability).>

> **Spectre executor invariants (not spec-author obligations):** The executor
> creates and manages `state/.venv/` automatically (v0.5.2+). Specs must not
> declare a PEP 668 strategy (system Python, venv path,
> `--break-system-packages`, pipx, etc.). All `python`/`python3`/`pip`/`pip3`
> action tokens are rewritten to the venv interpreter by `normalize_action`
> before execution. Only list invariants that your spec's actions must preserve
> — not environment setup that Spectre owns.

> **Spectre handoff envelope (v0.6+):** The lock step writes `specs/<slug>.envelope.json` carrying a SHA-256 integrity hash over the spec + sidecar + contracts. `/implement` verifies this hash on startup; mismatch halts execution. Specs must not modify `<slug>.envelope.json` directly — re-running `/vision` is the only legitimate way to update it.

## 6. Steps

> **Python environment (v0.5.2+):** Spectre creates `state/.venv/` automatically.
> Write bare `python3 script.py` or `pip install -e .` — the executor rewrites
> them to use the venv interpreter. Do **not** hard-code `.venv/bin/python` or
> declare `--break-system-packages` in actions.

Each step is an atomic transaction with three required keys plus optional contract and resource fields:
- `why:` one-line first-principles justification — *not* analogy. This is the "Reasoning in Public" line that gets printed before the action runs.
- `action:` the exact shell command to execute (single line, no pipes spanning multiple commands unless necessary).
- `verification:` the exact shell command that must exit 0 to prove the action succeeded.
- `produces:` (optional) — list of contract entries this step creates. Each entry is `<type>:<value>`. The evaluator uses these to resolve later steps' `requires:` entries. Omitting produces/requires is allowed but emits a `missing-contract` warning (non-blocking).
- `requires:` (optional) — list of contract entries this step needs. Every entry must appear in some prior step's `produces:`, or the evaluator emits an `unowned-requirement` block finding.
- `negative-paths:` (optional, recommended for steps with `produces:`) — list of `{trigger, handler}` pairs declaring the expected failure branches for this step. `trigger` is a condition string (e.g. `"pip install fails (network or PEP 668)"`). `handler` is one of `"reject"` (fail the step immediately), `"escalate"` (halt and surface to the user for manual intervention), or a free-text recovery action. Missing `negative-paths:` on a step with `produces:` emits a `warn`-severity `missing-negative-path` finding. When §8.1 declares `reboot-survival: required`, missing `negative-paths:` on any step with `produces:` is **block-severity** — failure semantics are load-bearing when data-loss risk exists.
- `properties:` (optional) — list of PBT-lite assertions the State Auditor will check after `verification` passes. Each property has `kind:` (one of `type` / `schema` / `length` / `range`), `target:` (path to a JSON file), and kind-specific fields. See `bin/auditor.py` for supported shapes. Auditor verdicts are informational, not blocking — they land in scratchpad and the next compact's additionalContext.
- `resources:` (optional) — list of Resource node IDs this step needs to acquire before executing. Each entry is a string matching a Resource node in `specs/.graph.md`. The supervisor grants access; if at capacity, the track queues. Released automatically after the step's verification passes (or on terminal halt).

**Contract types** (for `produces:` and `requires:`). Type prefixes are lowercase (`package:`, not `Package:`):
- `file:<path>` — absolute path to a file authored by the action
- `package:<name>` — Python package made importable (e.g. via `pip install -e .`)
- `console-script:<name>` — shell-PATH-resolvable command registered by an editable install
- `route:<METHOD> <path>` — HTTP route added (e.g. `route:POST /api/convert`)
- `module:<dotted.name>` — Python module path
- `binary:<name>` — system binary available on PATH (yt-dlp, curl, pip)
- `db-table:<name>` — SQLite table created
- `db-column:<table>.<col>` — column on a table

```yaml
- step: 1
  why: "<one-line justification grounded in first principles>"
  action: "pip install mypackage"
  verification: "python3 -c 'import mypackage'"
  produces:
    - "package:mypackage"
    - "console-script:mypackage-cli"

- step: 2
  why: "<one-line justification grounded in first principles>"
  action: "mypackage-cli --setup > /opt/mypackage/config.json"
  verification: "test -f /opt/mypackage/config.json"
  requires:
    - "package:mypackage"
    - "console-script:mypackage-cli"
  produces:
    - "file:/opt/mypackage/config.json"
  negative-paths:                 # OPTIONAL — recommended when produces: is set; REQUIRED (block) when §8.1 reboot-survival: required
    - trigger: "pip install fails (network or PEP 668)"
      handler: "escalate"
    - trigger: "package installs but import fails"
      handler: "reject"
  properties:                     # OPTIONAL — auditor runs PBT-lite checks if present
    - kind: type                  # type | schema | length | range
      target: "/opt/mypackage/config.json"
      expected: dict

- step: 3
  why: "Server must bind a known TCP port; lock prevents two tracks racing for it."
  action: "python3 -m http.server 8080"
  verification: "curl -sf http://127.0.0.1:8080 > /dev/null"
  resources:
    - res-port-8080
```

## 7. Success Criteria
- [ ] <binary pass/fail>
- [ ] <binary pass/fail>

## 8. Receiver Calibration

This section declares the spec author's contract with the executor. Split into hard contract (machine-enforced) and human-facing notes (informational only). The pre-lock spec evaluator (v0.3+) cross-checks §8.1 against actions' actual path captures.

### 8.1 Hard contract (machine-enforced — `block` severity on violation)

Every spec MUST declare the following four fields. The evaluator blocks lock if any are absent or if any action's path captures violate them.

- `mutates:` — comma-separated paths the spec is authorized to write/modify (e.g. `/opt/btc-poller/, /etc/systemd/system/`)
- `never-touches:` — comma-separated paths the spec MUST NOT write to (e.g. `/home, /etc/passwd`)
- `decision-budget:` — paid-API call budget (e.g. `1 paid API call per minute (CoinGecko free tier)` or `none`)
- `reboot-survival:` — `required` | `best-effort` | `none`

### 8.2 Cognitive-substrate contract (v0.7+ — auto-injected by wizard)

§8.2 is filled in automatically by `bin/substrate_wizard` at /vision Step 0.5. Spec authors should NOT edit it by hand — re-run /vision to update. Schema:

```markdown
### 8.2 Cognitive-substrate contract

# block-severity (must be present + non-empty)
- receiver-fingerprint: <claude-code+human | claude-code-autonomous | non-claude-ai | human-only>
- trust-profile: <comma-separated subset or "none">
- contextual-binding: <one-line description of what this spec is FOR>
- provenance: <{ kind: derived-from, parent-slug: <slug>, parent-envelope-sha256: <hex64> } | { kind: none }>
- ux-contract:
    on-success: <one-line operator-visible message>
    on-failure: <one-line operator-visible message + remediation hint>
    log-target: <path or stream>

# warn-severity (block only when assumptions-killed empty AND steps>3)
- assumptions-killed: <list of considered-and-ruled-out alternatives>
- requires-situated-judgment: <list of step IDs; cap = max(1, floor(0.3 × n_steps))>
- roi-budget: <yield-curve slope target / scaffolding cost ceiling>
```

**Per-step trust annotations (mandatory when trust-profile includes untrusted-input or handles-secrets):**

```yaml
- step: 3
  why: "fetch external JSON"
  action: "curl -fsSL https://example.com/data > /tmp/x.json"
  verification: "test -f /tmp/x.json"
  produces: ["file:/tmp/x.json"]
  untrusted-input: "yes"        # MANDATORY under untrusted-input profile
  halt-hint: "fetch failed: check network or signed-URL expiry"

- step: 4
  why: "extract + sanitize title"
  action: "jq '.title' /tmp/x.json | sanitize-html > /tmp/y.txt"
  verification: "test -f /tmp/y.txt"
  produces: ["file:/tmp/y.txt"]
  sanitizes: ["file:/tmp/y.txt"]   # clears taint on the OUTPUT only; /tmp/x.json stays tainted
  requires: ["file:/tmp/x.json"]
```

**Sink categories (Tier 1 detects taint reaching any of these):**
- filesystem-write: `mutates:` paths
- shell-eval: `bash -c "$(cat …)"`, `python -c`, `node -e`, eval-equivalent
- SQL/template: INSERT/UPDATE/REPLACE/DELETE FROM, jinja2/template_render
- network-egress: `curl|wget POST|PUT|--data|-T|--post-file=` with body from a tainted produces
