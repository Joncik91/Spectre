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

## 6. Steps

Each step is an atomic transaction with three required keys plus one optional:
- `why:` one-line first-principles justification — *not* analogy. This is the "Reasoning in Public" line that gets printed before the action runs.
- `action:` the exact shell command to execute (single line, no pipes spanning multiple commands unless necessary).
- `verification:` the exact shell command that must exit 0 to prove the action succeeded.
- `properties:` (optional) — list of PBT-lite assertions the State Auditor will check after `verification` passes. Each property has `kind:` (one of `type` / `schema` / `length` / `range`), `target:` (path to a JSON file), and kind-specific fields. See `bin/auditor.py` for supported shapes. Auditor verdicts are informational, not blocking — they land in scratchpad and the next compact's additionalContext.
- `resources:` (optional) — list of Resource node IDs this step needs to acquire before executing. Each entry is a string matching a Resource node in `specs/.graph.md`. The supervisor grants access; if at capacity, the track queues. Released automatically after the step's verification passes (or on terminal halt).

```yaml
- step: 1
  why: "<one-line justification grounded in first principles>"
  action: "<command>"
  verification: "<post-condition check command>"
  properties:                     # OPTIONAL — auditor runs PBT-lite checks if present
    - kind: type                  # type | schema | length | range
      target: "/path/to/output.json"
      expected: dict
    - kind: length
      target: "/path/to/output.json"
      target_field: "rows"
      min: 1
      max: 10

- step: 2
  why: "<one-line justification grounded in first principles>"
  action: "<command>"
  verification: "<post-condition check command>"

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
