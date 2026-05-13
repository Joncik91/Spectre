# <Title>

**Generated:** <ISO date>
**Slug:** <slug>
**Spec-version:** 1.0

> **Six-view spec model (v1.0+):** §§1-7 below are calibrated to the **implementing-agent** receiver — the executor that will run the steps. The product the steps build propagates to five other receivers (product-input, product-output, human-user, integrator, operator). §8 carries one substrate-calibration block per view (§§8.1-8.7); §§9-13 declare each non-agent view's contracts. Views not applicable to a given product are marked `not-applicable: <reason>` in their §8.x block and omit their §9-13 section body. More than two N/A views emits an `excessive-not-applicable` warn finding.

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

### 8.3 Product-input substrate (v1.0+)

Same schema as §8.2 but calibrated to the product's **input receiver**: what feeds the product. Fingerprint vocabulary differs.

```markdown
### 8.3 Product-input substrate

- receiver-fingerprint: <human-typed | programmatic-trusted | programmatic-untrusted | streamed-event | not-applicable>
- trust-profile: <comma-separated subset of {validated-schema, signed-payload, rate-limited, untrusted} or "none">
- contextual-binding: <what input this product accepts and from where>
- ux-contract:
    on-success: <one-line acknowledgement the product emits when input is accepted>
    on-failure: <one-line rejection message + cause>
    log-target: <where input-handling logs go>
- assumptions-killed: <considered-and-ruled-out input shapes>
```

When `receiver-fingerprint: not-applicable`, §9 body is omitted (declare a single `not-applicable: <reason>` field in place of the §9 contracts).

### 8.4 Product-output substrate (v1.0+)

Same schema as §8.2 but calibrated to the product's **output receiver**: what reads the product's output.

```markdown
### 8.4 Product-output substrate

- receiver-fingerprint: <human-reader | programmatic-consumer | streaming-sink | log-aggregator | not-applicable>
- trust-profile: <comma-separated subset of {schema-stable, versioned, deprecation-policy} or "none">
- contextual-binding: <what output this product emits and who consumes it>
- ux-contract:
    on-success: <one-line success-output shape>
    on-failure: <one-line failure-output shape + how the consumer detects failure>
    log-target: <where output is written>
- assumptions-killed: <considered-and-ruled-out output shapes>
```

### 8.5 Human-user substrate (v1.0+)

