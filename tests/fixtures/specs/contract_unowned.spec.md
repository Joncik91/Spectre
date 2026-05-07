# Contract Unowned Spec (test fixture)

**Generated:** 2026-05-07
**Slug:** contract-unowned

## 1. Hard Problem
Step 2 declares a requires: that no prior step produces — testing unowned-requirement detection.

## 2. First Principles
- Requires entries without a prior produces are unresolvable.

## 3. Algorithm Audit
- **Delete:** none
- **Simplify:** none
- **Accelerate:** none

## 4. Speed-of-Light Limit
Instant — test fixture only.

## 5. Physics Guardrails
- /tmp/ must be writable.

## 6. Steps

```yaml
- step: 1
  why: "First step produces nothing relevant."
  action: "echo hello"
  verification: "echo hello"
  produces:
    - "file:/tmp/other-artifact"

- step: 2
  why: "Second step requires a package that was never produced."
  action: "python3 -c 'import missing_pkg'"
  verification: "python3 -c 'import missing_pkg'"
  requires:
    - "package:missing_pkg"
```

## 7. Success Criteria
- [ ] test fixture only

## 8. Receiver Calibration

### 8.1 Hard contract (machine-enforced — `block` severity on violation)

- `mutates:` /tmp/
- `never-touches:` /home
- `decision-budget:` none
- `reboot-survival:` none
