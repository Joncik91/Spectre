"""tests/test_v1_1_e2e.py — v1.1 acceptance gate (synthetic spec).

Exercises every v1.1 finding kind in a single synthetic spec and verifies
the Fix 4 regression (self-cycle-produces must NOT fire for --out pattern).

Approach: direct module invocation via spec_ast.classify + cross_view_gate.classify
rather than subprocess or the full spec evaluator. Avoids spec-parsing fragility
(no walker, no scratchpad, no LLM Tier-3).

Finding kinds exercised:
  Fix 1:  view-fingerprint-contradicts-exemplar-binding
  Fix 2:  post-ship-iteration-deferral (×2) + excessive-post-ship-iteration
  Fix 3:  verification-too-shallow-for-claim
  Fix 4:  self-cycle-produces must NOT fire on --out flag pattern (regression)
"""
import pathlib

from bin import cross_view_gate
from bin import spec_ast

# ── Synthetic spec ─────────────────────────────────────────────────────────────
#
# Design notes:
#
# Fix 1 trigger: §8.5 fingerprint = gui-only, §11 binds exemplar:error-text:gh
#   which is calibrated-for [cli-power-user, cli-novice].
#   _check_fingerprint_vs_exemplar sees gui-only ∉ {cli-power-user, cli-novice}.
#
# Fix 2 trigger: §9 and §12 each declare `<aspect>-style: post-ship-iteration`.
#   _check_exemplar_bindings emits post-ship-iteration-deferral for each.
#   _check_excessive_post_ship_iteration aggregates (count=2 > 1).
#
# Fix 3 trigger: Step 2 — behavioral verb "prevent" in why + "test -f" verification.
#
# Fix 4 regression: Step 3 — node script.mjs --out path.yml + produces file:path.yml.
#   Must NOT fire self-cycle-produces (output-flag exclusion from Fix 4).
#
# The spec uses **Spec-version: 1.0** to activate v1.0 cross-view checks.
# §8.2 is the implementing-agent substrate (needed to suppress missing-substrate-block).
# §§8.3-8.7 provide minimal receiver-fingerprint fields for Fix 1.
# §§9-13 carry the relevant bindings; §10, §13 use not-applicable to keep size down.

