# No Path Captures Spec (test fixture)

**Generated:** 2026-05-05
**Slug:** no-path-captures

## 1. Hard Problem
Verifying tool availability requires running path-less commands that don't touch the filesystem.

## 2. First Principles
- Version checks are idempotent and safe.
- Path-less commands cannot produce calibration violations.

## 3. Algorithm Audit
- **Delete:** unnecessary filesystem writes
- **Simplify:** version-check only

## 4. Speed-of-Light Limit
Checks complete in under 1 second.

## 5. Physics Guardrails
- pip and python3 must be installed.

## 6. Steps

```yaml
- step: 1
  why: "Must confirm pip is available before any install step."
  action: "pip --version"
  verification: "pip --version | grep -q pip"

- step: 2
  why: "Must confirm python3 is available and meets version requirement."
  action: "python3 --version"
  verification: "python3 --version | grep -q 3"
```

## 7. Success Criteria
- [ ] pip and python3 both available.

## 8. Receiver Calibration

### 8.1 Hard contract (machine-enforced — `block` severity on violation)

- `mutates:` /tmp/
- `never-touches:` /home, /etc/
- `decision-budget:` none
- `reboot-survival:` not-required

### 8.2 Human-facing notes (informational only — `info` severity, never blocks)

- `assumes:` python3 installed
- `runtime-flavor:` A8 (Debian 13)