Calibrated to the **direct human user** of the product (CLI invoker, dashboard user, anyone who reads the product's user-facing surface).

```markdown
### 8.5 Human-user substrate

- receiver-fingerprint: <cli-power-user | cli-novice | gui-only | no-human-user | not-applicable>
- trust-profile: <comma-separated subset of {accessibility-required, i18n-required, screen-reader-compatible} or "none">
- contextual-binding: <who uses this product and in what context>
- ux-contract:
    on-success: <one-line user-visible success message>
    on-failure: <one-line user-visible failure message + recovery hint>
    log-target: <where user-readable logs go, if any>
- assumptions-killed: <considered-and-ruled-out user-experience choices>
```

### 8.6 Integrator substrate (v1.0+)

Calibrated to the **integrator receiver**: another system or developer who programmatically integrates against this product.

```markdown
### 8.6 Integrator substrate

- receiver-fingerprint: <library-consumer | api-consumer | webhook-subscriber | sdk-author | no-integrator | not-applicable>
- trust-profile: <comma-separated subset of {semver-stable, breaking-change-policy, deprecation-window} or "none">
- contextual-binding: <what programmatic surface this product exposes and to whom>
- ux-contract:
    on-success: <one-line integration-success shape (e.g. "2xx with stable schema")>
    on-failure: <one-line integration-failure shape (e.g. "4xx with error-code field")>
    log-target: <where integration logs go>
- assumptions-killed: <considered-and-ruled-out integration shapes>
```

### 8.7 Operator substrate (v1.0+)

Calibrated to the **operator receiver**: whoever runs the product in production, watches its observability, gets paged when it breaks.

```markdown
### 8.7 Operator substrate

- receiver-fingerprint: <on-call-engineer | sre-team | self-operated | no-operator | not-applicable>
- trust-profile: <comma-separated subset of {paging-required, slo-defined, runbook-required} or "none">
- contextual-binding: <how this product is run in production and by whom>
- ux-contract:
    on-success: <one-line healthy-state observability signature>
    on-failure: <one-line unhealthy-state signature + paging trigger>
    log-target: <where operational logs go>
- assumptions-killed: <considered-and-ruled-out operational choices>
```

## 9. Product-Input View (v1.0+)

Declares contracts the product's input surface must satisfy. Three contract types may be combined; views may declare any subset.

```markdown
## 9. Product-Input View

### Mechanical contracts
- input-source: <stdin | file:<path> | network:<protocol> | env-var:<name>>
- encoding: <utf-8 | binary | mime-type>
- validation-schema: <inline JSON Schema | url:<schema-url> | none>
- retry-budget: <count | none>

### Coverage contracts
- input-must-include: <comma-separated required field categories>

### Exemplar bindings
- input-shape-style: exemplar:<slug>
- taxonomy-version: <view-type>:<int>
```

Cross-view references resolve through §8.x: e.g. `on-failure: <on-failure from §8.3 ux-contract>` resolves to whatever §8.3 declares. Broken references = `cross-view-string-unresolved` block finding at lock time.

When §8.3 declares `not-applicable`, replace this section's body with `not-applicable: <reason>`.

## 10. Product-Output View (v1.0+)

```markdown
## 10. Product-Output View

### Mechanical contracts
- output-sink: <stdout | file:<path> | network:<protocol>>
- encoding: <utf-8 | binary | mime-type>
- schema: <inline JSON Schema | url:<schema-url> | none>
- exit-code-on-success: <int>
- exit-code-on-failure: <int>

### Coverage contracts
- output-must-include: <comma-separated required field categories>

### Exemplar bindings
- output-shape-style: exemplar:<slug>
- taxonomy-version: <view-type>:<int>
```

When §8.4 declares `not-applicable`, replace this section's body with `not-applicable: <reason>`.

## 11. Human-User View (v1.0+)

```markdown
## 11. Human-User View

### Mechanical contracts
- help-flag: <comma-separated flags, e.g. `--help, -h`>
- usage-on-stderr: <required | none>
- exit-code-on-error: <int | nonzero>

### Coverage contracts
- help-text-must-include: <comma-separated: usage, flags, examples, link-to-docs, version>
- error-text-must-include: <comma-separated: what-failed, why, recovery>

### Exemplar bindings
- help-text-style: exemplar:<slug>
- error-text-style: exemplar:<slug>
- taxonomy-version: help-text:<int>, error-text:<int>
```

When §8.5 declares `not-applicable`, replace this section's body with `not-applicable: <reason>`.

## 12. Integrator View (v1.0+)

```markdown
## 12. Integrator View

### Mechanical contracts
- interface-style: <rest | graphql | grpc | library | webhook>
- versioning: <semver | url-path | header | none>
- breaking-change-policy: <one-line policy or `not-applicable`>
- spec-document: <openapi:<url> | sdl:<url> | inline | none>

### Coverage contracts
- error-response-must-include: <comma-separated: code, message, request-id>

### Exemplar bindings
- api-shape-style: exemplar:<slug>
- taxonomy-version: api-shape:<int>
```

When §8.6 declares `not-applicable`, replace this section's body with `not-applicable: <reason>`.

## 13. Operator View (v1.0+)

```markdown
## 13. Operator View

### Mechanical contracts
- log-format: <plaintext | json-lines | logfmt>
- log-keys: <comma-separated required keys, e.g. `timestamp, level, op, duration_ms`>
- metric-names: <comma-separated metric identifiers>
- health-endpoint: <path | none>

### Coverage contracts
- runbook-must-include: <comma-separated: symptoms, paging-trigger, recovery-steps>

### Exemplar bindings
- log-format-style: exemplar:<slug>
- observability-style: exemplar:<slug>
- taxonomy-version: log-format:<int>, observability:<int>
```

When §8.7 declares `not-applicable`, replace this section's body with `not-applicable: <reason>`.