_V1_1_SYNTHETIC_SPEC = """\
# v1.1 Acceptance Synthetic Spec

**Generated:** 2026-05-14
**Slug:** v1-1-synthetic
**Spec-version:** 1.0

## 1. Hard Problem
Testing that all v1.1 Tier-1 and Tier-2 findings fire correctly.

## 2. First Principles
- Every new check must fire on a crafted positive case.
- Every regression must not fire on a crafted negative case.

## 3. Algorithm Audit
- deterministic

## 4. Speed-of-Light Limit
Immediate — all checks are O(spec-size).

## 5. Physics Guardrails
- None.

## 6. Steps

```yaml
- step: 1
  why: "Bootstrap the lexicon file for downstream consumers."
  action: "node scripts/build-lexicon.mjs"
  verification: "test -f /tmp/v11-synthetic/lexicon.ts"
  produces:
    - "file:/tmp/v11-synthetic/lexicon.ts"
  negative-paths:
    - trigger: "build fails"
      handler: "abort"

- step: 2
  why: "the recalibration trigger must prevent drift when N=5 illegibility events accumulate"
  action: "node scripts/build-lexicon.mjs"
  verification: "test -f /tmp/v11-synthetic/lexicon.ts"
  produces:
    - "file:/tmp/v11-synthetic/lexicon.ts"
  negative-paths:
    - trigger: "build fails"
      handler: "abort"

- step: 3
  why: "Scaffold the GitHub Action definition file using the output-flag pattern."
  action: "node scripts/scaffold.mjs --out /tmp/v11-synthetic/action.yml"
  verification: "test -f /tmp/v11-synthetic/action.yml"
  produces:
    - "file:/tmp/v11-synthetic/action.yml"
  negative-paths:
    - trigger: "scaffold fails"
      handler: "abort"
```

## 7. Success Criteria
- [ ] All v1.1 findings fire.
- [ ] Fix 4 regression does not fire.

## 8. Receiver Calibration

### 8.1 Hard contract (machine-enforced — `block` severity on violation)

- `mutates:` /tmp/v11-synthetic/
- `never-touches:` /etc
- `decision-budget:` none
- `reboot-survival:` none

### 8.2 Cognitive-substrate contract

- receiver-fingerprint: claude-code+human
- trust-profile: none
- contextual-binding: synthetic acceptance test for v1.1 checks
- provenance: { kind: none }
- ux-contract:
    on-success: checks pass
    on-failure: checks fail
    log-target: stdout
- assumptions-killed: none
- requires-situated-judgment: []
- roi-budget: none

### 8.3 Product-input substrate

- receiver-fingerprint: human-typed
- trust-profile: none
- contextual-binding: synthetic input
- ux-contract:
    on-success: accepted
    on-failure: rejected
    log-target: stdout
- assumptions-killed: none

### 8.4 Product-output substrate

- not-applicable: no product output in this synthetic spec

### 8.5 Human-user substrate

- receiver-fingerprint: gui-only
- trust-profile: none
- contextual-binding: GUI user reads results; no CLI surface
- ux-contract:
    on-success: results displayed in GUI
    on-failure: GUI shows error
    log-target: stdout
- assumptions-killed: none

### 8.6 Integrator substrate

- receiver-fingerprint: api-consumer
- trust-profile: none
- contextual-binding: REST API consumer
- ux-contract:
    on-success: 2xx response
    on-failure: 4xx with error field
    log-target: stdout
- assumptions-killed: none

### 8.7 Operator substrate

- receiver-fingerprint: self-operated
- trust-profile: none
- contextual-binding: single operator
- ux-contract:
    on-success: service healthy
    on-failure: service down
    log-target: stdout
- assumptions-killed: none

## 9. Product-Input View

### Exemplar bindings
- input-shape-style: post-ship-iteration
- taxonomy-version: help-text:1

## 10. Product-Output View

not-applicable: no product output

## 11. Human-User View

### Mechanical contracts
- help-flag: --help
- usage-on-stderr: none
- exit-code-on-error: 1

### Exemplar bindings
- help-text-style: exemplar:error-text:gh
- taxonomy-version: error-text:1

## 12. Integrator View

### Exemplar bindings
- api-shape-style: post-ship-iteration
- taxonomy-version: api-shape:1

## 13. Operator View

not-applicable: self-operated, no formal operator contracts needed
"""


def test_v1_1_acceptance_synthetic_spec(tmp_path: pathlib.Path) -> None:
    spec = tmp_path / "v1_1_synthetic.spec.md"
    spec.write_text(_V1_1_SYNTHETIC_SPEC, encoding="utf-8")

    tier1_findings = spec_ast.classify(spec)
    tier2_findings = cross_view_gate.classify(spec)
    all_findings = tier1_findings + tier2_findings
    kinds = {f.kind for f in all_findings}

    # Fix 1: fingerprint contradiction — §8.5 gui-only vs §11 cli-calibrated exemplar
    assert "view-fingerprint-contradicts-exemplar-binding" in kinds

    # Fix 2: two post-ship-iteration deferrals (§9 and §12)
    deferrals = [f for f in all_findings if f.kind == "post-ship-iteration-deferral"]
    assert len(deferrals) == 2

    # v1.3 #8: §9 now maps to input-shape which has cli-argparse-shape (human-typed)
    # and openapi-request-body (programmatic-trusted) — both compatible with the
    # human-typed fingerprint in §8.3.  §12 (api-shape|ipc-rpc) has api-consumer
    # compatible exemplars.  Both deferrals are operator-deferral (compatible
    # exemplars exist; operator chose to defer).  Count=2 > 1 → excessive fires.
    by_reason = {d.reason for d in deferrals}
    assert by_reason == {"operator-deferral"}
    assert "excessive-post-ship-iteration" in kinds

    # Fix 3: behavioral why + structural-only verification on step 2
    assert "verification-too-shallow-for-claim" in kinds

    # Fix 4 regression: --out flag must NOT trigger self-cycle-produces on step 3
    assert "self-cycle-produces" not in kinds
